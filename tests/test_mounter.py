import os
import subprocess
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.wsl_mounter import WslMounter, windows_to_wsl_path

class TestWslMounter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mounter = WslMounter()
        cls.test_img = os.path.join(BASE_DIR, "tests", "test_ext4.img")
        wsl_img_path = windows_to_wsl_path(cls.test_img)

        # Create a small 5MB ext4 image file
        create_script = (
            f"dd if=/dev/zero of='{wsl_img_path}' bs=1M count=5 && "
            f"mkfs.ext4 -F '{wsl_img_path}'"
        )
        proc = subprocess.run(
            ["wsl.exe", "-d", cls.mounter.distro, "-u", "root", "--", "bash", "-c", create_script],
            capture_output=True,
            text=True
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to create test image: {proc.stderr}")

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_img):
            try:
                os.remove(cls.test_img)
            except Exception:
                pass

    def test_image_mount_and_unmount(self):
        mount_name = "test_unit_ext4"

        # 1. Mount image
        success, unc_path, msg = self.mounter.mount_image_file(
            file_path=self.test_img,
            mount_name=mount_name,
            read_only=True
        )
        self.assertTrue(success, f"Mount failed: {msg}")
        self.assertTrue(os.path.exists(unc_path), f"UNC path does not exist: {unc_path}")

        # List files in mounted ext4 volume
        items = os.listdir(unc_path)
        self.assertIn("lost+found", items)

        # 2. Check active mounts
        active = self.mounter.list_active_mounts()
        self.assertTrue(any(m["mount_name"] == mount_name for m in active))

        # 3. Unmount image
        ok, unmount_msg = self.mounter.unmount_image_file(mount_name, self.test_img)
        self.assertTrue(ok, f"Unmount failed: {unmount_msg}")

        # 4. Verify unmounted
        active_after = self.mounter.list_active_mounts()
        self.assertFalse(any(m["mount_name"] == mount_name for m in active_after))

    def test_image_fix_permissions(self):
        mount_name = "test_unit_fix_perm"

        # 1. Mount image
        success, unc_path, msg = self.mounter.mount_image_file(
            file_path=self.test_img,
            mount_name=mount_name,
            read_only=True
        )
        self.assertTrue(success, f"Mount failed: {msg}")

        # 2. Fix permissions to full read-write
        ok, fix_msg = self.mounter.fix_permissions(mount_name, mode="rw", restore_ro=False)
        self.assertTrue(ok, f"Fix permissions failed: {fix_msg}")

        # 3. Clean up
        ok_unmount, _ = self.mounter.unmount_image_file(mount_name, self.test_img)
        self.assertTrue(ok_unmount)

if __name__ == "__main__":
    unittest.main()
