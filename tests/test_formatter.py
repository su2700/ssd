import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.disk_detector import is_system_disk, get_physical_disks
from core.wsl_mounter import get_best_distro
from core.disk_formatter import (
    sanitize_label,
    get_wsl_block_devices,
    wait_for_new_device,
    format_physical_disk_full,
    format_physical_partition
)

class TestDiskFormatter(unittest.TestCase):
    def test_system_disk_protection(self):
        # Disk 0 must always be flagged as system disk
        self.assertTrue(is_system_disk(0), "Disk 0 must be identified as system disk")

        # Attempting to format Disk 0 must be immediately rejected by safety firewall
        ok, msg = format_physical_disk_full(0)
        self.assertFalse(ok)
        self.assertIn("系统", msg)

        ok_part, msg_part = format_physical_partition(0, 1)
        self.assertFalse(ok_part)
        self.assertIn("系统", msg_part)

    def test_sanitize_label(self):
        # Standard label
        self.assertEqual(sanitize_label("SSD_DATA"), "SSD_DATA")
        # Long label truncation to 16 chars
        self.assertEqual(sanitize_label("EXT4_VERY_LONG_LABEL_123456"), "EXT4_VERY_LONG_L")
        # Stripping invalid symbols
        self.assertEqual(sanitize_label("Disk-1#EVO*4TB!"), "Disk-1EVO4TB")
        # Empty string fallback
        self.assertEqual(sanitize_label(""), "EXT4_SSD")
        self.assertEqual(sanitize_label("   "), "EXT4_SSD")

    def test_wsl_block_devices(self):
        distro = get_best_distro()
        devices = get_wsl_block_devices(distro)
        self.assertIsInstance(devices, dict)
        self.assertTrue(len(devices) > 0, "WSL2 should have at least one block device")
        self.assertTrue(any(d.startswith("sd") for d in devices), "Devices should contain standard SCSI block devices")

    def test_wait_for_new_device_timeout(self):
        distro = get_best_distro()
        current = get_wsl_block_devices(distro)
        # Passing current devices as before_devices without attaching anything should time out quickly
        new_dev = wait_for_new_device(distro, current, timeout=1)
        self.assertIsNone(new_dev)

if __name__ == "__main__":
    unittest.main()
