from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
from repair_ops import apply_update


class RepairTests(unittest.TestCase):
    def test_real_window_repairs_selected_installation(self):
        import repair_launcher
        import tkinter as tk
        from tkinter import ttk
        import sys
        with tempfile.TemporaryDirectory(prefix='修复 窗口-') as directory:
            location = Path(directory)
            root_dir = location / '已部署 助手'
            data = root_dir / '程序'
            data.mkdir(parents=True)
            payload = location / 'payload'
            payload.mkdir()
            (root_dir / '校园网助手.exe').write_bytes(b'old')
            (data / 'jmusupplicant.exe').write_bytes(b'core')
            (data / 'config.txt').write_bytes(b'preserve-account')
            (payload / '校园网助手.exe').write_bytes(b'new')
            (payload / 'getnic.ps1').write_bytes(b'new-script')
            window = tk.Tk()
            observed = []
            errors = []
            def widgets(parent):
                result = []
                for child in parent.winfo_children():
                    result.append(child)
                    result.extend(widgets(child))
                return result
            def start():
                try:
                    items = widgets(window)
                    self.assertTrue(window.winfo_viewable())
                    next(w for w in items if isinstance(w, ttk.Button) and w.cget('text') == '选择…').invoke()
                    next(w for w in items if isinstance(w, ttk.Button) and w.cget('text') == '修复').invoke()
                    window.after(100, inspect)
                except Exception as exc:
                    errors.append(repr(exc))
                    window.destroy()
            def inspect():
                try:
                    items = widgets(window)
                    labels = [w.cget('text') for w in items if isinstance(w, ttk.Label)]
                    if any('修复完成' in text for text in labels):
                        observed.append(True)
                        window.destroy()
                        return
                    window.after(100, inspect)
                except Exception as exc:
                    errors.append(repr(exc))
                    window.destroy()
            window.after(150, start)
            window.after(8000, window.destroy)
            with patch.object(sys, '_MEIPASS', str(location), create=True), \
                 patch.object(repair_launcher.tk, 'Tk', return_value=window), \
                 patch.object(repair_launcher.filedialog, 'askopenfilename', return_value=str(root_dir / '校园网助手.exe')), \
                 patch.object(repair_launcher, 'resolve_nic', return_value={'name': 'USB Ethernet'}):
                repair_launcher.main()
            self.assertFalse(errors, errors)
            self.assertEqual(observed, [True])
            self.assertEqual((root_dir / '校园网助手.exe').read_bytes(), b'new')
            self.assertEqual((data / 'config.txt').read_bytes(), b'preserve-account')

    def test_updates_program_and_preserves_account_and_backs_up_old_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '已部署 助手'
            data = root / '程序'
            data.mkdir(parents=True)
            payload = Path(directory) / 'payload'
            payload.mkdir()
            (root / '校园网助手.exe').write_bytes(b'old-executable')
            (data / 'jmusupplicant.exe').write_bytes(b'unchanged-core')
            (data / 'getnic.ps1').write_bytes(b'old-script')
            (data / 'config.txt').write_bytes(b'private-account-configuration')
            (data / 'nic.txt').write_bytes(b'old-computer-nic')
            (payload / '校园网助手.exe').write_bytes(b'new-executable')
            (payload / 'getnic.ps1').write_bytes(b'new-script')
            backup = apply_update(root, payload)
            self.assertEqual((root / '校园网助手.exe').read_bytes(), b'new-executable')
            self.assertEqual((data / 'getnic.ps1').read_bytes(), b'new-script')
            self.assertEqual((data / 'config.txt').read_bytes(), b'private-account-configuration')
            self.assertEqual((data / 'jmusupplicant.exe').read_bytes(), b'unchanged-core')
            self.assertEqual((backup / '校园网助手.exe').read_bytes(), b'old-executable')
            self.assertEqual((backup / 'nic.txt').read_bytes(), b'old-computer-nic')

    def test_partial_update_failure_restores_old_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '助手'
            data = root / '程序'
            data.mkdir(parents=True)
            payload = Path(directory) / 'payload'
            payload.mkdir()
            (root / '校园网助手.exe').write_bytes(b'old')
            (data / 'jmusupplicant.exe').write_bytes(b'core')
            (data / 'getnic.ps1').write_bytes(b'old-script')
            (payload / '校园网助手.exe').write_bytes(b'new')
            (payload / 'getnic.ps1').write_bytes(b'new-script')
            original = os.replace
            def replace(src, dest):
                if Path(dest).name == 'getnic.ps1':
                    raise PermissionError('locked')
                return original(src, dest)
            with patch('repair_ops.os.replace', side_effect=replace):
                with self.assertRaises(PermissionError):
                    apply_update(root, payload)
            self.assertEqual((root / '校园网助手.exe').read_bytes(), b'old')
            self.assertEqual((data / 'getnic.ps1').read_bytes(), b'old-script')
            self.assertFalse(list(root.rglob('*.repair-*')))


def run_checks(payload):
    import io
    result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(RepairTests))
    # Real embedded update payload must also be present in the single-file repair tool.
    return {'ok': result.wasSuccessful() and (payload / '校园网助手.exe').is_file() and (payload / 'getnic.ps1').is_file(),
            'checks': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors)}


if __name__ == '__main__':
    unittest.main()
