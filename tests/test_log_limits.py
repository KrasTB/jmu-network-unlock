import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import runtime_log as log


class LogLimitsTests(unittest.TestCase):
    def test_debug_details_are_off_by_default_and_can_be_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            log.event('nic', 'candidate', level='DEBUG', base=base)
            self.assertFalse((base/'runtime.log').exists())
            (base/'debug_logging.flag').touch()
            log.event('nic', 'candidate', level='DEBUG', base=base)
            self.assertEqual(json.loads((base/'runtime.log').read_text(encoding='utf-8'))['event'], 'candidate')

    def test_migration_prunes_extra_backups_and_keeps_every_file_under_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for suffix in ('', '.1', '.2', '.3'):
                (base/('runtime.log'+suffix)).write_text((json.dumps({'event':'旧记录'})+'\n')*100, encoding='utf-8')
            with patch.object(log, 'MAX_BYTES', 600):
                log.event('test', 'new result', base=base)
            files = list(base.glob('runtime.log*'))
            self.assertLessEqual(len(files), 2)
            self.assertTrue(files)
            for path in files:
                self.assertLessEqual(path.stat().st_size, 600)
                for line in path.read_text(encoding='utf-8').splitlines():
                    json.loads(line)

    def test_repeated_switch_heartbeat_does_not_repeat_info_log(self):
        import switch_notifications as switches
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            with patch.object(switches, 'data_dir', return_value=base), \
                 patch.object(switches, 'event') as event:
                switches.record_switch('VERIFIED', 'bypass', 'online', connected=True)
                switches.record_switch('VERIFIED', 'bypass', 'online', connected=True)
                switches.record_switch('FAILED', 'bypass', 'offline', connected=False)
            info = [c for c in event.call_args_list if c.kwargs.get('level','INFO') == 'INFO']
            self.assertEqual(len(info), 2)


if __name__ == '__main__':
    unittest.main()
