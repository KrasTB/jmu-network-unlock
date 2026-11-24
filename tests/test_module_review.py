from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
"""Behavior checks against staged runtime modules; all networking is simulated."""
import importlib
import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import json
import threading
from types import SimpleNamespace


class ModuleReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tools = Path(__file__).parent
        cls.stage = ROOT / 'app'
        sys.path.insert(0, str(cls.stage))
        for name in ['control', 'auto_switch', 'startup_guard', 'schedule']:
            sys.modules.pop(name, None)
        cls.control = importlib.import_module('control')
        cls.auto = importlib.import_module('auto_switch')
        cls.schedule = importlib.import_module('schedule')

    def test_portal_200_and_redirect_are_never_online(self):
        for code in [b'200', b'302', b'000']:
            with self.subTest(code=code), patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, code, b'')):
                self.assertFalse(self.control.probe_net('10.0.0.8'))

    def test_holiday_night_remains_exempt_after_midnight(self):
        with patch.object(self.schedule, 'load_holidays', return_value={datetime.date(2026, 11, 11)}):
            self.assertFalse(self.schedule.is_blackout(datetime.datetime(2026, 11, 12, 1)))
            self.assertTrue(self.schedule.is_blackout(datetime.datetime(2026, 11, 12, 23, 1)))

    def test_truncated_configuration_is_rejected_before_nic_or_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'config.txt'
            file.write_text('test-account test-password', encoding='utf-8')
            with patch.object(self.auto, 'CFG', str(file)):
                with self.assertRaises(ValueError):
                    self.auto.read_conf()

    def test_probe_204_requires_successful_curl_exit(self):
        for exit_code, expected in [(0, True), (7, False)]:
            with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], exit_code, b'204', b'')):
                self.assertEqual(self.control.probe_net('10.0.0.8'), expected)

    def test_timeout_includes_probe_duration(self):
        import runtime_support as support
        clock = [0.0]
        calls = []
        def probe():
            calls.append(True)
            clock[0] += 4
            return False
        with patch.object(support.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(support.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            self.assertEqual(support.wait_check(probe, 10, 2), (False, 10))
        self.assertEqual(len(calls), 2)

    def test_log_redacts_credentials_and_rotates(self):
        import runtime_log
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'config.txt').write_text('sensitive-account sensitive-password 172.20.1.10 255.255.0.0 3', encoding='utf-8')
            with patch.object(runtime_log, 'MAX_BYTES', 600):
                for index in range(10):
                    runtime_log.event('test', '日志隐私检查', base=folder, index=index,
                                      reason='sensitive-account sensitive-password', password='sensitive-password',
                                      command=['secret-command'])
            logs = list(folder.glob('runtime.log*'))
            self.assertLessEqual(len(logs), 4)
            self.assertTrue((folder / 'runtime.log.1').exists())
            for path in logs:
                raw = path.read_text(encoding='utf-8')
                self.assertNotIn('sensitive-account', raw)
                self.assertNotIn('sensitive-password', raw)
                self.assertNotIn('secret-command', raw)
                self.assertLessEqual(path.stat().st_size, 600)
                for line in raw.splitlines():
                    json.loads(line)

    def test_core_start_passes_selected_carrier_without_logging_command(self):
        import runtime_support as support
        conf = dict(user='test-account', pwd='test-password', oip='172.20.1.10', omask='255.255.0.0', svc='2')
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(support, 'data_dir', return_value=Path(directory)), \
                 patch.object(support.subprocess, 'Popen', return_value=SimpleNamespace(pid=456)) as popen, \
                 patch.object(support.threading, 'Thread', return_value=SimpleNamespace(start=lambda: None)):
                support.start_core('bypass', conf, r'\Device\NPF_{TEST}')
            arguments = popen.call_args.args[0]
            self.assertEqual(arguments[arguments.index('-s') + 1], '0')
            self.assertEqual(popen.call_args.kwargs['env']['JMU_MIDNIGHT_SERVICE'], '2')

    def test_stop_only_targets_owned_pids(self):
        import runtime_support as support
        with patch.object(support, 'process_info', return_value=[{'pid': 456, 'mode': 'normal'}]), \
             patch.object(support.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as run, \
             patch.object(support.time, 'sleep'):
            support.stop_core()
        self.assertEqual(run.call_args.args[0], ['taskkill.exe', '/F', '/PID', '456'])

    def test_confirmed_mode_survives_core_exit_but_not_reboot(self):
        import runtime_support as support
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'nic.txt').write_text(r'\Device\NPF_{TEST}', encoding='ascii')
            with patch.object(support, 'data_dir', return_value=folder), patch.object(support, 'process_info', return_value=[]):
                with patch.object(support, 'boot_epoch', return_value=1000):
                    support.auth_state('bypass', r'\Device\NPF_{TEST}', verified=True)
                    self.assertEqual(support.auth_mode(), 'bypass')
                with patch.object(support, 'boot_epoch', return_value=2000):
                    self.assertIsNone(support.auth_mode())

    def test_startup_command_quoting_does_not_hide_enabled_state(self):
        import package_runtime
        expected = package_runtime.app_command('startup-guard')
        quoted = subprocess.list2cmdline(expected)
        alternative = '"' + expected[0] + '" ' + subprocess.list2cmdline(expected[1:])
        self.assertTrue(package_runtime.command_matches(quoted, 'startup-guard'))
        self.assertTrue(package_runtime.command_matches(alternative, 'startup-guard'))
        self.assertFalse(package_runtime.command_matches(alternative, 'auto-switch'))

    def test_gui_distinguishes_link_auth_and_historical_success(self):
        import tkinter as tk
        window = tk.Tk()
        with patch.object(tk.Misc, 'after', return_value=None):
            app = self.control.App(window)
        try:
            app.snap = {'STATUS': 'Up', 'IP': '10.0.0.8', 'NIC_NAME': 'USB LAN',
                        '_startup': {'state': 'VERIFIED', 'time': '2026-01-01 10:00:00'}}
            app.net_wired = app.net_any = False
            app.render()
            self.assertIn('联网验证未通过', app.head.cget('text'))
            self.assertIn('当时有线联网验证通过', app.body.cget('text'))
            app._auth_phase = '启动认证并验证联网'
            app.net_wired = True
            app.render()
            self.assertIn('正在认证', app.head.cget('text'))
            self.assertIn('正在重新验证', app.body.cget('text'))
            self.assertFalse(hasattr(app, 'btn_hs'))
        finally:
            app.alive = False
            window.destroy()

    def test_scheduler_does_not_wait_forever_for_stale_process(self):
        auto = self.auto
        conf = dict(user='test-account', pwd='test-password', oip='172.20.1.10', omask='255.255.0.0', svc='3')
        with patch.object(sys, 'argv', ['test', '--force']), \
             patch.object(auto, 'read_conf', return_value=conf), patch.object(auto, 'read_nic', return_value='test-nic'), \
             patch.object(auto, 'current_mode', return_value='bypass'), patch.object(auto, 'is_blackout', return_value=True), \
             patch.object(auto, 'should_prepare_bypass', return_value=False), patch.object(auto, 'online', return_value=False), \
             patch.object(auto, 'wait_online', side_effect=[(False, 20), (True, 2)]), \
             patch.object(auto, 'kill_proc'), patch.object(auto, 'start_proc') as start, patch.object(auto, 'auth_state'):
            self.assertEqual(auto.main(), 0)
            self.assertEqual(start.call_args.args, ('bypass', conf, 'test-nic'))

    def test_speed_uses_selected_wired_ip_and_correct_megabyte_unit(self):
        def output(args, **kwargs):
            return '1000000' if '%{speed_download}' in args else '0.05'
        with patch.object(self.control, 'wired_ip', return_value='10.0.0.8'), \
             patch.object(self.control, 'probe_net', return_value=True), \
             patch.object(self.control, 'sh', side_effect=output) as run:
            result = self.control.App._measure_speed(SimpleNamespace())
        self.assertEqual(result['mbps'], 1.0)
        for call in run.call_args_list:
            arguments = call.args[0]
            self.assertEqual(arguments[arguments.index('--interface') + 1], '10.0.0.8')


if __name__ == '__main__':
    unittest.main()
