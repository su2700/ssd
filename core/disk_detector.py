import ctypes
import json
import os
import re
import subprocess
from typing import Dict, List, Optional, Any

LINUX_PARTITION_GUIDS = {
    "{0fc63daf-8483-4772-8e79-3d69d8477de4}",  # Linux filesystem data
    "{b1171da1-b1c6-4688-9b24-212ca24a2f4f}",  # Linux filesystem data (alternate)
    "{44479540-f297-41b2-9af7-d133d58a964e}",  # Linux root (x86_64)
    "{69dad710-2ce4-4e3c-b16c-21a1d49abed3}",  # Linux root (ARM64)
    "{933ac4e1-2eb4-4f13-b844-0e14e2aef915}",  # Linux /home
    "{3b8f8425-20e0-4f3b-8146-f13452cb23ec}",  # Linux /srv
}

def is_admin() -> bool:
    """Check if the current process is running with Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def get_wsl_distros() -> Dict[str, Any]:
    """
    Get installed WSL distros and identify default distro.
    Returns:
        {
            "default": "Ubuntu",
            "distros": ["kali-linux", "Ubuntu"],
            "running": [...]
        }
    """
    result = {"default": None, "distros": [], "running": []}
    try:
        proc = subprocess.run(
            ["wsl.exe", "-l", "-v"],
            capture_output=True,
            text=False,
            timeout=10
        )
        output = ""
        for encoding in ("utf-16le", "utf-8", "gbk"):
            try:
                output = proc.stdout.decode(encoding)
                if "NAME" in output or "NAME" in output.replace(" ", ""):
                    break
            except Exception:
                continue

        lines = output.strip().splitlines()
        for line in lines[1:]:
            line_str = line.strip()
            if not line_str:
                continue
            is_def = line_str.startswith("*")
            cleaned = line_str.lstrip("*").strip()
            parts = [p for p in cleaned.split() if p]
            if parts:
                name = parts[0]
                state = parts[1] if len(parts) > 1 else "Unknown"
                result["distros"].append(name)
                if is_def:
                    result["default"] = name
                if state.lower() == "running":
                    result["running"].append(name)

        if not result["default"] and result["distros"]:
            if "Ubuntu" in result["distros"]:
                result["default"] = "Ubuntu"
            else:
                result["default"] = result["distros"][0]
    except Exception as e:
        result["error"] = str(e)
    return result

def get_physical_disks() -> List[Dict[str, Any]]:
    """
    Query physical disks using PowerShell Win32_DiskDrive.
    """
    ps_cmd = (
        "Get-CimInstance Win32_DiskDrive | "
        "Select-Object Index, Model, Size, MediaType, InterfaceType, DeviceID | "
        "ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=15
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []

        raw_data = json.loads(proc.stdout)
        if isinstance(raw_data, dict):
            raw_data = [raw_data]

        disks = []
        for item in raw_data:
            idx = item.get("Index")
            size_bytes = item.get("Size") or 0
            size_gb = round(size_bytes / (1024 ** 3), 2)
            disks.append({
                "index": idx,
                "model": (item.get("Model") or f"Disk {idx}").strip(),
                "size_bytes": size_bytes,
                "size_gb": size_gb,
                "media_type": item.get("MediaType") or "Fixed",
                "device_id": item.get("DeviceID") or f"\\\\.\\PHYSICALDRIVE{idx}"
            })
        disks.sort(key=lambda d: d["index"])
        return disks
    except Exception:
        return []

def get_disk_partitions(disk_index: int) -> List[Dict[str, Any]]:
    """
    Query partitions for a specific physical disk.
    """
    ps_cmd = (
        f"Get-Partition -DiskNumber {disk_index} | "
        "Select-Object DiskNumber, PartitionNumber, DriveLetter, Size, Type, Guid | "
        "ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=15
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []

        raw_data = json.loads(proc.stdout)
        if isinstance(raw_data, dict):
            raw_data = [raw_data]

        partitions = []
        for p in raw_data:
            p_num = p.get("PartitionNumber")
            size_bytes = p.get("Size") or 0
            size_gb = round(size_bytes / (1024 ** 3), 2)
            p_type = p.get("Type") or "Unknown"
            guid = (p.get("Guid") or "").lower()
            drive_letter = p.get("DriveLetter")

            # Check if this partition is likely Linux / ext4
            is_linux_candidate = False
            if guid in LINUX_PARTITION_GUIDS:
                is_linux_candidate = True
            elif not drive_letter and p_type.lower() in ("unknown", "basic data") and size_gb > 0.5:
                is_linux_candidate = True

            partitions.append({
                "disk_index": disk_index,
                "partition_number": p_num,
                "size_bytes": size_bytes,
                "size_gb": size_gb,
                "type": p_type,
                "guid": guid,
                "drive_letter": f"{drive_letter}:" if drive_letter else None,
                "is_linux_candidate": is_linux_candidate
            })
        partitions.sort(key=lambda x: x["partition_number"])
        return partitions
    except Exception:
        return []

def get_free_drive_letters() -> List[str]:
    """
    Get a list of unused Windows drive letters (from D: to Z:).
    """
    free_letters = []
    for code in range(ord('D'), ord('Z') + 1):
        letter = f"{chr(code)}:"
        if not os.path.exists(f"{letter}\\"):
            free_letters.append(letter)
    return free_letters
