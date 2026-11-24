"""Single entry for the shareable distribution."""
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from office_ip_policy import check_office_ip, DEFAULT_OFFICE_IP
from package_runtime import data_dir, app_command, instance_lock, ensure_npcap, command_matches
from nic_manager import resolve_nic, NicError, choose_dialog
from runtime_log import event

BASE = data_dir()
CFG = BASE / 'config.txt'
NO_WINDOW = 0x08000000
SERVICES = ('教育网', '联通', '移动', '电信')
TASK = 'JMU_Shared_AutoSwitch'
RUN_NAME = 'JMU_Shared_StartupGuard'


def validate_fields(fields):
    if len(fields) != 5:
        raise ValueError('请填写完整的五项配置。')
    user, password, address, mask, service = fields
    if not user or not password or any(c.isspace() for c in user + password) or '"' in user + password:
        raise ValueError('账号和密码不能为空，当前版本不支持其中包含空白字符。')
    if user == '202500000000' or password == 'yourpassword':
        raise ValueError('请填写自己的账号密码，不能使用示例值。')
    check_office_ip(address)
    ipaddress.IPv4Network('0.0.0.0/' + mask)
    if service not in ('0', '1', '2', '3'):
        raise ValueError('请选择运营商。')
    return fields


def read_fields():
    try:
        return validate_fields(CFG.read_text(encoding='utf-8-sig').split())
    except (OSError, ValueError):
        return ['', '', DEFAULT_OFFICE_IP, '255.255.0.0', '3']


def configure(parent):
    dialog = tk.Toplevel(parent)
    dialog.title('账号与认证设置')
    dialog.resizable(False, False)
    if parent.state() != 'withdrawn':
        dialog.transient(parent)
    values = read_fields()
    variables = [tk.StringVar(value=v) for v in values]
    labels = ['校园网账号', '密码', '办公区认证 IP', '掩码', '运营商']
    for row, label in enumerate(labels):
        ttk.Label(dialog, text=label).grid(row=row, column=0, padx=14, pady=7, sticky='w')
        if row == 4:
            picker = ttk.Combobox(dialog, values=SERVICES, state='readonly', width=27)
            picker.current(int(values[4]))
            picker.grid(row=row, column=1, padx=14, pady=7)
        else:
            ttk.Entry(dialog, textvariable=variables[row], show='*' if row == 1 else '', width=30).grid(
                row=row, column=1, padx=14, pady=7)
    ttk.Label(dialog, text='认证 IP 不等于 Windows 网卡 IP，请勿照搬到网卡设置。').grid(
        row=5, column=0, columnspan=2, padx=14, pady=8)
    saved = [False]

    def save():
        fields = [v.get() for v in variables[:4]] + [str(picker.current())]
        try:
            validate_fields(fields)
            temp = CFG.with_suffix('.tmp')
            temp.write_text(' '.join(fields) + '\n', encoding='utf-8')
            os.replace(temp, CFG)
        except (ValueError, OSError) as exc:
            messagebox.showerror('无法保存', str(exc), parent=dialog)
            return
        saved[0] = True
        event('settings', '认证设置已保存', office_ip=fields[2], service=fields[4], reconnect_required=True)
        dialog.destroy()

    ttk.Button(dialog, text='保存', command=save).grid(row=6, column=0, columnspan=2, pady=12)
    # Map the dialog before entering the modal loop. Slow Windows font/widget
    # initialization can otherwise let an earlier callback run before the show timer.
    dialog.deiconify()
    dialog.update_idletasks()
    dialog.lift()
    dialog.focus_force()
    dialog.grab_set()
    parent.wait_window(dialog)
    return saved[0]


def pythonw():
    path = Path(sys.executable)
    candidate = path.with_name('pythonw.exe')
    return str(candidate if candidate.exists() else path)


def set_autostart(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            command = subprocess.list2cmdline(app_command('startup-guard'))
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            value = winreg.QueryValueEx(key, RUN_NAME)[0]
        return command_matches(value, 'startup-guard')
    except OSError:
        return False


def task_enabled():
    result = subprocess.run(['schtasks', '/Query', '/TN', TASK, '/XML'],
                            capture_output=True, creationflags=NO_WINDOW, timeout=12)
    # schtasks declares UTF-16 even when redirected output uses the console OEM code page.
    raw = result.stdout
    encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) or b'\x00' in raw[:8] else 'oem'
    text = raw.decode(encoding, errors='replace')
    if result.returncode:
        return False
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
        if root.findtext('.//{*}Settings/{*}Enabled', 'true').lower() == 'false':
            return False
        for action in root.findall('.//{*}Exec'):
            command = action.findtext('{*}Command', '').strip('"')
            arguments = action.findtext('{*}Arguments', '')
            if command_matches(subprocess.list2cmdline([command]) + ' ' + arguments, 'auto-switch'):
                return True
    except (ET.ParseError, ValueError):
        return False
    return False


