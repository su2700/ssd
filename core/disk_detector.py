import ctypes
import json
import logging
import os
import re
import subprocess

from typing import Dict, List, Optional, Any

from .shell_utils import decode_output, run_powershell, native_system_executable
from .diagnostics import UserFacingError, explain_error
logger = logging.getLogger("ext4_mounter.detector")

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
    result = {"default": None, "distros": [], "running": [], "versions": {}}
    try:
        proc = subprocess.run(
            [native_system_executable("wsl.exe"), "-l", "-v"],
            capture_output=True,
            text=False,
            timeout=10
        )
        if proc.returncode != 0:
            result["error"] = decode_output(proc.stderr or proc.stdout, wsl_management=True).strip()
            if not result["error"]:
                result["error"] = f"WSL exited with code {proc.returncode}"
            logger.warning("WSL discovery failed: %s", result["error"])
            return result
        output = decode_output(proc.stdout)
        # Ignore translated column headings and states; parse only the name and
        # final WSL version column, whose format does not depend on UI language.
        for line in output.splitlines():
            match = re.match(r"^\s*(\*)?\s*(.+?)\s{2,}.*?\s+([12])\s*$", line)
            if not match:
                continue
            name = match.group(2).strip()
            result["distros"].append(name)
            result["versions"][name] = int(match.group(3))
            if match.group(1):
                result["default"] = name
        running = subprocess.run(
            [native_system_executable("wsl.exe"), "--list", "--running", "--quiet"],
            capture_output=True, timeout=10
        )
        if running.returncode == 0:
            names = decode_output(running.stdout).strip().splitlines()
            result["running"] = [n.strip() for n in names if n.strip() in result["distros"]]

        if not result["default"] and result["distros"]:
            if "Ubuntu" in result["distros"]:
                result["default"] = "Ubuntu"
            else:
                result["default"] = result["distros"][0]
    except Exception as e:
        logger.exception("WSL discovery failed")
        result["error"] = str(e)
        result["diagnostic"] = explain_error(e, context="wsl")
    return result

def is_system_disk(disk_index: int) -> bool:
    """
    Check if the specified disk is a system or boot disk (e.g. contains C:).
    Such disks MUST never be cleared or formatted.
    """
    if disk_index == 0:
        return True
    try:
        ps_cmd = f"Get-Disk -Number {disk_index} | Select-Object IsBoot, IsSystem | ConvertTo-Json -Compress"
        proc = run_powershell(
            ps_cmd,
            timeout=10
        )
        if proc.returncode == 0 and proc.stdout.strip():
            info = json.loads(proc.stdout)
            if info.get("IsBoot") or info.get("IsSystem"):
                return True

        parts = get_disk_partitions(disk_index)
        for p in parts:
            if p.get("drive_letter") == "C:":
                return True
            if str(p.get("type", "")).lower() in ("system", "boot", "recovery"):
                return True
    except Exception:
        return True
    return False

def get_physical_disks(strict: bool = False) -> List[Dict[str, Any]]:
    """
    Query physical disks using PowerShell Get-Disk with Win32_DiskDrive fallback.
    Returns details including index, model, size, partition_style, is_system.
    """
    # Prefer Get-Disk for partition style and boot/system flags
    ps_cmd = (
        "Get-Disk | "
        "Select-Object Number, FriendlyName, Size, PartitionStyle, IsBoot, IsSystem, BusType | "
        "ConvertTo-Json -Compress"
    )
    try:
        proc = run_powershell(
            ps_cmd,
            timeout=15
        )
        if proc.returncode == 0 and proc.stdout.strip():
            raw_data = json.loads(proc.stdout)
            if isinstance(raw_data, dict):
                raw_data = [raw_data]

            disks = []
            for item in raw_data:
                idx = item.get("Number")
                size_bytes = int(item.get("Size") or 0)
                size_gb = round(size_bytes / (1024 ** 3), 2)
                is_boot = bool(item.get("IsBoot"))
                is_sys = bool(item.get("IsSystem"))
                is_system = is_boot or is_sys or (idx == 0)
                style = item.get("PartitionStyle")
                # Windows PowerShell 5.1 may serialize CIM enums as integers.
                part_style = {0: "RAW", 1: "MBR", 2: "GPT"}.get(style, str(style or "RAW").upper())
                bus_type = item.get("BusType") or "Fixed"

                disks.append({
                    "index": idx,
                    "model": (item.get("FriendlyName") or f"Disk {idx}").strip(),
                    "size_bytes": size_bytes,
                    "size_gb": size_gb,
                    "media_type": bus_type,
                    "device_id": f"\\\\.\\PHYSICALDRIVE{idx}",
                    "partition_style": part_style,
                    "is_system": is_system
                })
            disks.sort(key=lambda d: d["index"])
            return disks
        logger.warning("Get-Disk failed: %s", proc.stderr)
    except Exception:
        logger.exception("Get-Disk failed; trying CIM")

    # Fallback to Win32_DiskDrive
    ps_cmd_fallback = (
        "Get-CimInstance Win32_DiskDrive | "
        "Select-Object Index, Model, Size, MediaType, InterfaceType, DeviceID | "
        "ConvertTo-Json -Compress"
    )
    try:
        proc = run_powershell(
            ps_cmd_fallback,
            timeout=15
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"CIM exit code {proc.returncode}")
        if not proc.stdout.strip():
            return []

        raw_data = json.loads(proc.stdout)
        if isinstance(raw_data, dict):
            raw_data = [raw_data]

        disks = []
        for item in raw_data:
            idx = item.get("Index")
            size_bytes = int(item.get("Size") or 0)
            size_gb = round(size_bytes / (1024 ** 3), 2)
            disks.append({
                "index": idx,
                "model": (item.get("Model") or f"Disk {idx}").strip(),
                "size_bytes": size_bytes,
                "size_gb": size_gb,
                "media_type": item.get("MediaType") or "Fixed",
                "device_id": item.get("DeviceID") or f"\\\\.\\PHYSICALDRIVE{idx}",
                "partition_style": "UNKNOWN",
                "is_system": (idx == 0)
            })
        disks.sort(key=lambda d: d["index"])
        return disks
    except Exception as error:
        logger.exception("CIM disk query failed")
        if strict:
            raise UserFacingError(explain_error(error, context="disk")) from error
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
        proc = run_powershell(
            ps_cmd,
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
        logger.exception("Partition query failed for disk %s", disk_index)
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
