"""Persist switch outcomes and request a native tray notification without stealing focus."""
import datetime
import json
from pathlib import Path
import subprocess
from package_runtime import data_dir
from runtime_log import event
from schedule import is_blackout, cutoff


def read_switch_status():
    try:
        value = json.loads((data_dir() / 'switch_status.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(value):
    path = data_dir() / 'switch_status.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def record_switch(status, mode, reason='', **fields):
    value = read_switch_status()
    value.update(status=status, mode=mode, reason=reason,
                 updated=datetime.datetime.now().isoformat(timespec='seconds'), **fields)
    if status == 'VERIFIED':
        value['problem_active'] = False
    _save(value)
    event('switch', '自动切换状态', status=status, mode=mode, reason=reason, **fields)


def notify_night_failure(*, now=None, connected=False, reason='本次夜间认证尚未确认成功'):
    now = now or datetime.datetime.now()
    if not is_blackout(now):
        return False
    evening = now.date() - datetime.timedelta(days=1) if now.hour < 6 else now.date()
    boundary = cutoff(evening)
    if boundary is None:
        return False
    key = boundary.isoformat()
    previous = read_switch_status()
    if previous.get('problem_active') and previous.get('notice_boundary') == key:
        return False
    message = ('已到夜间限制时段，夜间认证未确认成功。' +
               ('当前连接仍可上网，但不能据此确认切换成功。' if connected else '当前有线联网验证未通过。') +
               '助手会按计划重试，可打开JMU 夜间联网查看运行日志。')
    try:
        subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                          str(data_dir() / 'notify.ps1'), '-Title', 'JMU 夜间联网：夜间认证未确认',
                          '-Message', message], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=0x08000000)
        previous.update(problem_active=True, notice_boundary=key, notification_requested=now.isoformat(),
                        status='FAILED', reason=reason)
        _save(previous)
        event('notification', '已请求Windows右下角通知', boundary=key, connected=connected, reason=reason)
        return True
    except OSError as exc:
        event('notification', '无法请求系统通知', level='WARNING', error_type=type(exc).__name__)
        return False
