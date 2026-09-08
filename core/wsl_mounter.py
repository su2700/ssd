import ctypes
import json
import os
import re
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Tuple, Any

from .disk_detector import is_admin, get_wsl_distros

STATE_FILE = os.path.join(os.path.expanduser("~"), ".ext4_mounter_state.json")

def windows_to_wsl_path(win_path: str) -> str:
    """Convert Windows path C:\\foo\\bar to WSL path /mnt/c/foo/bar."""
    abs_path = os.path.abspath(win_path)
    match = re.match(r"^([a-zA-Z]):[\\/](.*)$", abs_path)
    if match:
        drive_letter = match.group(1).lower()
        sub_path = match.group(2).replace("\\", "/")
        return f"/mnt/{drive_letter}/{sub_path}"
    return abs_path.replace("\\", "/")

def get_best_distro(preferred_distro: Optional[str] = None) -> str:
    """Get the WSL distribution to use, defaulting to Ubuntu or default."""
    info = get_wsl_distros()
    distros = info.get("distros", [])
    if preferred_distro and preferred_distro in distros:
        return preferred_distro
    if "Ubuntu" in distros:
        return "Ubuntu"
    if info.get("default"):
        return info["default"]
    if distros:
        return distros[0]
    return "Ubuntu"

def run_elevated_command(cmd_line: str, timeout: int = 60) -> Tuple[int, str]:
    """
    Run a command with Administrator privileges using PowerShell Start-Process -Verb RunAs.
    Returns (exit_code, output_text).
    """
    temp_dir = tempfile.gettempdir()
    out_file = os.path.join(temp_dir, f"ext4_mounter_out_{int(time.time()*1000)}.log")
    err_file = os.path.join(temp_dir, f"ext4_mounter_err_{int(time.time()*1000)}.log")
    exit_file = os.path.join(temp_dir, f"ext4_mounter_code_{int(time.time()*1000)}.log")
    bat_file = os.path.join(temp_dir, f"ext4_mounter_run_{int(time.time()*1000)}.bat")

    # Construct batch script that captures stdout, stderr and exitcode
    bat_content = (
        f"@echo off\r\n"
        f"chcp 65001 >nul\r\n"
        f"{cmd_line} > \"{out_file}\" 2> \"{err_file}\"\r\n"
        f"echo %ERRORLEVEL% > \"{exit_file}\"\r\n"
    )

    try:
        with open(bat_file, "w", encoding="utf-8") as f:
            f.write(bat_content)

        # PowerShell command to elevate batch script
        ps_cmd = (
            f"Start-Process -FilePath 'cmd.exe' "
            f"-ArgumentList '/c \"{bat_file}\"' "
            f"-Verb RunAs -WindowStyle Hidden -Wait"
        )

        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=timeout
        )

        # Read results
        output = ""
        if os.path.exists(out_file):
            try:
                with open(out_file, "r", encoding="utf-8", errors="replace") as f:
                    output += f.read()
            except Exception:
                pass

        if os.path.exists(err_file):
            try:
                with open(err_file, "r", encoding="utf-8", errors="replace") as f:
                    err_text = f.read().strip()
                    if err_text:
                        output += "\n" + err_text
            except Exception:
                pass

        exit_code = 0
        if os.path.exists(exit_file):
            try:
                with open(exit_file, "r", encoding="utf-8") as f:
                    exit_code = int(f.read().strip())
            except Exception:
                exit_code = 1
        else:
            # If exit_file doesn't exist, user might have declined UAC prompt
            exit_code = 1
            if not output:
                output = "用户取消了管理员授权 (UAC) 或进程未正常执行。"

        return exit_code, output.strip()

    except Exception as e:
        return 1, f"提权执行失败: {str(e)}"
    finally:
        for p in (bat_file, out_file, err_file, exit_file):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

def load_saved_mounts() -> List[Dict[str, Any]]:
    """Load list of recorded active mounts from state file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_mounts(mounts: List[Dict[str, Any]]):
    """Save list of recorded active mounts to state file."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(mounts, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def register_mount(info: Dict[str, Any]):
    """Register a new mount into the state tracker."""
    mounts = load_saved_mounts()
    # Remove any existing entry with same mount_name
    mounts = [m for m in mounts if m.get("mount_name") != info.get("mount_name")]
    mounts.append(info)
    save_mounts(mounts)

def unregister_mount(mount_name: str):
    """Unregister a mount from the state tracker."""
    mounts = load_saved_mounts()
    mounts = [m for m in mounts if m.get("mount_name") != mount_name]
    save_mounts(mounts)


