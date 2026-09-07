import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.disk_detector import (
    get_wsl_distros,
    get_physical_disks,
    get_disk_partitions,
    get_free_drive_letters
)
from core.wsl_mounter import windows_to_wsl_path, get_best_distro

class TestDiskDetector(unittest.TestCase):
    def test_wsl_distros(self):
        info = get_wsl_distros()
        self.assertIsInstance(info, dict)
        self.assertIn("distros", info)
        self.assertTrue(len(info["distros"]) > 0, "At least one WSL distro should be detected")
        self.assertTrue(any("ubuntu" in d.lower() or "kali" in d.lower() for d in info["distros"]))

    def test_best_distro(self):
        distro = get_best_distro()
        self.assertIsNotNone(distro)
        self.assertIn(distro.lower(), ["ubuntu", "kali-linux"])

    def test_windows_to_wsl_path(self):
        win_path = r"C:\Users\test\image.img"
        wsl_path = windows_to_wsl_path(win_path)
        self.assertEqual(wsl_path, "/mnt/c/Users/test/image.img")

    def test_get_physical_disks(self):
        disks = get_physical_disks()
        self.assertIsInstance(disks, list)
        self.assertTrue(len(disks) >= 1, "At least Disk 0 should exist")
        # Check attributes
        disk0 = disks[0]
        self.assertIn("index", disk0)
        self.assertIn("model", disk0)
        self.assertIn("size_gb", disk0)

    def test_free_drive_letters(self):
        letters = get_free_drive_letters()
        self.assertIsInstance(letters, list)
        self.assertTrue(len(letters) > 0)
        for l in letters:
            self.assertTrue(l.endswith(":"))

if __name__ == "__main__":
    unittest.main()
