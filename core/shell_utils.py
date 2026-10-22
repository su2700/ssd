"""Explicit encodings for Windows PowerShell, WSL and native tools."""

import base64
import locale
import os
import subprocess


def native_system_executable(name: str) -> str:
    """Sysnative bypasses WOW64 redirection when Python is a 32-bit process."""
    if os.name == "nt":
        windows = os.environ.get("SystemRoot", r"C:\Windows")
        for folder in ("Sysnative", "System32"):
            path = os.path.join(windows, folder, name)
            if os.path.isfile(path):
                return path
    return name


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
    management = bool(tokens and os.path.basename(tokens[0]).lower() == "wsl.exe" and
                      not any(flag in tokens for flag in ("-e", "--exec", "--")))
    if isinstance(command, (list, tuple)) and command and command[0].lower() == "wsl.exe":
        command = [native_system_executable("wsl.exe"), *command[1:]]
        if args:
            args = (command, *args[1:])
        else:
            kwargs["args"] = command
    elif isinstance(command, str) and command.lower().startswith("wsl.exe "):
        command = subprocess.list2cmdline([native_system_executable("wsl.exe")]) + command[7:]
        if args:
            args = (command, *args[1:])
        else:
            kwargs["args"] = command
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
    return [native_system_executable("powershell.exe"), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def run_powershell(script: str, **kwargs):
    return run_text(powershell_command(script), capture_output=True, **kwargs)
