import os
import subprocess
from typing import Tuple

def open_in_explorer(target_path: str) -> bool:
    """
    Open File Explorer at the specified folder (UNC path or drive letter).
    """
    try:
        # Use explorer.exe directly
        subprocess.Popen(["explorer.exe", target_path])
        return True
    except Exception as e:
        try:
            os.startfile(target_path)
            return True
        except Exception:
            return False

def map_drive_letter(drive_letter: str, unc_path: str) -> Tuple[bool, str]:
    """
    Map an available drive letter (e.g. 'Z:') to a network UNC path.
    Note: Windows net use maps to the root or share name.
    """
    clean_letter = drive_letter.rstrip(":") + ":"
    cmd = f"net use {clean_letter} \"{unc_path}\" /persistent:no"
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if proc.returncode == 0:
            return True, f"成功将 {unc_path} 映射至盘符 {clean_letter}"
        else:
            return False, f"映射盘符失败: {proc.stderr.strip() or proc.stdout.strip()}"
    except Exception as e:
        return False, str(e)

def unmap_drive_letter(drive_letter: str) -> Tuple[bool, str]:
    """
    Unmap a drive letter.
    """
    clean_letter = drive_letter.rstrip(":") + ":"
    cmd = f"net use {clean_letter} /delete /y"
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return True, f"已释放盘符 {clean_letter}"
    except Exception as e:
        return False, str(e)

def create_desktop_shortcut(
    target_path: str,
    shortcut_name: str = "Ext4一键挂载小工具",
    arguments: str = "",
    icon_path: str = ""
) -> Tuple[bool, str]:
    """
    Create a Windows Desktop shortcut (.lnk) pointing to the app.
    """
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.exists(desktop):
        # Fallback to OneDrive Desktop if synced
        desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")

    lnk_path = os.path.join(desktop, f"{shortcut_name}.lnk")
    working_dir = os.path.dirname(os.path.abspath(target_path))

    icon_code = f"$s.IconLocation = '{icon_path}';" if icon_path and os.path.exists(icon_path) else ""
    ps_cmd = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{lnk_path}'); "
        f"$s.TargetPath = '{target_path}'; "
        f"$s.Arguments = '{arguments}'; "
        f"$s.WorkingDirectory = '{working_dir}'; "
        f"{icon_code} "
        f"$s.Save()"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True
        )
        if proc.returncode == 0 and os.path.exists(lnk_path):
            return True, lnk_path
        return False, proc.stderr.strip() or "创建快捷方式失败"
    except Exception as e:
        return False, str(e)
