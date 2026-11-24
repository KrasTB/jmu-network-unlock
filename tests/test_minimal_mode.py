from contextlib import nullcontext
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))


class MinimalModeTests(unittest.TestCase):
    def setUp(self):
        self.minimal = importlib.import_module('minimal_mode')

    def test_preference_persists_and_defaults_to_full_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(self.minimal, 'data_dir', return_value=Path(directory)):
                self.assertFalse(self.minimal.enabled())
                self.minimal.set_enabled(True)
                self.assertTrue(self.minimal.enabled())
                self.minimal.set_enabled(False)
                self.assertFalse(self.minimal.enabled())

    def test_already_online_never_restarts_authentication(self):
        m = self.minimal
        with patch.object(m, 'instance_lock', return_value=nullcontext(True)), \
             patch.object(m, 'probe_device', return_value=True), \
             patch.object(m, 'stop_core') as stop, patch.object(m, 'start_core') as start, \
             patch.object(m, 'notify_result') as notice:
            self.assertEqual(m.authenticate_once({'svc':'3'}, 'nic'), 0)
        stop.assert_not_called()
        start.assert_not_called()
        self.assertEqual(notice.call_count, 1)

    def test_offline_authenticates_once_with_strict_proof_and_no_retries(self):
        m = self.minimal
        for night, ok in [(True, True), (False, False)]:
            with self.subTest(night=night), \
                 patch.object(m, 'instance_lock', return_value=nullcontext(True)), \
                 patch.object(m, 'probe_device', return_value=False), \
                 patch.object(m, 'is_blackout', return_value=night), \
                 patch.object(m, 'should_prepare_bypass', return_value=False), \
                 patch.object(m, 'stop_core') as stop, patch.object(m, 'start_core') as start, \
                 patch.object(m, 'wait_authentication', return_value=(ok, 5)) as wait, \
                 patch.object(m, 'notify_result') as notice:
                conf = {'svc':'3'}
                self.assertEqual(m.authenticate_once(conf, 'nic'), 0 if ok else 1)
                start.assert_called_once_with('bypass' if night else 'normal', conf, 'nic')
                stop.assert_called_once()
                wait.assert_called_once()
                self.assertEqual(notice.call_count, 1)

    def test_minimal_background_entry_exits_before_auth_lock_and_network(self):
        import launcher
        for argument in ('--auto-switch', '--startup-guard'):
            with patch.object(launcher.sys, 'argv', ['app', argument]), \
                 patch.object(self.minimal, 'enabled', return_value=True), \
                 patch.object(launcher, 'instance_lock') as lock:
                launcher.dispatch()
                lock.assert_not_called()

    def test_full_override_and_minimal_entry_do_not_start_each_other(self):
        import launcher
        with patch.object(self.minimal, 'enabled', return_value=True), \
             patch.object(self.minimal, 'shift_requested', return_value=False), \
             patch.object(launcher, 'instance_lock', return_value=nullcontext(True)), \
             patch.object(launcher, 'main') as full, \
             patch.object(launcher, 'run_minimal', create=True) as minimal:
            with patch.object(launcher.sys, 'argv', ['app']):
                launcher.dispatch()
                minimal.assert_called_once()
                full.assert_not_called()
            minimal.reset_mock()
            with patch.object(launcher.sys, 'argv', ['app', '--full']):
                launcher.dispatch()
                full.assert_called_once()
                minimal.assert_not_called()

    def test_scheduled_task_keeps_running_on_battery_without_overlapping_instances(self):
        import launcher
        import xml.etree.ElementTree as ET
        captured = []
        def execute(args, **kwargs):
            captured.append(ET.parse(args[args.index('/XML') + 1]).getroot())
            return type('Result', (), {'returncode':0})()
        with patch.object(launcher.subprocess, 'run', side_effect=execute):
            launcher.set_task(True)
        root = captured[0]
        self.assertEqual(root.findtext('.//{*}DisallowStartIfOnBatteries'), 'false')
        self.assertEqual(root.findtext('.//{*}StopIfGoingOnBatteries'), 'false')
        self.assertEqual(root.findtext('.//{*}MultipleInstancesPolicy'), 'IgnoreNew')
        self.assertEqual(root.findtext('.//{*}Interval'), 'PT2M')


if __name__ == '__main__':
    unittest.main()
