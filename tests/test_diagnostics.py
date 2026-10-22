"""Recovery messages must preserve the failure and provide specific next steps."""

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from core.diagnostics import UserFacingError, explain_error, wsl_environment_error
from core.disk_detector import get_physical_disks, get_wsl_distros
from core.shell_utils import native_system_executable, run_powershell
import main


class TestRecoveryMessages(unittest.TestCase):
    def assert_actionable(self, message):
        for section in ('问题：', '原因：', '解决方法：'):
            self.assertIn(section, message)

    def test_missing_wsl_preserves_type_information_in_discovery(self):
        with patch('core.disk_detector.subprocess.run', side_effect=FileNotFoundError(2, 'not found')), self.assertLogs('ext4_mounter'):
            info = get_wsl_distros()
        message = wsl_environment_error(info)
        self.assert_actionable(message)
        self.assertIn('找不到 WSL', message)
        self.assertIn('wsl --install', message)
        self.assertIn('not found', message)

    def test_known_runtime_errors_have_specific_recovery(self):
        cases = [
            ('0x80370102', 'BIOS/UEFI'),
            ('0x8007019e', '适用于 Linux 的 Windows 子系统'),
            ('0x800701bc', 'wsl --update'),
            (PermissionError('denied'), 'UAC'),
            ('用户取消了管理员授权 (UAC)', '重新执行'),
            (subprocess.TimeoutExpired('wsl.exe', 10), '停止所有 WSL 会话'),
            ('bash: mkfs.ext4: command not found', 'e2fsprogs'),
        ]
        for error, fix in cases:
            with self.subTest(error=error):
                message = explain_error(error, log_path='example.log')
                self.assert_actionable(message)
                self.assertIn(fix, message)
                self.assertIn(str(error), message)
                self.assertIn('example.log', message)

    def test_no_distribution_is_distinct_from_wsl1(self):
        message = wsl_environment_error({'distros': []})
        self.assert_actionable(message)
        self.assertIn('wsl --install -d Ubuntu', message)
        message = wsl_environment_error({'distros': ['My Linux'], 'versions': {'My Linux': 1}})
        self.assert_actionable(message)
        self.assertIn("wsl --set-version 'My Linux' 2", message)

    def test_unknown_error_does_not_claim_a_specific_cause(self):
        message = explain_error(RuntimeError('unexpected exit 77'))
        self.assert_actionable(message)
        self.assertIn('尚未识别', message)
        self.assertIn('unexpected exit 77', message)

    def test_already_formatted_error_is_not_wrapped_twice(self):
        message = wsl_environment_error({'distros': []})
        self.assertEqual(explain_error(UserFacingError(message)), message)

    def test_disk_failure_is_reported_instead_of_no_disks(self):
        with patch('core.disk_detector.run_powershell', side_effect=FileNotFoundError('powershell.exe')), self.assertLogs('ext4_mounter'):
            with self.assertRaises(UserFacingError) as raised:
                get_physical_disks(strict=True)
        message = str(raised.exception)
        self.assert_actionable(message)
        self.assertIn('找不到 Windows PowerShell', message)
        self.assertIn('WindowsPowerShell', message)

    def test_query_error_and_successful_empty_inventory_are_distinct(self):
        for code in (0, 1):
            with self.subTest(code=code), patch('core.disk_detector.run_powershell', return_value=subprocess.CompletedProcess([], code, '', 'CIM unavailable')):
                if code:
                    with self.assertLogs('ext4_mounter'), self.assertRaises(UserFacingError) as raised:
                        get_physical_disks(strict=True)
                    self.assertIn('Get-CimInstance', str(raised.exception))
                else:
                    with self.assertLogs('ext4_mounter'):
                        self.assertEqual(get_physical_disks(strict=True), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows native startup dialog')
    def test_tk_failure_uses_native_dialog_with_repair_and_log(self):
        with patch('main.ctypes.windll.user32.MessageBoxW') as dialog:
            main.show_startup_error(ImportError('No module named _tkinter'), 'startup.log')
        message = dialog.call_args.args[1]
        self.assert_actionable(message)
        self.assertIn('Modify/Repair', message)
        self.assertIn('startup.log', message)

    def test_powershell_is_resolved_in_its_actual_system_directory(self):
        with patch('core.shell_utils.os.name', 'nt'), patch('core.shell_utils.os.path.isfile', side_effect=lambda p: 'Sysnative' in p and 'WindowsPowerShell' in p):
            path = native_system_executable('powershell.exe')
        self.assertIn('Sysnative', path)
        self.assertIn('WindowsPowerShell', path)

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell launcher')
    def test_missing_python_launcher_shows_fix_without_opening_a_dialog(self):
        launcher = str(Path(__file__).resolve().parents[1] / 'scripts' / 'launch.ps1').replace("'", "''")
        script = """
function Get-Command { param($Name, $ErrorAction) return $null }
function New-Object {
    param($ComObject)
    $obj = [pscustomobject]@{}
    $obj | Add-Member ScriptMethod Popup {
        param($message, $timeout, $title, $icon)
        [Console]::WriteLine('USER_DIALOG:' + $message)
        return 1
    }
    return $obj
}
& '%s'
""" % launcher
        proc = run_powershell(script, timeout=15)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('USER_DIALOG:', proc.stdout)
        self.assertIn('Cause:', proc.stdout)
        self.assertIn('Fix:', proc.stdout)
        self.assertIn('python.org', proc.stdout)


if __name__ == '__main__':
    unittest.main()
