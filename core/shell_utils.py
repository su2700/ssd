"""Explicit encodings for Windows PowerShell, WSL and native tools."""

import base64
import locale
import subprocess


def decode_output(data: bytes, wsl_management: bool = False) -> str:
    if not data:
        return ""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    # WSL management commands emit UTF-16LE even on non-English Windows.
    if b"\x00" in data:
        return data.decode("utf-16le", errors="replace").lstrip("\ufeff")
    if wsl_management:
        # A Chinese-only UTF-16LE error can contain no NUL bytes. Prefer UTF-8
        # when valid (newer WSL releases), otherwise use WSL's native UTF-16LE.
        try:
            return data.decode("utf-8-sig")
        except UnicodeError:
            return data.decode("utf-16le", errors="replace")
    for encoding in ("utf-8-sig", locale.getpreferredencoding(False), "gb18030"):
        try:
            return data.decode(encoding)
        except (UnicodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def run_text(*args, **kwargs):
    """Capture bytes first; WSL management and Linux output differ in encoding."""
    kwargs.pop("text", None)
    command = args[0] if args else kwargs.get("args", [])
    tokens = command.split() if isinstance(command, str) else command
    management = bool(tokens and tokens[0].lower() == "wsl.exe" and
                      not any(flag in tokens for flag in ("-e", "--exec", "--")))
    proc = subprocess.run(*args, **kwargs)
    if isinstance(proc.stdout, bytes):
        proc.stdout = decode_output(proc.stdout, wsl_management=management)
    if isinstance(proc.stderr, bytes):
        proc.stderr = decode_output(proc.stderr, wsl_management=management)
    return proc


def powershell_command(script: str):
    # EncodedCommand also preserves Chinese paths independently of CMD's code page.
    preamble = (
        "$ErrorActionPreference = 'Stop'; "
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); "
        "$OutputEncoding = [Console]::OutputEncoding; "
    )
    encoded = base64.b64encode((preamble + script).encode("utf-16le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def run_powershell(script: str, **kwargs):
    return run_text(powershell_command(script), capture_output=True, **kwargs)
