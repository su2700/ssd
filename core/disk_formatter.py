import os
import re
import subprocess
import time
from typing import Dict, List, Optional, Tuple, Any

from .disk_detector import is_admin, is_system_disk, get_disk_partitions
from .wsl_mounter import WslMounter, get_best_distro, run_elevated_command

def sanitize_label(label: str) -> str:
    """
    Sanitize volume label for ext4 filesystem.
    ext4 labels can be up to 16 bytes. Only alphanumeric, hyphen and underscore allowed.
    """
    clean = re.sub(r"[^a-zA-Z0-9_\-]", "", (label or "").strip())
    if not clean:
        clean = "EXT4_SSD"
    return clean[:16]

def get_wsl_block_devices(distro: str) -> Dict[str, Dict[str, Any]]:
    """
    Query current block devices inside WSL2 using lsblk.
    Returns a dict mapping device name (e.g. 'sda') to info.
    """
    cmd = ["wsl.exe", "-d", distro, "-u", "root", "--", "lsblk", "-d", "-n", "-b", "-o", "NAME,SIZE,TYPE"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        devices = {}
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    name = parts[0].strip()
                    try:
                        size_bytes = int(parts[1].strip())
                    except ValueError:
                        size_bytes = 0
                    dev_type = parts[2].strip()
                    devices[name] = {"name": name, "size_bytes": size_bytes, "type": dev_type}
        return devices
    except Exception:
        return {}

def wait_for_new_device(distro: str, before_devices: Dict[str, Any], timeout: int = 15) -> Optional[str]:
    """
    Poll WSL2 for a newly attached disk block device.
    Returns device name, e.g. 'sde'.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        current_devices = get_wsl_block_devices(distro)
        new_devs = set(current_devices.keys()) - set(before_devices.keys())
        for dev in new_devs:
            if current_devices[dev]["type"] == "disk":
                return dev
        time.sleep(0.5)
    return None

def get_device_partitions(distro: str, dev_name: str) -> List[str]:
    """
    Returns list of partition device names under dev_name, e.g. ['sde1'].
    """
    cmd = ["wsl.exe", "-d", distro, "-u", "root", "--", "lsblk", "-n", "-o", "NAME,TYPE", f"/dev/{dev_name}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        parts = []
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                parts_tokens = line.split()
                if len(parts_tokens) >= 2 and parts_tokens[1].strip() == "part":
                    p_name = parts_tokens[0].strip()
                    p_name = re.sub(r"[^a-zA-Z0-9]", "", p_name)
                    parts.append(p_name)
        return parts
    except Exception:
        return []

def initialize_disk_gpt_with_partition(disk_index: int) -> Tuple[bool, str]:
    """
    Initialize a physical disk as GPT and create 1 single partition spanning the whole disk
    with Linux filesystem data GUID: {0fc63daf-8483-4772-8e79-3d69d8477de4}.
    """
    if is_system_disk(disk_index):
        return False, f"安全阻断：磁盘 {disk_index} 为系统主盘，严禁执行初始化！"

    ps_script = (
        f"$d = Get-Disk -Number {disk_index}; "
        f"if ($d.PartitionStyle -ne 'RAW') {{ Clear-Disk -Number {disk_index} -RemoveData -RemoveOEM -Confirm:$false }}; "
        f"Initialize-Disk -Number {disk_index} -PartitionStyle GPT; "
        f"$part = New-Partition -DiskNumber {disk_index} -UseMaximumSize -GptType '{{0fc63daf-8483-4772-8e79-3d69d8477de4}}'; "
        f"if ($part) {{ 'SUCCESS' }} else {{ 'FAILED' }}"
    )
    cmd = f"powershell.exe -NoProfile -Command \"{ps_script}\""
    if is_admin():
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        out = (proc.stdout + " " + proc.stderr).strip()
        if proc.returncode == 0 and "SUCCESS" in out:
            return True, "磁盘 GPT 初始化与 Linux 分区创建成功"
        return False, f"PowerShell 初始化失败: {out}"
    else:
        code, out = run_elevated_command(cmd)
        if code == 0 and "SUCCESS" in out:
            return True, "磁盘 GPT 初始化与 Linux 分区创建成功"
        return False, f"提权初始化失败: {out}"

def mount_bare_disk(disk_index: int) -> Tuple[bool, str]:
    """
    Attach physical disk to WSL2 without mounting a filesystem (--bare).
    """
    device_path = f"\\\\.\\PHYSICALDRIVE{disk_index}"
    mount_cmd = f"wsl.exe --mount {device_path} --bare"
    if is_admin():
        proc = subprocess.run(mount_cmd, shell=True, capture_output=True, text=True)
        code = proc.returncode
        out = (proc.stdout + " " + proc.stderr).strip()
    else:
        code, out = run_elevated_command(mount_cmd)
    if code == 0:
        return True, "裸设备成功附加至 WSL2"
    return False, f"附加裸设备至 WSL2 失败 (代码 {code}): {out}"

def unmount_bare_disk(disk_index: int) -> Tuple[bool, str]:
    """
    Detach physical disk from WSL2.
    """
    device_path = f"\\\\.\\PHYSICALDRIVE{disk_index}"
    unmount_cmd = f"wsl.exe --unmount {device_path}"
    if is_admin():
        proc = subprocess.run(unmount_cmd, shell=True, capture_output=True, text=True)
        code = proc.returncode
        out = (proc.stdout + " " + proc.stderr).strip()
    else:
        code, out = run_elevated_command(unmount_cmd)
    if code == 0:
        return True, f"设备 {device_path} 已从 WSL2 释放"
    return False, f"释放设备返回 (代码 {code}): {out}"

def format_physical_disk_full(
    disk_index: int,
    label: str = "EXT4_SSD",
    distro: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Full-disk reinitialization and formatting:
    1. Security check: prohibit system disk
    2. Unmount if currently mounted
    3. Windows initialize as GPT + create maximum partition (Linux GUID)
    4. Attach to WSL2 bare
    5. Identify newly attached block device in WSL2
    6. Run mkfs.ext4 -F -O 64bit -m 1 -E nodiscard -L {label}
    7. Unmount bare disk
    """
    if is_system_disk(disk_index):
        return False, f"安全阻断：磁盘 {disk_index} 包含 Windows 系统或引导文件，严禁格式化！"

    distro = get_best_distro(distro)
    clean_label = sanitize_label(label)

    # 1. Unmount any active WSL mounts for this disk
    mounter = WslMounter(preferred_distro=distro)
    mounter.unmount_physical_disk(disk_index)

    # 2. Windows initialize GPT + partition
    ok_init, msg_init = initialize_disk_gpt_with_partition(disk_index)
    if not ok_init:
        return False, f"磁盘分区初始化失败: {msg_init}"

    # Small delay to let Windows flush partition table
    time.sleep(1.0)

    # 3. Snapshot block devices before attaching
    devs_before = get_wsl_block_devices(distro)

    # 4. Attach bare disk
    ok_mount, msg_mount = mount_bare_disk(disk_index)
    if not ok_mount:
        return False, f"WSL2 挂载失败: {msg_mount}"

    try:
        # 5. Find the new block device
        dev_name = wait_for_new_device(distro, devs_before, timeout=15)
        if not dev_name:
            return False, "未能识别 WSL2 中的新磁盘设备节点，请检查 WSL 运行状态。"

        time.sleep(1.0)
        parts = get_device_partitions(distro, dev_name)
        if parts:
            target_dev = f"/dev/{parts[0]}"
        else:
            test_cmd = ["wsl.exe", "-d", distro, "-u", "root", "--", "test", "-b", f"/dev/{dev_name}1"]
            if subprocess.run(test_cmd).returncode == 0:
                target_dev = f"/dev/{dev_name}1"
            else:
                target_dev = f"/dev/{dev_name}"

        # 6. Format with mkfs.ext4
        # -F: force
        # -O 64bit: support 64-bit block numbers (> 2TB support)
        # -m 1: reserve 1% superuser space (recovers ~160GB on 4TB SSD)
        # -E nodiscard: instant format without discard delays in virtual SCSI
        # -L: volume label
        format_cmd = (
            f"mkfs.ext4 -F -O 64bit -m 1 -E nodiscard -L '{clean_label}' {target_dev}"
        )
        proc = subprocess.run(
            ["wsl.exe", "-d", distro, "-u", "root", "--", "bash", "-c", format_cmd],
            capture_output=True,
            text=True,
            timeout=120
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip()
            return False, f"mkfs.ext4 格式化执行失败 (代码 {proc.returncode}): {err}"

        return True, f"SSD 整盘初始化并格式化为 ext4 成功！(卷标: {clean_label}, 设备: {target_dev})"

    finally:
        # 7. Always detach bare disk
        unmount_bare_disk(disk_index)

def format_physical_partition(
    disk_index: int,
    partition_number: int,
    label: str = "EXT4_SSD",
    distro: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Format a specific existing partition on an SSD to ext4 without repartitioning.
    """
    if is_system_disk(disk_index):
        return False, f"安全阻断：磁盘 {disk_index} 包含 Windows 系统或引导文件，严禁格式化！"

    distro = get_best_distro(distro)
    clean_label = sanitize_label(label)

    # 1. Unmount if currently mounted
    mounter = WslMounter(preferred_distro=distro)
    mounter.unmount_physical_disk(disk_index)

    # 2. Snapshot block devices before attaching
    devs_before = get_wsl_block_devices(distro)

    # 3. Attach bare disk
    ok_mount, msg_mount = mount_bare_disk(disk_index)
    if not ok_mount:
        return False, f"WSL2 挂载失败: {msg_mount}"

    try:
        # 4. Find the new block device
        dev_name = wait_for_new_device(distro, devs_before, timeout=15)
        if not dev_name:
            return False, "未能识别 WSL2 中的新磁盘设备节点，请检查 WSL 运行状态。"

        target_dev = f"/dev/{dev_name}{partition_number}"
        # Verify block device exists
        test_cmd = ["wsl.exe", "-d", distro, "-u", "root", "--", "test", "-b", target_dev]
        if subprocess.run(test_cmd).returncode != 0:
            return False, f"未在 WSL2 中找到分区设备 {target_dev}"

        # 5. Format with mkfs.ext4
        format_cmd = (
            f"mkfs.ext4 -F -O 64bit -m 1 -E nodiscard -L '{clean_label}' {target_dev}"
        )
        proc = subprocess.run(
            ["wsl.exe", "-d", distro, "-u", "root", "--", "bash", "-c", format_cmd],
            capture_output=True,
            text=True,
            timeout=120
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip()
            return False, f"mkfs.ext4 格式化执行失败 (代码 {proc.returncode}): {err}"

        # Update partition GUID to Linux data in Windows if GPT
        try:
            ps_set = (
                f"Set-Partition -DiskNumber {disk_index} -PartitionNumber {partition_number} "
                f"-GptType '{{0fc63daf-8483-4772-8e79-3d69d8477de4}}' -ErrorAction SilentlyContinue"
            )
            if is_admin():
                subprocess.run(f"powershell.exe -NoProfile -Command \"{ps_set}\"", shell=True, capture_output=True)
            else:
                run_elevated_command(f"powershell.exe -NoProfile -Command \"{ps_set}\"")
        except Exception:
            pass

        return True, f"分区 #{partition_number} 成功格式化为 ext4！(卷标: {clean_label})"

    finally:
        # Always unmount bare disk
        unmount_bare_disk(disk_index)