class WslMounter:
    def __init__(self, preferred_distro: Optional[str] = None):
        self.distro = get_best_distro(preferred_distro)

    def set_distro(self, distro: str):
        self.distro = distro

    def get_unc_path(self, mount_name: str) -> str:
        """Return the Windows UNC path to the mountpoint."""
        return f"\\\\wsl.localhost\\{self.distro}\\mnt\\wsl\\{mount_name}"

    def check_mount_exists(self, mount_name: str) -> bool:
        """Check if the mount folder exists in Windows or WSL."""
        unc = self.get_unc_path(mount_name)
        if os.path.exists(unc):
            return True
        # Check via WSL
        cmd = ["wsl.exe", "-d", self.distro, "-e", "test", "-d", f"/mnt/wsl/{mount_name}"]
        res = subprocess.run(cmd, capture_output=True)
        return res.returncode == 0

    def mount_physical_disk(
        self,
        disk_index: int,
        partition_number: int,
        mount_name: str,
        read_only: bool = True
    ) -> Tuple[bool, str, str]:
        """
        Mount a physical disk partition into WSL2.
        Returns: (success: bool, unc_path: str, message: str)
        """
        device_path = f"\\\\.\\PHYSICALDRIVE{disk_index}"
        mount_cmd = (
            f"wsl.exe --mount {device_path} "
            f"--partition {partition_number} "
            f"--name \"{mount_name}\" "
            f"--type ext4"
        )
        if read_only:
            mount_cmd += " --options ro"

        if is_admin():
            proc = subprocess.run(mount_cmd, shell=True, capture_output=True, text=True)
            exit_code = proc.returncode
            output = (proc.stdout + " " + proc.stderr).strip()
        else:
            exit_code, output = run_elevated_command(mount_cmd)

        unc_path = self.get_unc_path(mount_name)

        # Give WSL a moment to initialize the 9P share
        for _ in range(10):
            if os.path.exists(unc_path) or self.check_mount_exists(mount_name):
                break
            time.sleep(0.5)

        is_mounted = self.check_mount_exists(mount_name) or os.path.exists(unc_path)
        if exit_code == 0 or is_mounted:
            register_mount({
                "type": "physical",
                "disk_index": disk_index,
                "partition_number": partition_number,
                "device_path": device_path,
                "mount_name": mount_name,
                "read_only": read_only,
                "distro": self.distro,
                "unc_path": unc_path,
                "mounted_at": time.strftime("%Y-%m-%d %H:%M:%S")
            })
            return True, unc_path, f"物理磁盘分区挂载成功！挂载点: {unc_path}"
        else:
            return False, "", f"物理磁盘挂载失败 (代码: {exit_code}): {output}"

    def unmount_physical_disk(self, disk_index: int, mount_name: Optional[str] = None) -> Tuple[bool, str]:
        """
        Unmount and detach a physical disk from WSL2.
        """
        device_path = f"\\\\.\\PHYSICALDRIVE{disk_index}"
        unmount_cmd = f"wsl.exe --unmount {device_path}"

        if is_admin():
            proc = subprocess.run(unmount_cmd, shell=True, capture_output=True, text=True)
            exit_code = proc.returncode
            output = (proc.stdout + " " + proc.stderr).strip()
        else:
            exit_code, output = run_elevated_command(unmount_cmd)

        if mount_name:
            unregister_mount(mount_name)
        else:
            # Unregister any with this disk_index
            for m in load_saved_mounts():
                if m.get("disk_index") == disk_index:
                    unregister_mount(m.get("mount_name"))

        if exit_code == 0:
            return True, f"物理磁盘 {device_path} 已成功卸载并分离！"
        else:
            return False, f"卸载执行返回 (代码: {exit_code}): {output}"

    def mount_image_file(
        self,
        file_path: str,
        mount_name: str,
        read_only: bool = True
    ) -> Tuple[bool, str, str]:
        """
        Mount an ext4 image file (.img, .ext4, .vhdx, .raw).
        Uses WSL2 loop device or --vhd.
        Returns: (success: bool, unc_path: str, message: str)
        """
        abs_win_path = os.path.abspath(file_path)
        if not os.path.exists(abs_win_path):
            return False, "", f"文件不存在: {abs_win_path}"

        ext = os.path.splitext(abs_win_path)[1].lower()
        unc_path = self.get_unc_path(mount_name)

        if ext in (".vhdx", ".vhd"):
            # Native WSL VHD mount
            vhd_cmd = f"wsl.exe --mount \"{abs_win_path}\" --vhd --name \"{mount_name}\""
            if read_only:
                vhd_cmd += " --options ro"
            if is_admin():
                proc = subprocess.run(vhd_cmd, shell=True, capture_output=True, text=True)
                exit_code = proc.returncode
                output = (proc.stdout + " " + proc.stderr).strip()
            else:
                exit_code, output = run_elevated_command(vhd_cmd)

            if exit_code != 0 and not self.check_mount_exists(mount_name):
                return False, "", f"VHD 挂载失败: {output}"
        else:
            # Raw .img, .ext4, .raw image - mount via WSL2 loop device (NO Windows admin required!)
            wsl_file_path = windows_to_wsl_path(abs_win_path)
            opts = "loop,ro" if read_only else "loop,rw"
            bash_script = (
                f"mkdir -p '/mnt/wsl/{mount_name}' && "
                f"mount -o {opts} '{wsl_file_path}' '/mnt/wsl/{mount_name}'"
            )
            cmd = ["wsl.exe", "-d", self.distro, "-u", "root", "--", "bash", "-c", bash_script]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                return False, "", f"镜像挂载失败 (代码: {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"

        # Wait for UNC path availability
        for _ in range(10):
            if os.path.exists(unc_path) or self.check_mount_exists(mount_name):
                break
            time.sleep(0.5)

        register_mount({
            "type": "image",
            "file_path": abs_win_path,
            "mount_name": mount_name,
            "read_only": read_only,
            "distro": self.distro,
            "unc_path": unc_path,
            "mounted_at": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        return True, unc_path, f"ext4 镜像文件挂载成功！挂载点: {unc_path}"

    def unmount_image_file(self, mount_name: str, file_path: Optional[str] = None) -> Tuple[bool, str]:
        """
        Unmount an ext4 image file from WSL2.
        """
        ext = os.path.splitext(file_path or "")[1].lower()
        if ext in (".vhdx", ".vhd") and file_path:
            unmount_cmd = f"wsl.exe --unmount \"{file_path}\""
            if is_admin():
                proc = subprocess.run(unmount_cmd, shell=True, capture_output=True, text=True)
                exit_code = proc.returncode
                output = proc.stdout + proc.stderr
            else:
                exit_code, output = run_elevated_command(unmount_cmd)
        else:
            # Loop mount unmount
            bash_script = f"umount '/mnt/wsl/{mount_name}' && rmdir '/mnt/wsl/{mount_name}'"
            cmd = ["wsl.exe", "-d", self.distro, "-u", "root", "--", "bash", "-c", bash_script]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            exit_code = proc.returncode
            output = proc.stderr or proc.stdout

        unregister_mount(mount_name)
        if exit_code == 0:
            return True, f"镜像挂载点 {mount_name} 已成功卸载！"
        else:
            return False, f"卸载镜像返回 (代码: {exit_code}): {output.strip()}"

    def unmount_all(self) -> List[Tuple[str, bool, str]]:
        """
        Unmount all registered mounts and unmount WSL disks.
        Returns list of (name, success, message).
        """
        results = []
        mounts = load_saved_mounts()
        for m in mounts:
            m_type = m.get("type")
            m_name = m.get("mount_name")
            if m_type == "physical":
                disk_idx = m.get("disk_index")
                ok, msg = self.unmount_physical_disk(disk_idx, m_name)
                results.append((m_name, ok, msg))
            else:
                f_path = m.get("file_path")
                ok, msg = self.unmount_image_file(m_name, f_path)
                results.append((m_name, ok, msg))

        # Also run generic wsl --unmount to ensure any detached disks are released
        if is_admin():
            subprocess.run("wsl.exe --unmount", shell=True, capture_output=True)
        else:
            run_elevated_command("wsl.exe --unmount")

        return results

    def list_active_mounts(self) -> List[Dict[str, Any]]:
        """
        List active mounts by querying state and verifying WSL mount directory.
        """
        saved = load_saved_mounts()
        active = []
        for m in saved:
            m_name = m.get("mount_name")
            if self.check_mount_exists(m_name):
                m["status"] = "Active"
                active.append(m)
            else:
                # Mount is no longer active, prune it
                unregister_mount(m_name)
        return active

    def fix_permissions(
        self,
        mount_name: str,
        mode: str = "rw",
        restore_ro: bool = False
    ) -> Tuple[bool, str]:
        """
        Fix file and directory permissions in a mounted ext4 partition or image.
        - mode: "rw" sets a+rwX (0777 on dirs, 0666 on files), "r" sets a+rX.
        - restore_ro: if True, switches filesystem back to ro after applying permissions.
        Returns: (success: bool, message: str)
        """
        mount_path = f"/mnt/wsl/{mount_name}"
        if not self.check_mount_exists(mount_name):
            return False, f"挂载点不存在或未处于活动状态: {mount_path}"

        chmod_perm = "a+rwX" if mode == "rw" else "a+rX"
        restore_val = "1" if restore_ro else "0"

        bash_script = (
            f"mount_path='/mnt/wsl/{mount_name}'; "
            f"was_ro=0; "
            f"if mount | grep -E \"on $mount_path \" | grep -q \"ro,\"; then "
            f"  was_ro=1; "
            f"  mount -o remount,rw \"$mount_path\" || exit 1; "
            f"fi; "
            f"chmod -R {chmod_perm} \"$mount_path\"; "
            f"if [ \"{restore_val}\" = \"1\" ]; then "
            f"  mount -o remount,ro \"$mount_path\"; "
            f"fi"
        )
        cmd = ["wsl.exe", "-d", self.distro, "-u", "root", "--", "bash", "-c", bash_script]
        proc = subprocess.run(cmd, capture_output=True, text=True)

        if proc.returncode == 0 or "Bad message" in proc.stderr:
            if mode == "rw" and not restore_ro:
                mounts = load_saved_mounts()
                for m in mounts:
                    if m.get("mount_name") == mount_name:
                        m["read_only"] = False
                save_mounts(mounts)
            return True, f"权限修复成功！已赋予全部目录与文件 {chmod_perm} 访问权限。"
        else:
            return False, f"权限修复未完全完成 (代码: {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"

