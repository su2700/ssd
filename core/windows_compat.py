"""Windows 10/11 and WSL feature checks; never install or modify the host."""

import os
import re
import sys
import subprocess

from .shell_utils import run_text, native_system_executable


def get_windows_support():
    if os.name != "nt":
        return {"name": sys.platform, "supported": False,
                "error": "此应用需要 Windows 10 (build 19041+) 或 Windows 11。"}
    version = sys.getwindowsversion()
    build = version.build
    name = "Windows 11" if build >= 22000 else "Windows 10"
    supported = version.major >= 10 and build >= 19041
    return {"name": name, "build": build, "supported": supported,
            "error": "" if supported else "请更新至 Windows 10 2004 (build 19041+) 或 Windows 11。"}


def get_wsl_capabilities():
    """Help option tokens are stable even when WSL's UI language changes."""
    try:
        proc = run_text([native_system_executable("wsl.exe"), "--help"],
                        capture_output=True, timeout=10)
        if proc.returncode != 0:
            return {"options": set(), "error": (proc.stderr or proc.stdout).strip()
                    or f"WSL help failed ({proc.returncode})"}
        return {"options": set(re.findall(r"--[a-z][a-z-]*", proc.stdout)), "error": ""}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"options": set(), "error": str(error)}


def mount_support_error(capabilities, *, named=True, vhd=False):
    required = {"--mount", "--unmount", "--bare"}
    if named:
        required.update(("--name", "--partition", "--type"))
    if vhd:
        required.add("--vhd")
    missing = required - capabilities.get("options", set())
    if capabilities.get("error") or missing:
        detail = capabilities.get("error") or "缺少 " + ", ".join(sorted(missing))
        return (f"当前 WSL 不支持此操作 ({detail})。\n"
                "Windows 10/11：请安装或更新 Microsoft Store 版 WSL，然后重试。\n"
                "管理员 PowerShell: wsl --update\n"
                "安装说明: https://learn.microsoft.com/windows/wsl/install")
    return ""


def get_wsl2_support_error(distro=None):
    host = get_windows_support()
    if not host["supported"]:
        return host["error"]
    from .disk_detector import get_wsl_distros
    info = get_wsl_distros()
    versions = info.get("versions", {})
    if info.get("error"):
        return info["error"]
    if distro and versions.get(distro) != 2:
        return f"发行版 [{distro}] 必须使用 WSL 2。请运行: wsl --set-version \"{distro}\" 2"
    if not any(version == 2 for version in versions.values()):
        return "未检测到 WSL 2 发行版。请先安装 WSL 2，并使用 wsl --set-version <发行版> 2 转换。"
    return ""


def get_mount_support_error(*, named=True, vhd=False, distro=None):
    """Preflight must finish before requesting elevation or modifying a disk."""
    error = get_wsl2_support_error(distro)
    if error:
        return error
    return mount_support_error(get_wsl_capabilities(), named=named, vhd=vhd)
