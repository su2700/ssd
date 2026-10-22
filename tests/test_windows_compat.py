"""Windows 10/11 compatibility matrix; no real WSL or disk operations."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from core.disk_detector import get_physical_disks
from core.disk_formatter import format_physical_disk_full, format_physical_partition
from core.shell_utils import native_system_executable, run_text
from core.windows_compat import get_windows_support, get_wsl_capabilities, mount_support_error, get_mount_support_error
from core.wsl_mounter import get_best_distro, WslMounter


MODERN = {'--mount', '--unmount', '--bare', '--partition', '--type', '--name', '--vhd'}


class TestWindowsCompatibility(unittest.TestCase):
    def test_windows_build_matrix(self):
        for build, supported, name in ((18363, False, 'Windows 10'), (19041, True, 'Windows 10'),
                                       (19045, True, 'Windows 10'), (22000, True, 'Windows 11'),
                                       (26100, True, 'Windows 11')):
            with self.subTest(build=build), patch('core.windows_compat.os.name', 'nt'), patch(
                'core.windows_compat.sys.getwindowsversion', return_value=SimpleNamespace(major=10, build=build), create=True
            ):
                info = get_windows_support()
            self.assertEqual(info['supported'], supported)
            self.assertEqual(info['name'], name)

    def test_localized_capability_detection(self):
        for encoding in ('utf-8', 'utf-16le'):
            help_text = '参数说明:\n' + '\n'.join(MODERN)
            proc = subprocess.CompletedProcess([], 0, help_text.encode(encoding), b'')
            with self.subTest(encoding=encoding), patch('core.shell_utils.subprocess.run', return_value=proc):
                capabilities = get_wsl_capabilities()
            self.assertEqual(capabilities['options'], MODERN)
            self.assertEqual(mount_support_error(capabilities, vhd=True), '')

    def test_inbox_wsl_requires_update_for_named_mounts(self):
        capabilities = {'options': MODERN - {'--name', '--vhd'}}
        self.assertIn('--name', mount_support_error(capabilities))
        self.assertEqual(mount_support_error(capabilities, named=False), '')
        self.assertIn('--vhd', mount_support_error(capabilities, vhd=True))

    def test_wsl1_is_not_selected_over_wsl2(self):
        info = {'default': 'Ubuntu', 'distros': ['Ubuntu', 'Debian'],
                'versions': {'Ubuntu': 1, 'Debian': 2}}
        with patch('core.wsl_mounter.get_wsl_distros', return_value=info):
            self.assertEqual(get_best_distro('Ubuntu'), 'Debian')
        with patch('core.windows_compat.get_windows_support', return_value={'supported': True}), patch(
            'core.disk_detector.get_wsl_distros', return_value=info
        ), patch('core.windows_compat.get_wsl_capabilities') as help_probe:
            self.assertIn('--set-version', get_mount_support_error(distro='Ubuntu'))
            help_probe.assert_not_called()

    def test_native_tools_bypass_wow64(self):
        with patch('core.shell_utils.os.name', 'nt'), patch.dict('os.environ', {'SystemRoot': r'C:\Windows'}), patch(
            'core.shell_utils.os.path.isfile', side_effect=lambda path: 'Sysnative' in path
        ):
            self.assertIn('Sysnative', native_system_executable('wsl.exe'))
            for command in (['wsl.exe', '--status'], 'wsl.exe --status'):
                with patch('core.shell_utils.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as run:
                    run_text(command, capture_output=True)
                self.assertIn('Sysnative', str(run.call_args.args[0]))

    def test_explorer_share_works_without_wsl_localhost_alias(self):
        mounter = WslMounter(discover=False)
        self.assertEqual(mounter.get_unc_path('data'), r'\\wsl$\Ubuntu\mnt\wsl\data')
        saved = [{'mount_name': 'data', 'unc_path': r'\\wsl.localhost\Ubuntu\mnt\wsl\data'}]
        with patch('core.wsl_mounter.load_saved_mounts', return_value=saved), patch.object(mounter, 'check_mount_exists', return_value=True):
            self.assertEqual(mounter.list_active_mounts()[0]['unc_path'], mounter.get_unc_path('data'))

    def test_numeric_storage_enum_does_not_force_cim_fallback(self):
        disk = {'Number': 1, 'FriendlyName': 'SSD', 'Size': 1024, 'PartitionStyle': 2}
        with patch('core.disk_detector.run_powershell', return_value=subprocess.CompletedProcess([], 0, json.dumps(disk), '')) as query:
            disks = get_physical_disks()
        self.assertEqual(disks[0]['partition_style'], 'GPT')
        self.assertEqual(query.call_count, 1)

    def test_cim_string_disk_size(self):
        replies = [subprocess.CompletedProcess([], 1, '', 'Get-Disk unavailable'),
                   subprocess.CompletedProcess([], 0, json.dumps({'Index': 1, 'Size': '1073741824'}), '')]
        with patch('core.disk_detector.run_powershell', side_effect=replies), self.assertLogs('ext4_mounter'):
            self.assertEqual(get_physical_disks()[0]['size_gb'], 1)

    def test_unsupported_mount_cannot_elevate_or_modify_disk(self):
        with patch('core.wsl_mounter.get_mount_support_error', return_value='Update WSL'), patch(
            'core.wsl_mounter.run_elevated_command'
        ) as elevate:
            self.assertEqual(WslMounter(discover=False).mount_physical_disk(1, 1, 'data'), (False, '', 'Update WSL'))
            elevate.assert_not_called()
        with patch('core.disk_formatter.is_system_disk', return_value=False), patch(
            'core.disk_formatter.get_best_distro', return_value='Ubuntu'
        ), patch('core.disk_formatter.get_mount_support_error', return_value='Update WSL'), patch(
            'core.disk_formatter.initialize_disk_gpt_with_partition'
        ) as initialize, patch('core.disk_formatter.WslMounter') as mounter:
            self.assertEqual(format_physical_disk_full(1), (False, 'Update WSL'))
            self.assertEqual(format_physical_partition(1, 1), (False, 'Update WSL'))
            initialize.assert_not_called()
            mounter.assert_not_called()

    def test_packaged_manifest(self):
        root = Path(__file__).resolve().parents[1]
        manifest = ET.parse(root / 'scripts' / 'app.manifest')
        self.assertIsNotNone(manifest.find('.//{urn:schemas-microsoft-com:compatibility.v1}supportedOS'))
        privilege = manifest.find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
        self.assertEqual(privilege.get('level'), 'asInvoker')
        self.assertIn('--manifest "scripts\\app.manifest"', (root / 'scripts' / 'build_exe.bat').read_text())


if __name__ == '__main__':
    unittest.main()