def set_task(enabled):
    if enabled:
        import datetime
        import tempfile
        import xml.etree.ElementTree as ET
        ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
        ET.register_namespace('', ns)
        root = ET.Element('{' + ns + '}Task', version='1.2')
        def child(parent, name, text=None, **attrs):
            node = ET.SubElement(parent, '{' + ns + '}' + name, attrs)
            node.text = text
            return node
        trigger = child(child(root, 'Triggers'), 'CalendarTrigger')
        repetition = child(trigger, 'Repetition')
        child(repetition, 'Interval', 'PT2M')
        child(repetition, 'Duration', 'P1D')
        child(repetition, 'StopAtDurationEnd', 'false')
        child(trigger, 'StartBoundary', datetime.date.today().isoformat() + 'T00:00:00')
        child(trigger, 'Enabled', 'true')
        child(child(trigger, 'ScheduleByDay'), 'DaysInterval', '1')
        principal = child(child(root, 'Principals'), 'Principal', id='Author')
        child(principal, 'UserId', os.environ.get('USERDOMAIN', '.') + '\\' + os.environ['USERNAME'])
        child(principal, 'LogonType', 'InteractiveToken')
        child(principal, 'RunLevel', 'LeastPrivilege')
        settings = child(root, 'Settings')
        for name, value in [('MultipleInstancesPolicy','IgnoreNew'), ('DisallowStartIfOnBatteries','false'),
                            ('StopIfGoingOnBatteries','false'), ('StartWhenAvailable','true'),
                            ('AllowStartOnDemand','true'), ('Enabled','true'), ('ExecutionTimeLimit','PT5M')]:
            child(settings, name, value)
        action = child(child(root, 'Actions', Context='Author'), 'Exec')
        command = app_command('auto-switch')
        child(action, 'Command', command[0])
        child(action, 'Arguments', subprocess.list2cmdline(command[1:]))
        with tempfile.TemporaryDirectory(prefix='jmu-task-') as directory:
            path = Path(directory) / 'task.xml'
            ET.ElementTree(root).write(path, encoding='utf-16', xml_declaration=True)
            result = subprocess.run(['schtasks', '/Create', '/TN', TASK, '/XML', str(path), '/F'],
                                    capture_output=True, creationflags=NO_WINDOW, timeout=20)
    else:
        args = ['schtasks', '/Delete', '/TN', TASK, '/F']
        result = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, timeout=20)
    if result.returncode:
        raise RuntimeError('系统未能更新自动切换任务，请检查任务计划程序权限。')


def ensure_nic():
    return resolve_nic(force=True)


def run_minimal():
    from minimal_mode import authenticate_once
    from runtime_support import read_config
    from switch_notifications import notify_result
    root = None
    def settings_root():
        nonlocal root
        if root is None:
            root = tk.Tk()
            root.withdraw()
        return root
    try:
        if not ensure_npcap():
            notify_result('JMU 夜间联网', '缺少 Npcap，认证未启动。', warning=True)
            return
        if not CFG.exists() or not read_fields()[0]:
            if not configure(settings_root()):
                return
        conf = read_config(CFG)
        try:
            adapter = ensure_nic()
        except NicError:
            if not choose_dialog(settings_root()):
                return
            adapter = ensure_nic()
        authenticate_once(conf, adapter['device'])
    except Exception as exc:
        event('minimal', '启动检查未通过', level='ERROR', reason=str(exc))
        notify_result('JMU 夜间联网', '认证未启动：' + str(exc), warning=True)
    finally:
        if root is not None:
            root.destroy()


