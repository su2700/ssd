"""Startup regressions: all WSL, disk and UAC calls are mocked."""

import builtins
import json
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main
from core.disk_detector import get_physical_disks, get_wsl_distros
from core.wsl_mounter import WslMounter, load_saved_mounts, run_elevated_command
from gui.app import Ext4MounterApp


class TestStartupBoundaries(unittest.TestCase):
    def test_gui_import_failure_is_caught_without_tk_or_stderr(self):
        original_import = builtins.__import__

        def missing_tk(name, *args, **kwargs):
            if name == 'gui.app':
                raise ImportError('Tcl/Tk runtime missing')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=missing_tk), patch(
            'main.configure_logging', return_value='app.log'
        ), patch('main.show_startup_error') as dialog, patch('main.sys.stderr', None), self.assertLogs('ext4_mounter'):
            self.assertEqual(main.main(), 1)
        self.assertIsInstance(dialog.call_args.args[0], ImportError)

    def test_logging_writes_traceback_to_user_directory(self):
        import logging
        logger = logging.getLogger('ext4_mounter')
        previous = list(logger.handlers)
        try:
            with tempfile.TemporaryDirectory() as folder:
                with patch.dict('os.environ', {'LOCALAPPDATA': folder}):
                    path = main.configure_logging()
                try:
                    raise PermissionError('denied')
                except PermissionError:
                    logger.exception('probe failed')
                content = Path(path).read_text(encoding='utf-8')
                self.assertIn('Traceback', content)
                self.assertIn('PermissionError: denied', content)
                for handler in list(logger.handlers):
                    if handler not in previous:
                        logger.removeHandler(handler)
                        handler.close()
        finally:
            logger.handlers[:] = previous

    def test_missing_wsl_and_timeout_are_discovery_errors(self):
        for error in (FileNotFoundError('wsl.exe'), subprocess.TimeoutExpired('wsl.exe', 10)):
            with self.subTest(error=error), patch('core.disk_detector.subprocess.run', side_effect=error), self.assertLogs('ext4_mounter'):
                self.assertIn('error', get_wsl_distros())

    def test_unavailable_disk_queries_are_logged_without_crashing(self):
        with patch('core.disk_detector.run_powershell', side_effect=PermissionError('CIM denied')), self.assertLogs('ext4_mounter') as logs:
            self.assertEqual(get_physical_disks(), [])
        self.assertTrue(any('Get-Disk' in line for line in logs.output))
        self.assertTrue(any('CIM disk query failed' in line for line in logs.output))

    def test_saved_mount_probe_failure_does_not_prune_state(self):
        mounter = WslMounter(discover=False)
        for error in (FileNotFoundError('wsl.exe'), PermissionError('denied'), subprocess.TimeoutExpired('wsl.exe', 10)):
            with self.subTest(error=error), patch('core.wsl_mounter.load_saved_mounts', return_value=[{'mount_name': 'saved'}]), patch(
                'core.wsl_mounter.os.path.exists', return_value=False
            ), patch('core.wsl_mounter.subprocess.run', side_effect=error) as run, patch('core.wsl_mounter.unregister_mount') as prune:
                with self.assertRaises(type(error)):
                    mounter.list_active_mounts()
                self.assertEqual(run.call_args.kwargs['timeout'], 10)
                prune.assert_not_called()

    def test_invalid_saved_state_is_ignored_and_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            for value in (None, {}, ['broken'], [{'mount_name': None}], [{'mount_name': ''}]):
                path.write_text(json.dumps(value), encoding='utf-8')
                with patch('core.wsl_mounter.STATE_FILE', str(path)), self.assertLogs('ext4_mounter'):
                    self.assertEqual(load_saved_mounts(), [])

    def test_cancelled_uac_is_a_result_not_an_exception(self):
        with tempfile.TemporaryDirectory() as folder, patch('core.wsl_mounter.tempfile.gettempdir', return_value=folder), patch(
            'core.wsl_mounter.run_powershell', side_effect=PermissionError('UAC cancelled')
        ):
            code, message = run_elevated_command('wsl.exe --mount example')
            self.assertNotEqual(code, 0)
            self.assertIn('UAC cancelled', message)
            self.assertEqual(list(Path(folder).iterdir()), [])


