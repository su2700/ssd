"""Actionable user messages, independent of Tk and Windows GUI imports."""

import logging
import subprocess


class UserFacingError(RuntimeError):
    """An error already containing a cause and recovery instructions."""


def format_issue(problem, cause, steps, detail=""):
    message = f"问题：{problem}\n\n原因：{cause}\n\n解决方法：\n"
    message += "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))
    if detail:
        message += f"\n\n详细信息：\n{str(detail)[:1800]}"
    return message


def log_location():
    for handler in logging.getLogger("ext4_mounter").handlers:
        if isinstance(handler, logging.FileHandler):
            return handler.baseFilename
    return None


def explain_error(error, context="operation", log_path=None):
    detail = str(error)
    text = detail.lower()
    filename = str(getattr(error, "filename", "") or "").lower()
    code = getattr(error, "winerror", None)
    if detail.startswith("问题："):
        message = detail
    elif code == 1223 or any(s in text for s in ("uac cancelled", "uac canceled", "取消了管理员授权", "用户取消", "operation was canceled")):
        message = format_issue("管理员授权已取消", "物理磁盘/VHD 操作需要管理员权限，本次未获得授权。",
                               ["重新执行操作，在 UAC 对话框中选择“是”。", "如果设备由组织管理，请联系管理员授权。"], detail)
    elif "0x80370102" in text or "hcs_e_hyperv_not_installed" in text:
        message = format_issue("WSL 2 虚拟机无法启动", "虚拟机平台、固件虚拟化或虚拟机嵌套虚拟化可能未启用。",
                               ["在“启用或关闭 Windows 功能”中启用“虚拟机平台”，然后重启 Windows。",
                                "在 BIOS/UEFI 中启用 Intel VT-x/AMD-V；如果 Windows 本身运行在虚拟机中，请让管理员启用嵌套虚拟化。",
                                "运行 wsl -l -v 验证，然后回到应用点击“刷新磁盘”。"], detail)
    elif "0x8007019e" in text or "wsl_e_wsl_optional_component_required" in text:
        message = format_issue("WSL Windows 功能未启用", "当前 WSL 安装需要的 Windows 可选组件未启用。",
                               ["在“启用或关闭 Windows 功能”中启用“适用于 Linux 的 Windows 子系统”和“虚拟机平台”。",
                                "重启 Windows，运行 wsl --install 完成配置，再点击“刷新磁盘”。"], detail)
    elif "0x800701bc" in text:
        message = format_issue("WSL 2 内核需要更新", "当前 Linux 内核组件缺失或版本过旧。",
                               ["在管理员 PowerShell 中运行 wsl --update。", "按提示重启，再点击“刷新磁盘”。"], detail)
    elif isinstance(error, subprocess.TimeoutExpired) or "timed out" in text:
        message = format_issue("依赖程序未及时响应", "WSL 或磁盘查询超时，可能仍在启动或等待系统服务。",
                               ["稍候再点击“刷新磁盘”，并在 PowerShell 中运行 wsl --status、wsl -l -v 检查状态。",
                                "保存所有 WSL 工作后，可运行 wsl --shutdown 再重试；该命令会停止所有 WSL 会话。"], detail)
    elif any(s in text for s in ("tkinter", "_tkinter", "tcl", "tk runtime", "init.tk")) and context == "startup":
        message = format_issue("图形界面组件缺失或无法加载", "Python 的 Tcl/Tk 运行环境不完整，应用无法创建窗口。",
                               ["源码版：在 Python 安装程序中选择 Modify/Repair，安装“tcl/tk and IDLE”，然后运行 python -m tkinter 验证。",
                                "独立 exe 版：重新下载完整应用，或用包含 Tcl/Tk 的 Python 重新构建。"], detail)
    elif isinstance(error, FileNotFoundError) and (context == "wsl" or "wsl" in filename or "wsl" in text):
        message = format_issue("找不到 WSL", "系统无法启动 wsl.exe，WSL 可能尚未安装或安装已损坏。",
                               ["在管理员 PowerShell 中运行 wsl --install，并按提示重启 Windows。",
                                "若命令不可用，请从 Microsoft Store 安装 WSL：https://learn.microsoft.com/windows/wsl/install",
                                "完成 Linux 发行版首次启动配置，再回到应用点击“刷新磁盘”。"], detail)
    elif isinstance(error, FileNotFoundError) and (context == "disk" or "powershell" in filename or "powershell" in text):
        message = format_issue("找不到 Windows PowerShell", "磁盘查询依赖 Windows PowerShell 5.1，当前无法启动该程序。",
                               ["确认系统存在 %SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe。",
                                "请让管理员修复 Windows PowerShell/系统组件，然后重启应用。"], detail)
    elif isinstance(error, FileNotFoundError):
        message = format_issue("所需程序或文件不存在", "Windows 无法找到本次操作引用的程序或路径；详细信息可能包含缺失项。",
                               ["确认所选镜像/目录仍存在，重新选择有效路径。",
                                "在 PowerShell 中运行 Get-Command wsl.exe 和 Get-Command powershell.exe，确认依赖可用；缺少 WSL 时运行 wsl --install。",
                                "如果依赖存在仍失败，请提供日志中的完整异常以确定缺失路径。"], detail)
    elif isinstance(error, PermissionError) or code == 5 or any(s in text for s in ("access is denied", "access denied", "拒绝访问", "e_accessdenied")):
        message = format_issue("访问被拒绝", "当前账户或进程没有所需权限，也可能受到设备管理策略限制。",
                               ["物理磁盘/VHD 操作：重试并允许 UAC，或使用 start_as_admin.bat 启动。",
                                "文件操作：检查所选文件/目录的读取权限；受管理设备请联系管理员。"], detail)
    elif any(s in text for s in ("command not found", ": not found", "not recognized", "未找到命令")) and any(s in text for s in ("mkfs.ext4", "lsblk", "mount", "bash", "setfacl")):
        message = format_issue("Linux 工具缺失", "选中的 WSL 发行版缺少当前操作需要的 Linux 工具。",
                               ["打开选中的 Linux 发行版，安装详细信息中提示缺少的工具。",
                                "Ubuntu/Debian 示例：sudo apt update，然后 sudo apt install bash util-linux e2fsprogs acl。其他发行版请使用对应包管理器。",
                                "返回应用重试。"], detail)
    elif context == "wsl":
        message = format_issue("WSL 检测失败", "WSL 返回了错误；仅凭当前信息无法确定具体原因。",
                               ["在 PowerShell 中运行 wsl --status 和 wsl -l -v，查看系统提示。",
                                "根据提示安装或修复 WSL；若提示版本过旧，在管理员 PowerShell 中运行 wsl --update。",
                                "按要求重启后，点击“刷新磁盘”；仍失败时请将日志提供给维护者。"], detail)
    elif context == "disk":
        message = format_issue("磁盘信息查询失败", "PowerShell 存储/CIM 查询未成功，可能是权限、服务或设备状态问题。",
                               ["检查磁盘连接，并在 Windows“磁盘管理”中确认设备状态。",
                                "在 PowerShell 中运行 Get-Disk 和 Get-CimInstance Win32_DiskDrive 查看具体错误；权限不足时以管理员身份重试。",
                                "根据系统提示处理后点击“刷新磁盘”；请勿为解决检测问题而初始化或格式化已有数据的磁盘。"], detail)
    else:
        message = format_issue("操作未完成", "发生了尚未识别的错误，请根据详细信息进一步排查。",
                               ["保留详细信息，查看下方日志中的完整异常。",
                                "将日志和复现步骤提供给应用维护者；仅重试已确认安全的操作。"], detail)
    if log_path:
        message += f"\n\n日志：{log_path}"
    return message


def wsl_environment_error(info, distro=None):
    if info.get("error"):
        return info.get("diagnostic") or explain_error(info["error"], context="wsl")
    if not info.get("distros"):
        return format_issue("未安装 Linux 发行版", "WSL 没有可供应用使用的 Linux 环境。",
                            ["在 PowerShell 中运行 wsl --install -d Ubuntu，按提示重启。",
                             "首次启动 Ubuntu 并完成用户名/密码设置，然后点击“刷新磁盘”。"])
    versions = info.get("versions", {})
    if (distro and versions.get(distro) != 2) or not any(v == 2 for v in versions.values()):
        name = distro or info.get("default") or info["distros"][0]
        # PowerShell single-quoted literals preserve distro names with spaces or metacharacters.
        quoted = "'" + name.replace("'", "''") + "'"
        return format_issue("需要 WSL 2 发行版", "磁盘挂载需要 Linux 内核；WSL 1 无法提供该能力。",
                            [f"在 PowerShell 中运行 wsl --set-version {quoted} 2。",
                             "运行 wsl -l -v 确认 VERSION 为 2，然后点击“刷新磁盘”。",
                             "wsl --set-default-version 2 只影响新安装的发行版，不会转换已有发行版。"])
    return ""
