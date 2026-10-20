"""Locale regressions; no disk writes, mounts, UAC or desktop changes."""

import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from core.disk_detector import get_physical_disks, get_wsl_distros
from core.shell_utils import decode_output, powershell_command, run_powershell, run_text
from core.wsl_mounter import run_elevated_command

ROOT = Path(__file__).resolve().parents[1]


class TestShellEncoding(unittest.TestCase):
    def test_output_encodings(self):
        message = "磁盘挂载失败：拒绝访问"
        with patch('core.shell_utils.locale.getpreferredencoding', return_value='cp936'):
            for encoding in ('utf-8', 'utf-8-sig', 'utf-16', 'utf-16le', 'gbk'):
                with self.subTest(encoding=encoding):
                    self.assertEqual(decode_output(message.encode(encoding), wsl_management=encoding == 'utf-16le'), message)
        self.assertEqual(decode_output(b''), '')

    def test_text_capture_decodes_stdout_and_stderr(self):
        proc = subprocess.CompletedProcess([], 1, '中文'.encode('utf-8'), '错误'.encode('utf-16le'))
        with patch('core.shell_utils.subprocess.run', return_value=proc) as run:
            result = run_text(['wsl.exe'], capture_output=True, text=True)
        self.assertEqual((result.stdout, result.stderr, result.returncode), ('中文', '错误', 1))
        self.assertNotIn('text', run.call_args.kwargs)

    def test_encoded_command_preserves_chinese_paths(self):
        script = "Write-Output 'C:\\用户\\测试 文件.img'"
        command = powershell_command(script)
        decoded = base64.b64decode(command[-1]).decode('utf-16le')
        self.assertTrue(decoded.endswith(script))
        self.assertIn('OutputEncoding', decoded)
        self.assertTrue(command[-1].isascii())

    def test_wsl_localized_tables(self):
        for header, running, stopped in (
            ('名称 状态 版本', '正在运行', '已停止'),
            ('名稱 狀態 版本', '執行中', '已停止'),
            ('NAME STATE VERSION', 'Running', 'Stopped'),
        ):
            for encoding in ('utf-16le', 'utf-8', 'gbk'):
                with self.subTest(header=header, encoding=encoding):
                    table = f'  {header}\r\n* Ubuntu          {running}       2\r\n  Debian          {stopped}       2\r\n'
                    replies = [
                        subprocess.CompletedProcess([], 0, table.encode(encoding), b''),
                        subprocess.CompletedProcess([], 0, 'Ubuntu\r\n'.encode(encoding), b''),
                    ]
                    with patch('core.disk_detector.subprocess.run', side_effect=replies), patch(
                        'core.shell_utils.locale.getpreferredencoding', return_value='cp936'
                    ):
                        info = get_wsl_distros()
                    self.assertEqual(info, {'default': 'Ubuntu', 'distros': ['Ubuntu', 'Debian'], 'running': ['Ubuntu']})

    def test_wsl_failure_is_not_a_distro(self):
        error = '没有已安装的分发版'
        proc = subprocess.CompletedProcess([], 1, error.encode('utf-16le'), b'')
        with patch('core.disk_detector.subprocess.run', return_value=proc):
            info = get_wsl_distros()
        self.assertEqual(info['distros'], [])
        self.assertEqual(info['error'], error)

    def test_chinese_disk_model_json(self):
        output = json.dumps({'Number': 1, 'FriendlyName': '移动硬盘', 'Size': 1024,
                             'PartitionStyle': 'GPT'}, ensure_ascii=False).encode('utf-8')
        with patch('core.shell_utils.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output, b'')):
            self.assertEqual(get_physical_disks()[0]['model'], '移动硬盘')

    def test_batch_files_are_ascii_crlf(self):
        for path in ROOT.rglob('*.bat'):
            data = path.read_bytes()
            data.decode('ascii')
            self.assertNotIn(b'\n', data.replace(b'\r\n', b''), str(path))
            self.assertNotIn(b'\r\r\n', data, str(path))

    def test_elevated_batch_encoding_and_log_decoding(self):
        with tempfile.TemporaryDirectory(prefix="ext4 中文 O'Brien ") as folder:
            def simulate_elevation(script, **kwargs):
                batch = next(Path(folder).glob('*.bat')).read_bytes()
                self.assertNotIn(b'\r\r\n', batch)
                self.assertIn(b'\r\n', batch)
                self.assertIn("O''Brien", script)
                text = batch.decode('utf-8')
                stdout, stderr = re.search(r'> "([^"]+)" 2> "([^"]+)"', text).groups()
                code = re.search(r'echo %ERRORLEVEL% > "([^"]+)"', text).group(1)
                Path(stdout).write_bytes('挂载完成\r\n'.encode('utf-16le'))
                Path(stderr).write_bytes(b'')
                Path(code).write_bytes(b'0\r\n')
                return subprocess.CompletedProcess([], 0, '', '')
            with patch('core.wsl_mounter.tempfile.gettempdir', return_value=folder), patch(
                'core.wsl_mounter.run_powershell', side_effect=simulate_elevation
            ):
                self.assertEqual(run_elevated_command('wsl.exe --status'), (0, '挂载完成'))
            self.assertEqual(list(Path(folder).iterdir()), [])


@unittest.skipUnless(os.name == 'nt', 'Windows shell integration')
class TestWindowsShells(unittest.TestCase):
    def test_launcher_forwards_chinese_project_path(self):
        with tempfile.TemporaryDirectory(prefix="ext4 中文 & O'Brien ") as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            launch = root / 'scripts' / 'launch.ps1'
            shutil.copyfile(ROOT / 'scripts' / 'launch.ps1', launch)
            # Intercept process creation while exercising the actual launcher.
            script = '''function Start-Process {
                param($FilePath, $WorkingDirectory, $ArgumentList)
                @{FilePath=$FilePath; WorkingDirectory=$WorkingDirectory; Arguments=$ArgumentList} | ConvertTo-Json -Compress
            }; . '%s' ''' % str(launch).replace("'", "''")
            proc = run_powershell(script)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result['WorkingDirectory'], folder)
            self.assertEqual(result['Arguments'], '"' + str(root / 'main.py') + '"')
            self.assertTrue(result['FilePath'].lower().endswith(('pythonw.exe', 'python.exe')))

    def test_windows_powershell_chinese_output_and_path(self):
        with tempfile.TemporaryDirectory(prefix='ext4 中文 ') as folder:
            target = Path(folder) / '测试 文件.txt'
            target.write_text('中文测试', encoding='utf-8')
            literal = str(target).replace("'", "''")
            proc = run_powershell(f"Get-Content -LiteralPath '{literal}' -Raw -Encoding UTF8")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), '中文测试')

    def test_batch_dispatch_on_chinese_and_utf8_codepages(self):
        for codepage in (936, 65001):
            for name in ('install_desktop_shortcut.bat', 'start_ext4_mounter.bat', 'start_as_admin.bat'):
                with self.subTest(codepage=codepage, script=name), tempfile.TemporaryDirectory(prefix="ext4 中文 & O'Brien ") as folder:
                    root = Path(folder)
                    (root / 'scripts').mkdir()
                    shutil.copyfile(ROOT / name, root / name)
                    # Substitute a harmless PS endpoint to check the BAT parser and
                    # path forwarding without opening apps or requesting elevation.
                    stub = "param([switch]$AsAdmin)\r\n[IO.File]::WriteAllText((Join-Path $PSScriptRoot '..\\called.txt'), 'OK')\r\n"
                    for ps_name in ('launch.ps1', 'create_desktop_shortcut.ps1'):
                        (root / 'scripts' / ps_name).write_bytes(stub.encode('ascii'))
                    proc = subprocess.run(['cmd.exe', '/d', '/c', f'chcp {codepage} >nul & call {name} <nul'],
                                          cwd=root, capture_output=True, timeout=20)
                    self.assertEqual(proc.returncode, 0, decode_output(proc.stderr))
                    self.assertEqual((root / 'called.txt').read_text(), 'OK')


if __name__ == '__main__':
    unittest.main()
