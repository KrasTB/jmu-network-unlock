"""Side-effect-free acceptance checks, invoked only by the explicit self-test flag."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import sys


def run(report):
    results = []
    try:
        import launcher
        import control
        import auto_switch
        import startup_guard
        import schedule
        import office_ip_policy
        import nic_manager
        from package_runtime import data_dir, app_command, instance_lock
        base = data_dir()
        assert Path(control.BASE) == base
        assert Path(auto_switch.BASE) == base
        assert Path(startup_guard.BASE) == base
        assert Path(schedule.HOLIDAY_FILE).parent == base
        for name in ['jmusupplicant.exe', 'libiconv-2.dll', 'getnic.ps1', 'install_npcap.ps1', 'holidays.txt']:
            assert (base / name).is_file(), name
        results.append('standalone_imports_and_stable_paths')
        for mode in ['auto-switch', 'startup-guard']:
            command = app_command(mode)
            assert command[-1] == '--' + mode
            if getattr(sys, 'frozen', False):
                assert command == [sys.executable, '--' + mode]
        results.append('frozen_startup_and_scheduled_commands')
        with instance_lock('selftest') as first:
            assert first
            with instance_lock('selftest') as second:
                assert not second
        results.append('cross_process_mutex')

        with tempfile.TemporaryDirectory(prefix='jmu-settings-test-') as directory:
            testdir = Path(directory)
            launcher.CFG = testdir / 'config.txt'
            assert launcher.read_fields()[2] == '172.20.1.10'
            root = tk.Tk()
            root.withdraw()
            observations = []

            def save_form():
                window = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
                observations.append(bool(window.winfo_viewable()))
                entries = [w for w in window.winfo_children() if type(w) is ttk.Entry]
                for entry, value in zip(entries, ['test-account', 'test-password', '172.20.1.10', '255.255.0.0']):
                    entry.delete(0, 'end')
                    entry.insert(0, value)
                next(w for w in window.winfo_children() if type(w) is ttk.Button).invoke()

            root.after(150, save_form)
            assert launcher.configure(root)
            assert observations == [True]
            fields = launcher.CFG.read_text(encoding='utf-8').split()
            assert fields[0] == 'test-account' and fields[2] == '172.20.1.10'
            results.append('first_run_dialog_visible_and_config_saved')

            previous = launcher.CFG.read_bytes()
            errors = []
            original_error = launcher.messagebox.showerror
            launcher.messagebox.showerror = lambda *args, **kwargs: errors.append(str(args))

            def blocked_form():
                window = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
                entries = [w for w in window.winfo_children() if type(w) is ttk.Entry]
                entries[2].delete(0, 'end')
                entries[2].insert(0, '172.20.1.11')
                next(w for w in window.winfo_children() if type(w) is ttk.Button).invoke()
                window.destroy()

            root.after(150, blocked_form)
            assert not launcher.configure(root)
            launcher.messagebox.showerror = original_error
            root.destroy()
            assert errors and '172.20.1.11' in errors[0]
            assert launcher.CFG.read_bytes() == previous
            results.append('reserved_address_rejected_by_real_save_button')

            (testdir / 'nic.txt').write_text(r'\Device\NPF_{TEST}', encoding='ascii')
            control.CFG = str(launcher.CFG)
            control.NICF = str(testdir / 'nic.txt')
            auto_switch.CFG = str(launcher.CFG)
            # Hardware boundary is simulated: self-test must never select a real NIC.
            control.resolve_nic = lambda **kwargs: {'device': r'\Device\NPF_{TEST}'}
            auto_switch.resolve_nic = control.resolve_nic
            assert control.read_conf()[2] == '172.20.1.10'
            assert auto_switch.read_conf()['oip'] == '172.20.1.10'
            assert auto_switch.read_nic() == r'\Device\NPF_{TEST}'
            assert control.read_conf()[-1] == r'\Device\NPF_{TEST}'
            first = dict(device=r'\Device\NPF_{A}', name='Ethernet', status='Up', wired=True, ip='')
            second = dict(first, device=r'\Device\NPF_{B}', name='USB Ethernet')
            assert nic_manager.select_adapter([first], r'\Device\NPF_{STALE}') == first
            assert nic_manager.select_adapter([first, second], second['device']) == second
            usb = dict(first, device=r'\Device\NPF_{USB}', wired=False, selectable=True)
            assert nic_manager.select_adapter([usb], usb['device']) == usb
            try:
                nic_manager.select_adapter([usb])
            except nic_manager.NicError:
                pass
            else:
                raise AssertionError('Unknown USB medium should require manual selection')
            for candidates in [[first, second], [dict(first, wired=False)], [dict(first, status='Disconnected')]]:
                try:
                    nic_manager.select_adapter(candidates)
                except nic_manager.NicError:
                    pass
                else:
                    raise AssertionError('Ambiguous or disconnected adapter accepted')
            results.append('shared_auth_paths_and_adapter_selection_regressions')
            launcher.CFG.write_text('test-account test-password 172.20.1.11 255.255.0.0 3', encoding='ascii')
            for read in [control.read_conf, auto_switch.read_conf]:
                try:
                    read()
                except ValueError:
                    pass
                else:
                    raise AssertionError('Reserved address accepted')
            startup_guard.BASE = str(testdir)
            startup_guard.LOG = str(testdir / 'startup.log')
            startup_guard.STATUS = str(testdir / 'status.txt')
            def forbidden():
                raise AssertionError('Unexpected real network/authentication action')
            startup_guard.link_up = forbidden
            startup_guard.start_auth = forbidden
            startup_guard.stop_auth = forbidden
            assert startup_guard.ensure_connected() == 2
            assert 'state=FAILED' in Path(startup_guard.STATUS).read_text(encoding='utf-8')
            results.append('all_authentication_paths_reject_reserved_address_before_network_actions')

            # Build the real main window without running timers, installing drivers or registering anything.
            original_after = tk.Misc.after
            original_loop = tk.Misc.mainloop
            tk.Misc.after = lambda *args, **kwargs: None
            windows = []
            def inspect_window(window, *args, **kwargs):
                menu = window.nametowidget(window.cget('menu'))
                assert menu.entrycget(1, 'label') == '设置'
                assert window.title() == '校园网助手'
                def all_widgets(parent):
                    result = []
                    for child in parent.winfo_children():
                        result.append(child)
                        result.extend(all_widgets(child))
                    return result
                texts = [str(w.cget('text')) for w in all_widgets(window) if 'text' in w.keys()]
                assert not any('热点' in text for text in texts)
                assert not hasattr(control.App, 'render_hotspot')
                assert any(text == '夜间认证' for text in texts)
                windows.append(True)
                window.destroy()
            tk.Misc.mainloop = inspect_window
            launcher.ensure_npcap = lambda: True
            launcher.ensure_nic = lambda: None
            launcher.autostart_enabled = lambda: False
            launcher.task_enabled = lambda: False
            launcher.CFG.write_bytes(previous)
            try:
                launcher.main()
            finally:
                tk.Misc.after = original_after
                tk.Misc.mainloop = original_loop
            assert windows == [True]
            results.append('real_main_window_and_settings_menu')
            results.append('hotspot_removed_and_action_labels_clear')

        report.write_text(json.dumps({'ok': True, 'checks': results, 'frozen': bool(getattr(sys, 'frozen', False))},
                                     ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        import traceback
        report.write_text(json.dumps({'ok': False, 'checks': results, 'error': traceback.format_exc()},
                                     ensure_ascii=False, indent=2), encoding='utf-8')
        raise