class TestGuiStartup(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.main_thread = threading.get_ident()
        self.patches = [
            patch('gui.app.get_wsl_distros', return_value={'error': 'WSL missing', 'distros': []}),
            patch('gui.app.get_physical_disks', return_value=[]),
            patch('core.wsl_mounter.load_saved_mounts', return_value=[]),
            patch('gui.app.load_saved_mounts', return_value=[]),
            patch('gui.app.messagebox.showerror'),
            patch('gui.app.messagebox.showwarning'),
        ]
        self.mocks = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.app = Ext4MounterApp(self.root)

    def tearDown(self):
        if not self.app._closed.is_set():
            self.app._close()

    def pump_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(condition(), 'UI did not process worker completion')

    def test_constructor_does_not_discover_and_missing_wsl_keeps_window_alive(self):
        self.mocks[0].assert_not_called()
        self.mocks[1].assert_not_called()
        self.pump_until(lambda: self.mocks[5].called)
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(str(self.app.mount_phys_btn['state']), 'disabled')
        self.assertIn('WSL', self.app.wsl_badge['text'])

    def test_worker_exceptions_reach_ui_on_main_thread(self):
        # Start without running the normal discovery callbacks.
        callback_threads = []
        original = self.app._show_error

        def record(error, **kwargs):
            callback_threads.append(threading.get_ident())
            original(error, **kwargs)

        def fail():
            raise PermissionError('raw disk denied')

        self.app.is_busy = True
        with patch.object(self.app, '_show_error', side_effect=record), self.assertLogs('ext4_mounter'):
            self.app._start_worker(fail, action=True)
            self.pump_until(lambda: self.mocks[4].called)
        self.assertEqual(callback_threads, [self.main_thread])
        self.assertFalse(self.app.is_busy)

    def test_saved_mount_with_missing_wsl_does_not_abort_startup(self):
        with patch('core.wsl_mounter.load_saved_mounts', return_value=[{'mount_name': 'saved'}]), patch(
            'core.wsl_mounter.WslMounter.check_mount_exists', side_effect=FileNotFoundError('wsl.exe')
        ), patch('core.wsl_mounter.unregister_mount') as prune, self.assertLogs('ext4_mounter'):
            self.pump_until(lambda: self.mocks[4].called)
        self.assertTrue(self.root.winfo_exists())
        prune.assert_not_called()

    def test_old_wsl_preserves_raw_images_and_disables_physical_mount(self):
        info = {'default': 'Ubuntu', 'distros': ['Ubuntu'], 'versions': {'Ubuntu': 2},
                'capabilities': {'options': set()}}
        with self.assertLogs('ext4_mounter'):
            self.app._on_system_status(info)
        self.assertEqual(str(self.app.mount_img_btn['state']), 'normal')
        self.assertEqual(str(self.app.mount_phys_btn['state']), 'disabled')
        self.assertEqual(str(self.app.format_phys_btn['state']), 'disabled')
        self.app._restore_action_controls()
        self.assertEqual(str(self.app.mount_phys_btn['state']), 'disabled')

    def test_modern_wsl_enables_windows_disk_actions(self):
        info = {'default': 'Ubuntu', 'distros': ['Ubuntu', 'Debian'],
                'versions': {'Ubuntu': 1, 'Debian': 2}, 'capabilities': {
                    'options': {'--mount', '--unmount', '--bare', '--partition', '--type', '--name'}}}
        self.app._on_system_status(info)
        self.assertEqual(self.app.mounter.distro, 'Debian')
        self.assertEqual(str(self.app.mount_phys_btn['state']), 'normal')
        self.assertEqual(str(self.app.format_phys_btn['state']), 'normal')

    def test_close_during_worker_drops_late_result_without_tk_calls(self):
        release = threading.Event()
        done = threading.Event()
        result = Mock()

        def worker():
            release.wait(2)
            self.app._post_ui(result)
            done.set()

        self.app._start_worker(worker)
        self.app._close()
        release.set()
        self.assertTrue(done.wait(2))
        self.assertTrue(self.app._ui_queue.empty())
        result.assert_not_called()


if __name__ == '__main__':
    unittest.main()
