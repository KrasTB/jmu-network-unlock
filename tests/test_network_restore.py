from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))


class NetworkRestoreTests(unittest.TestCase):
    def test_reserved_ip_requires_an_installation_local_explicit_override(self):
        import office_ip_policy as policy
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(policy, 'data_dir', return_value=folder):
                with self.assertRaises(ValueError):
                    policy.check_office_ip('172.20.1.11')
                (folder / 'personal_office_ip.txt').write_text('172.20.1.11', encoding='ascii')
                self.assertEqual(policy.check_office_ip('172.20.1.11'), '172.20.1.11')
    def test_restore_pauses_before_stopping_all_cores_and_preserves_configuration(self):
        import network_restore as restore
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = folder / 'config.txt'
            config.write_bytes(b'private configuration')
            (folder / 'auth_state.json').write_text('{"verified":true}')
            with patch.object(restore, 'data_dir', return_value=folder), \
                 patch.object(restore, 'stop_core') as stop, \
                 patch.object(restore, 'record_switch') as status:
                stop.side_effect = lambda **kw: self.assertTrue(restore.paused())
                auto, task = Mock(), Mock()
                self.assertEqual(restore.restore_default(auto, task), [])
                stop.assert_called_once_with(wait=0, all_copies=True)
                auto.assert_called_once_with(False)
                task.assert_called_once()
                self.assertFalse((folder / 'auth_state.json').exists())
                self.assertEqual(config.read_bytes(), b'private configuration')
                self.assertEqual(status.call_args.args[0], 'STOPPED')
                restore.resume()
                self.assertFalse(restore.paused())

    def test_partial_failures_are_reported_and_do_not_prevent_stopping_core(self):
        import network_restore as restore
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(restore, 'data_dir', return_value=Path(directory)), \
                 patch.object(restore, 'stop_core') as stop, patch.object(restore, 'record_switch'):
                errors = restore.restore_default(Mock(side_effect=OSError('registry')), Mock())
                self.assertTrue(errors)
                stop.assert_called_once()
                self.assertTrue(restore.paused())

    def test_paused_background_entry_never_takes_authentication_lock(self):
        import network_restore as restore
        import launcher
        import minimal_mode
        with patch.object(restore, 'paused', return_value=True), \
             patch.object(minimal_mode, 'enabled', return_value=False), \
             patch.object(launcher, 'instance_lock') as lock, \
             patch.object(launcher.sys, 'argv', ['app', '--auto-switch']):
            launcher.dispatch()
            lock.assert_not_called()

    def test_paused_core_start_fails_before_creating_auth_attempt(self):
        import network_restore as restore
        import runtime_support as support
        with patch.object(restore, 'paused', return_value=True), \
             patch.object(support, 'begin_auth_attempt') as begin, \
             patch.object(support.subprocess, 'Popen') as start:
            with self.assertRaises(RuntimeError):
                support.start_core('bypass', {}, 'nic')
            begin.assert_not_called()
            start.assert_not_called()

    def test_cancellation_stops_waiting_without_network_probes_or_failure_notice(self):
        import network_restore as restore
        import runtime_support as support
        import switch_notifications as notices
        with patch.object(restore, 'paused', return_value=True), \
             patch.object(support, 'probe_device') as probe, \
             patch.object(notices.subprocess, 'Popen') as notify:
            self.assertFalse(support.wait_authentication('bypass', 'nic', timeout=3)[0])
            self.assertFalse(notices.notify_night_failure())
            probe.assert_not_called()
            notify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
