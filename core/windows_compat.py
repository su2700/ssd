"""Windows 10/11 and WSL feature checks; never install or modify the host."""

import os
import re
import sys
import subprocess

from .shell_utils import run_text, native_system_executable
from .diagnostics import format_issue, wsl_environment_error, explain_error


def get_windows_support():
    if os.name != "nt":
        return {"name": sys.platform, "supported": False,
                "error": format_issue("操作系统不兼容", "此应用依赖 Windows 的 WSL 2 和磁盘接口。",
                                      ["请在 Windows 10 (build 19041+) 或 Windows 11 上运行此应用。"])}
    version = sys.getwindowsversion()
    build = version.build
    name = "Windows 11" if build >= 22000 else "Windows 10"
    supported = version.major >= 10 and build >= 19041
    return {"name": name, "build": build, "supported": supported,
            "error": "" if supported else format_issue("Windows 版本过旧", f"当前 build {build} 低于应用要求的 19041。",
                ["打开“设置 → 更新和安全 → Windows 更新”，安装兼容的功能更新。",
                 "更新至 Windows 10 2004 (build 19041+) 或 Windows 11，按提示重启后再运行应用。"])}


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
        return {"options": set(), "error": str(error), "diagnostic": explain_error(error, context="wsl")}


def mount_support_error(capabilities, *, named=True, vhd=False):
    required = {"--mount", "--unmount", "--bare"}
    if named:
        required.update(("--name", "--partition", "--type"))
    if vhd:
        required.add("--vhd")
    missing = required - capabilities.get("options", set())
    if capabilities.get("error") or missing:
        detail = capabilities.get("error") or "缺少 " + ", ".join(sorted(missing))
        if capabilities.get("error"):
            return capabilities.get("diagnostic") or explain_error(capabilities["error"], context="wsl")
        return format_issue("当前 WSL 缺少所需功能", "已安装的 WSL 命令行不支持本次磁盘/VHD 操作需要的选项。",
                            ["在管理员 PowerShell 中运行 wsl --update，或安装/更新 Microsoft Store 版 WSL。",
                             "安装说明：https://learn.microsoft.com/windows/wsl/install",
                             "按提示重启后点击“刷新磁盘”，再重试操作；原始镜像仍可通过 WSL 2 loopback 挂载。"], detail)
    return ""


def get_wsl2_support_error(distro=None):
    host = get_windows_support()
    if not host["supported"]:
        return host["error"]
    from .disk_detector import get_wsl_distros
    info = get_wsl_distros()
    return wsl_environment_error(info, distro)


def get_mount_support_error(*, named=True, vhd=False, distro=None):
    """Preflight must finish before requesting elevation or modifying a disk."""
    error = get_wsl2_support_error(distro)
    if error:
        return error
    return mount_support_error(get_wsl_capabilities(), named=named, vhd=vhd)
