"""Send this single executable to repair an existing portable deployment."""
from pathlib import Path
import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from repair_ops import apply_update
from nic_manager import resolve_nic, choose_dialog


def main():
    root = tk.Tk()
    root.title('校园网助手 · 网卡修复（USB 兼容版）')
    root.resizable(False, False)
    target = tk.StringVar()
    status = tk.StringVar(value='先关闭原助手窗口，再选择已部署的“校园网助手.exe”。\n保留账号和认证设置；更新前自动备份。')
    ttk.Label(root, textvariable=status, wraplength=560, justify='left').pack(padx=20, pady=16)
    row = ttk.Frame(root)
    row.pack(padx=20, pady=6)
    ttk.Entry(row, textvariable=target, width=64, state='readonly').pack(side='left')
    def browse():
        file = filedialog.askopenfilename(parent=root, title='选择原校园网助手',
                                         filetypes=[('校园网助手', '校园网助手.exe')])
        if file:
            target.set(str(Path(file).parent))
    browse_button = ttk.Button(row, text='选择…', command=browse)
    browse_button.pack(side='left', padx=8)
    actions = ttk.Frame(root)
    actions.pack(pady=16)
    events = queue.Queue()
    def repair():
        if not target.get():
            messagebox.showinfo('选择原程序', '请先选择已部署的校园网助手。', parent=root)
            return
        location = Path(target.get())
        repair_button.config(state='disabled')
        browse_button.config(state='disabled')
        nic_button.config(state='disabled')
        open_button.config(state='disabled')
        status.set('正在备份、更新并检查本机网卡，请稍候…')
        def work():
            try:
                payload = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'payload'
                backup = apply_update(location, payload)
                try:
                    adapter = resolve_nic(base=location / '程序', force=True)
                    message = '修复完成。已选择：' + adapter['name'] + '。\n请打开原助手并点击“重新认证”。'
                except Exception as exc:
                    message = '程序文件已更新。网卡检查：\n' + str(exc) + '\n接好网线后可点“检查 / 选择网卡”。'
                events.put((True, message + '\n备份：' + str(backup)))
            except PermissionError:
                events.put((False, '无法更新文件。请关闭原助手窗口及其他正在使用它的修复程序后重试；若目录受保护，请以管理员身份运行修复。'))
            except Exception as exc:
                events.put((False, '修复未完成：' + str(exc)))
        threading.Thread(target=work, daemon=True).start()
    def poll():
        try:
            success, message = events.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        status.set(message)
        repair_button.config(state='normal')
        browse_button.config(state='normal')
        if success:
            nic_button.config(state='normal')
            open_button.config(state='normal')
        root.after(100, poll)
    def open_app():
        location = Path(target.get())
        subprocess.Popen([str(location / '校园网助手.exe')], cwd=location, creationflags=0x08000000)
    repair_button = ttk.Button(actions, text='修复', command=repair)
    repair_button.pack(side='left', padx=8)
    nic_button = ttk.Button(actions, text='检查 / 选择网卡', state='disabled',
                            command=lambda: choose_dialog(root, Path(target.get()) / '程序'))
    nic_button.pack(side='left', padx=8)
    open_button = ttk.Button(actions, text='打开原助手', command=open_app, state='disabled')
    open_button.pack(side='left', padx=8)
    root.after(100, poll)
    root.mainloop()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from test_repair import run_checks
        result = run_checks(Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'payload')
        Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        raise SystemExit(0 if result['ok'] else 1)
    main()