def main():
    import control
    root = tk.Tk()
    root.withdraw()
    event('launcher', '打开助手', executable=sys.executable, data_directory=str(BASE))
    nic_warning = ''
    try:
        if not ensure_npcap():
            root.destroy()
            return
        if not CFG.exists() or not read_fields()[0]:
            if not configure(root):
                root.destroy()
                return
        try:
            ensure_nic()
        except NicError as exc:
            nic_warning = str(exc)
    except Exception as exc:
        messagebox.showerror('启动检查未通过', str(exc), parent=root)
        root.destroy()
        return

    # Only one sharing-package authentication operation may run at a time.
    class PortableApp(control.App):
        def _connect_bypass(self):
            with instance_lock('authentication') as acquired:
                if acquired:
                    return super()._connect_bypass()
                self.root.after(0, lambda: self.tip.config(text='另一个认证操作正在运行，请稍后再试'))

        def _connect_normal(self, svc):
            with instance_lock('authentication') as acquired:
                if acquired:
                    return super()._connect_normal(svc)
                self.root.after(0, lambda: self.tip.config(text='另一个认证操作正在运行，请稍后再试'))

    app = PortableApp(root)
    app.head.config(wraplength=330, justify='left')
    app.body.config(wraplength=500)
    app.tip.config(wraplength=500, justify='left')
    if nic_warning:
        app.tip.config(text=nic_warning)
    menubar = tk.Menu(root)
    settings = tk.Menu(menubar, tearoff=False)
    def edit_settings():
        if configure(root):
            app.tip.config(text='设置已保存；当前连接尚未更改，点击“重新认证”后生效。')
    settings.add_command(label='账号与认证设置…', command=edit_settings)
    settings.add_command(label='认证网卡…', command=lambda: choose_dialog(root))
    boot = tk.BooleanVar(value=autostart_enabled())
    try:
        enabled = task_enabled()
    except (OSError, subprocess.TimeoutExpired):
        enabled = False
    periodic = tk.BooleanVar(value=enabled)

    def change(variable, action):
        try:
            action(variable.get())
            event('settings', '自动功能设置已更新', setting=action.__name__, enabled=variable.get())
            app.tip.config(text='自动功能设置已更新。')
        except Exception as exc:
            variable.set(not variable.get())
            event('settings', '自动功能设置失败', level='ERROR', reason=str(exc))
            messagebox.showerror('设置未生效', str(exc), parent=root)

    settings.add_checkbutton(label='登录 Windows 后自动认证', variable=boot,
                             command=lambda: change(boot, set_autostart))
    settings.add_checkbutton(label='自动切换（夜间／早间恢复）', variable=periodic,
                             command=lambda: change(periodic, set_task))
    from minimal_mode import enabled as minimal_enabled, set_enabled as save_minimal
    simple = tk.BooleanVar(value=minimal_enabled())
    def change_minimal():
        try:
            if simple.get():
                set_autostart(False)
                if task_enabled():
                    set_task(False)
                boot.set(False)
                periodic.set(False)
            save_minimal(simple.get())
            event('settings', '最简模式设置已更新', enabled=simple.get())
            if simple.get():
                app.alive = False
                root.destroy()
            else:
                app.tip.config(text='已恢复完整模式。自动功能可在设置中按需启用。')
        except Exception as exc:
            simple.set(not simple.get())
            app.tip.config(text='最简模式未能更新：' + str(exc))
    settings.add_separator()
    settings.add_checkbutton(label='最简模式（下次打开直接认证）', variable=simple, command=change_minimal)
    from runtime_log import debug_enabled, set_debug_logging
    detailed = tk.BooleanVar(value=debug_enabled())
    settings.add_checkbutton(label='详细日志（排障时启用）', variable=detailed,
                             command=lambda: change(detailed, set_debug_logging))
    settings.add_separator()
    settings.add_command(label='编辑节假日', command=lambda: os.startfile(str(BASE / 'holidays.txt')))
    settings.add_command(label='打开日志文件夹', command=lambda: os.startfile(str(BASE)))
    menubar.add_cascade(label='设置', menu=settings)
    root.config(menu=menubar)
    try:
        root.mainloop()
    finally:
        app.alive = False


def dispatch():
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        from portable_selftest import run
        run(Path(sys.argv[2]))
        return
    from minimal_mode import enabled as minimal_enabled, shift_requested
    if len(sys.argv) > 1 and sys.argv[1] in ('--startup-guard', '--auto-switch'):
        if minimal_enabled():
            event('launcher', '最简模式不执行后台任务', mode=sys.argv[1])
            return
        with instance_lock('authentication') as acquired:
            if not acquired:
                event('launcher', '后台任务跳过', reason='另一个认证或验证任务正在执行', mode=sys.argv[1])
                return
            if sys.argv[1] == '--startup-guard':
                import startup_guard
                raise SystemExit(startup_guard.ensure_connected())
            import auto_switch
            sys.argv = [sys.argv[0]]
            raise SystemExit(auto_switch.main())
    simple = ('--minimal' in sys.argv or minimal_enabled()) and '--full' not in sys.argv and not shift_requested()
    with instance_lock('ui') as acquired:
        if not acquired:
            if simple:
                from switch_notifications import notify_result
                notify_result('JMU 夜间联网', '已有窗口或认证操作正在运行，请稍后再试。', warning=True)
                return
            messagebox.showinfo('JMU 夜间联网', '助手已经打开，请查看已有窗口。')
            return
        run_minimal() if simple else main()


if __name__ == '__main__':
    try:
        dispatch()
    except SystemExit:
        raise
    except Exception:
        if '--self-test' in sys.argv:
            raise SystemExit(1)
        import traceback
        error = traceback.format_exc()
        event('launcher', '启动异常', level='ERROR', reason=error)
        messagebox.showerror('JMU 夜间联网启动失败', '程序未能完成启动，请查看“程序/runtime.log”。')
        raise SystemExit(1)
