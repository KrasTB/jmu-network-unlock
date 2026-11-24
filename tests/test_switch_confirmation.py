from pathlib import Path
import sys
import tempfile
import unittest
import datetime
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import runtime_support as support


class SwitchConfirmationTests(unittest.TestCase):
    def test_cutoff_old_online_session_still_notifies_and_attempts_switch(self):
        import auto_switch as scheduler
        now = datetime.datetime(2026, 11, 24, 23)
        class Clock(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return now
        with ExitStack() as stack:
            stack.enter_context(patch.object(scheduler.sys, 'argv', ['auto_switch']))
            stack.enter_context(patch.object(scheduler.datetime, 'datetime', Clock))
            for name, value in {'read_switch_status': {}, 'read_conf': {'svc': '1'},
                                'read_nic': 'device', 'current_mode': 'normal', 'online': True,
                                'server_confirmed': False, 'read_auth_state': {},
                                'switch_to': False}.items():
                stack.enter_context(patch.object(scheduler, name, return_value=value))
            notify = stack.enter_context(patch.object(scheduler, 'notify_night_failure'))
            record = stack.enter_context(patch.object(scheduler, 'record_switch'))
            self.assertEqual(scheduler.main(), 1)
            self.assertTrue(notify.called)
            self.assertTrue(all(call.args[0] != 'VERIFIED' for call in record.call_args_list))

    def test_weekend_failure_notifies_at_midnight(self):
        import switch_notifications as notices
        import schedule
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(notices, 'data_dir', return_value=Path(directory)), \
                 patch.object(schedule, 'load_holidays', return_value=set()), \
                 patch.object(notices.subprocess, 'Popen') as popen:
                self.assertFalse(notices.notify_night_failure(now=datetime.datetime(2026,11,27,23,59)))
                self.assertTrue(notices.notify_night_failure(now=datetime.datetime(2026,11,28,0,0)))
                self.assertEqual(popen.call_count, 1)

    def test_old_online_session_cannot_mark_new_authentication_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(support, 'data_dir', return_value=Path(directory)), \
                 patch.object(support, 'boot_epoch', return_value=1000):
                support.auth_state('bypass', 'test-device', verified=True)
                self.assertFalse(support.read_auth_state().get('verified'))

    def test_no_seven_second_release_wait_when_no_process_exists(self):
        with patch.object(support, 'process_info', return_value=[]), patch.object(support.time, 'sleep') as sleep:
            support.stop_core()
        sleep.assert_not_called()

    def test_first_stage_success_is_not_full_bypass_success(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(support, 'data_dir', return_value=folder), patch.object(support, 'boot_epoch', return_value=1000):
                attempt = support.begin_auth_attempt('bypass', 'test-device')
                result = folder / attempt['result_file']
                result.write_text('STAGE1_OK\n', encoding='ascii')
                self.assertFalse(support.server_confirmed('bypass', 'test-device'))
                support.auth_state('bypass', 'test-device', verified=True)
                self.assertFalse(support.read_auth_state()['verified'])
                result.write_text('SUCCESS\n', encoding='ascii')
                self.assertTrue(support.server_confirmed('bypass', 'test-device'))
                support.auth_state('bypass', 'test-device', verified=True)
                self.assertTrue(support.read_auth_state()['verified'])
                self.assertFalse(support.server_confirmed('normal', 'test-device'))
                self.assertFalse(support.server_confirmed('bypass', 'another-device'))

    def test_old_attempt_success_file_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(support, 'data_dir', return_value=folder), patch.object(support, 'boot_epoch', return_value=1000):
                old = support.begin_auth_attempt('bypass', 'test-device')
                (folder / old['result_file']).write_text('SUCCESS', encoding='ascii')
                self.assertTrue(support.server_confirmed('bypass', 'test-device'))
                new = support.begin_auth_attempt('bypass', 'test-device')
                self.assertNotEqual(new['attempt'], old['attempt'])
                self.assertFalse(support.server_confirmed('bypass', 'test-device'))

    def test_old_network_is_not_probed_as_evidence_before_server_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = [0.0]
            with patch.object(support, 'data_dir', return_value=Path(directory)), \
                 patch.object(support, 'boot_epoch', return_value=1000), \
                 patch.object(support.time, 'monotonic', side_effect=lambda: clock[0]), \
                 patch.object(support.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0]+seconds)), \
                 patch.object(support, 'probe_device', return_value=True) as probe:
                support.begin_auth_attempt('bypass', 'test-device')
                self.assertEqual(support.wait_authentication('bypass', 'test-device', timeout=3), (False, 3))
                probe.assert_not_called()

    def test_stability_failure_is_detected_before_the_full_minute(self):
        clock = [0.0]
        with patch.object(support, 'server_confirmed', return_value=True), \
             patch.object(support, 'probe_device', side_effect=lambda *args, **kwargs: clock[0] < 3), \
             patch.object(support, 'auth_state'), \
             patch.object(support.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(support.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0]+seconds)):
            self.assertFalse(support.monitor_stability('normal', 'test-device', 60, 2))
        self.assertLessEqual(clock[0], 4)

    def test_boundary_failure_requests_native_notification_once_until_recovery(self):
        import switch_notifications as notices
        import schedule
        now = datetime.datetime(2026, 11, 24, 23)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(notices, 'data_dir', return_value=Path(directory)), \
                 patch.object(schedule, 'load_holidays', return_value=set()), \
                 patch.object(notices.subprocess, 'Popen') as popen:
                self.assertTrue(notices.notify_night_failure(now=now, connected=True))
                self.assertFalse(notices.notify_night_failure(now=now+datetime.timedelta(minutes=2), connected=False))
                self.assertEqual(popen.call_count, 1)
                arguments = popen.call_args.args[0]
                self.assertIn('notify.ps1', arguments[5])
                self.assertEqual(popen.call_args.kwargs['creationflags'], 0x08000000)
                notices.record_switch('VERIFIED', 'bypass')
                self.assertTrue(notices.notify_night_failure(now=now+datetime.timedelta(minutes=10), connected=False))
                self.assertEqual(popen.call_count, 2)

    def test_no_notification_before_cutoff_or_on_holidays(self):
        import switch_notifications as notices
        import schedule
        with patch.object(schedule, 'load_holidays', return_value=set()), patch.object(notices.subprocess, 'Popen') as popen:
            self.assertFalse(notices.notify_night_failure(now=datetime.datetime(2026,11,24,22,59)))
            popen.assert_not_called()
        with patch.object(schedule, 'load_holidays', return_value={datetime.date(2026,11,24)}), \
             patch.object(notices.subprocess, 'Popen') as popen:
            self.assertFalse(notices.notify_night_failure(now=datetime.datetime(2026,11,24,23)))
            popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
