from contextlib import ExitStack
import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import auto_switch as auto
import schedule
import switch_notifications as status


class CarrierRecoveryTests(unittest.TestCase):
    def test_half_hour_windows_start_at_six_and_do_not_overlap_night_preparation(self):
        with patch.object(schedule, 'load_holidays', return_value=set()):
            for hour, minute, expected in [(5,30,False), (6,0,True), (6,1,True),
                                            (6,2,False), (6,30,True), (12,0,True),
                                            (12,15,False), (22,30,True), (23,0,False)]:
                with self.subTest(hour=hour, minute=minute):
                    self.assertEqual(schedule.is_carrier_recovery_time(datetime.datetime(2026,11,24,hour,minute)), expected)

    def run_recovery(self, now, *, mode='bypass', outcomes=(True,), previous=None):
        with ExitStack() as stack:
            folder = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            stack.enter_context(patch.object(status, 'data_dir', return_value=folder))
            if previous:
                status._save(previous)
            stack.enter_context(patch.object(auto, 'current_mode', return_value=mode))
            conf = stack.enter_context(patch.object(auto, 'read_conf', return_value={'svc':'3'}))
            stack.enter_context(patch.object(auto, 'read_nic', return_value='nic'))
            visit = stack.enter_context(patch.object(auto, 'visit_carrier_portal', return_value=False, create=True))
            switch = stack.enter_context(patch.object(auto, 'switch_to', side_effect=outcomes))
            notices = stack.enter_context(patch.object(auto, 'notify_night_failure'))
            result = auto.recover_carrier(now)
            saved = status.read_switch_status()
            if mode == 'normal' or (previous and previous.get('carrier_recovery_slot') == '2026-11-25T06:00'):
                conf.assert_not_called()
                visit.assert_not_called()
                switch.assert_not_called()
            notices.assert_not_called()
            return result, saved, visit.call_count, switch.call_args_list

    def test_success_is_confirmed_by_authentication_not_portal_response(self):
        result, saved, visits, calls = self.run_recovery(datetime.datetime(2026,11,25,6))
        self.assertEqual(result, 0)
        self.assertEqual(visits, 1)
        self.assertEqual([c.args[0] for c in calls], ['normal'])
        self.assertEqual(saved['carrier_recovered_day'], '2026-11-25')
        self.assertEqual(saved['status'], 'VERIFIED')

    def test_failure_rolls_back_once_and_waits_for_next_half_hour(self):
        now = datetime.datetime(2026,11,25,6)
        result, saved, visits, calls = self.run_recovery(now, outcomes=(False, True))
        self.assertEqual(result, 1)
        self.assertEqual([c.args[0] for c in calls], ['normal', 'bypass'])
        self.assertNotEqual(saved.get('carrier_recovered_day'), now.date().isoformat())
        result2, _, visits2, calls2 = self.run_recovery(now+datetime.timedelta(minutes=1), previous=saved)
        self.assertEqual(result2, 0)
        self.assertEqual((visits2, calls2), (0, []))

    def test_day_complete_and_existing_normal_connection_are_untouched(self):
        now = datetime.datetime(2026,11,25,6)
        self.run_recovery(now, mode='normal')
        _, _, visits, calls = self.run_recovery(now, previous={'carrier_recovered_day':'2026-11-25'})
        self.assertEqual((visits, calls), (0, []))

    def test_four_attempt_limit_survives_task_restart_and_resets_next_day(self):
        previous = {'carrier_recovery_day':'2026-11-25', 'carrier_recovery_attempts':4}
        _, saved, visits, calls = self.run_recovery(datetime.datetime(2026,11,25,8), previous=previous)
        self.assertEqual((visits, calls), (0, []))
        _, saved, visits, calls = self.run_recovery(datetime.datetime(2026,11,26,6), previous=previous)
        self.assertEqual(visits, 1)
        self.assertEqual(saved['carrier_recovery_attempts'], 1)
        self.assertEqual(saved['carrier_recovery_day'], '2026-11-26')

    def test_hidden_portal_get_uses_selected_wired_address_and_is_bounded(self):
        with patch.object(auto, 'resolve_nic', return_value={'device':'nic', 'ip':'192.0.2.8'}), \
             patch.object(auto.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,b'200',b'')) as run:
            self.assertTrue(auto.visit_carrier_portal('nic'))
        args = run.call_args.args[0]
        self.assertEqual(args[-1], 'http://10.8.2.2/')
        self.assertIn('192.0.2.8', args)
        self.assertIn('--noproxy', args)
        self.assertLessEqual(run.call_args.kwargs['timeout'], 6)
        self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)


if __name__ == '__main__':
    unittest.main()
