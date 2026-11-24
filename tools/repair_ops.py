"""Offline, reversible updates for an already deployed portable helper."""
from pathlib import Path
import datetime
import os
import shutil
import uuid


def apply_update(root, payload):
    root, payload = Path(root).resolve(), Path(payload).resolve()
    data = root / '程序'
    if not (root / '校园网助手.exe').is_file() or not (data / 'jmusupplicant.exe').is_file():
        raise ValueError('请选择原“校园网助手.exe”所在文件夹，保持完整的“程序”目录。')
    files = [(payload / '校园网助手.exe', root / '校园网助手.exe'),
             (payload / 'getnic.ps1', data / 'getnic.ps1')]
    if any(not src.is_file() for src, dest in files):
        raise ValueError('修复程序缺少更新文件，请重新获取完整修复程序。')
    backup = data / '修复备份' / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    backup.mkdir(parents=True)
    originals = {}
    pending = []
    installed = []
    try:
        for src, dest in files:
            if dest.is_symlink():
                raise ValueError('目标文件为链接，请在正常解压目录运行修复。')
            if dest.exists():
                saved = backup / dest.name
                shutil.copy2(dest, saved)
                originals[dest] = saved
            temp = dest.with_name(dest.name + '.repair-' + uuid.uuid4().hex)
            pending.append(temp)
            shutil.copy2(src, temp)
        for (_, dest), temp in zip(files, pending):
            os.replace(temp, dest)
            installed.append(dest)
    except Exception:
        for dest in reversed(installed):
            if dest in originals:
                shutil.copy2(originals[dest], dest)
            else:
                dest.unlink(missing_ok=True)
        raise
    finally:
        for temp in pending:
            temp.unlink(missing_ok=True)
    # nic.txt is a machine-local preference, not an account setting. Keep a copy.
    if (data / 'nic.txt').exists():
        shutil.copy2(data / 'nic.txt', backup / 'nic.txt')
    return backup
