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

        try:
            # 2. Fix permissions to full 777 read-write
            ok, fix_msg = self.mounter.fix_permissions(mount_name, mode="rw", restore_ro=False)
            self.assertTrue(ok, f"Fix permissions failed: {fix_msg}")

            # 3. Create subfolder and new file inside WSL to verify permissions and ACL inheritance
            test_script = (
                f"mkdir -p /mnt/wsl/{mount_name}/sub_dir && "
                f"touch /mnt/wsl/{mount_name}/sub_dir/new_file.txt && "
                f"/usr/bin/stat -c '%a' /mnt/wsl/{mount_name} && "
                f"/usr/bin/stat -c '%a' /mnt/wsl/{mount_name}/sub_dir"
            )
            proc = subprocess.run(
                ["wsl.exe", "-d", self.mounter.distro, "-u", "root", "--", "bash", "-c", test_script],
                capture_output=True,
                text=True
            )
            self.assertEqual(proc.returncode, 0, f"test_script failed: {proc.stderr}")
            lines = proc.stdout.strip().splitlines()
            self.assertEqual(lines[0], "777", f"Root dir permission not 777: {lines}")
            self.assertEqual(lines[1], "777", f"Subdir permission not 777: {lines}")

            # 4. Test sweep_permissions
            ok_sweep = self.mounter.sweep_permissions(mount_name)
            self.assertTrue(ok_sweep)

            # Check new file is 777 after sweep
            stat_file = subprocess.run(
                ["wsl.exe", "-d", self.mounter.distro, "-u", "root", "--", "/usr/bin/stat", "-c", "%a", f"/mnt/wsl/{mount_name}/sub_dir/new_file.txt"],
                capture_output=True,
                text=True
            )
            self.assertEqual(stat_file.stdout.strip(), "777")
        finally:
            # 5. Clean up
            self.mounter.unmount_image_file(mount_name, self.test_img)

    def test_auto_chmod_777_on_rw_mount(self):
        mount_name = "test_unit_auto_777"

        # Mount image in RW mode with auto_chmod_777=True
        success, unc_path, msg = self.mounter.mount_image_file(
            file_path=self.test_img,
            mount_name=mount_name,
            read_only=False,
            auto_chmod_777=True
        )
        self.assertTrue(success, f"Mount failed: {msg}")

        try:
            # Verify permissions are 777
            stat_proc = subprocess.run(
                ["wsl.exe", "-d", self.mounter.distro, "-u", "root", "--", "/usr/bin/stat", "-c", "%a", f"/mnt/wsl/{mount_name}"],
                capture_output=True,
                text=True
            )
            self.assertEqual(stat_proc.stdout.strip(), "777")
        finally:
            # Clean up
            self.mounter.unmount_image_file(mount_name, self.test_img)

    def test_fix_rosbag_permissions(self):
        mount_name = "test_unit_rosbag_fix"

        # Mount image in read-only mode with auto_chmod_777=True (the app default)
        success, unc_path, msg = self.mounter.mount_image_file(
            file_path=self.test_img,
            mount_name=mount_name,
            read_only=True,
            auto_chmod_777=True
        )
        self.assertTrue(success, f"Mount failed: {msg}")

        try:
            # 1. Remount RW temporarily in WSL to inject 0700/0600 rosbag/mcap directory structure
            setup_script = (
                f"mount -o remount,rw /mnt/wsl/{mount_name} && "
                f"mkdir -p /mnt/wsl/{mount_name}/mcap/rosbag2_test && "
                f"echo 'mcap_header' > /mnt/wsl/{mount_name}/mcap/rosbag2_test/recording.mcap && "
                f"chmod 700 /mnt/wsl/{mount_name}/mcap && "
                f"chmod 700 /mnt/wsl/{mount_name}/mcap/rosbag2_test && "
                f"chmod 600 /mnt/wsl/{mount_name}/mcap/rosbag2_test/recording.mcap && "
                f"mount -o remount,ro /mnt/wsl/{mount_name}"
            )
            proc = subprocess.run(
                ["wsl.exe", "-d", self.mounter.distro, "-u", "root", "--", "bash", "-c", setup_script],
                capture_output=True,
                text=True
            )
            self.assertEqual(proc.returncode, 0, f"setup_script failed: {proc.stderr}")

            # 2. Test detect_rosbag_dirs
            detected = self.mounter.detect_rosbag_dirs(mount_name)
            self.assertTrue(any("mcap" in d for d in detected), f"mcap not detected in {detected}")

            # 3. Call fix_rosbag_permissions
            ok, fix_msg = self.mounter.fix_rosbag_permissions(mount_name)
            self.assertTrue(ok, f"fix_rosbag_permissions failed: {fix_msg}")

            # 4. Verify that permissions allow traversal and reading from Windows
            test_file_win = os.path.join(unc_path, "mcap", "rosbag2_test", "recording.mcap")
            self.assertTrue(os.path.exists(test_file_win), f"File {test_file_win} not accessible from Windows")
            with open(test_file_win, "r", encoding="utf-8") as f:
                content = f.read().strip()
            self.assertEqual(content, "mcap_header")

        finally:
            self.mounter.unmount_image_file(mount_name, self.test_img)

if __name__ == "__main__":
    unittest.main()
