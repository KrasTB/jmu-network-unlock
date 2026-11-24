"""One manual authentication attempt, without a dashboard or background loop."""
import ctypes
import json
from package_runtime import data_dir, instance_lock
from runtime_log import event
from runtime_support import probe_device, stop_core, start_core, wait_authentication
from schedule import is_blackout, should_prepare_bypass
from switch_notifications import notify_result


def enabled():
    try:
        value = json.loads((data_dir() / 'minimal_mode.json').read_text(encoding='utf-8'))
        return isinstance(value, dict) and value.get('enabled') is True
    except (OSError, ValueError):
        return False


def set_enabled(value):
    path = data_dir() / 'minimal_mode.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'enabled': bool(value)}), encoding='utf-8')
    temporary.replace(path)


def shift_requested():
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
    except (OSError, AttributeError):
        return False


def authenticate_once(conf, nic):
    try:
        with instance_lock('authentication') as acquired:
            if not acquired:
                notify_result('JMU 夜间联网', '已有认证任务进行中，请稍后再试。', warning=True)
                return 1
            if probe_device(nic, timeout=4, component='minimal'):
                notify_result('JMU 夜间联网', '有线联网已验证可用，无需重新认证。')
                return 0
            mode = 'bypass' if is_blackout() or should_prepare_bypass() else 'normal'
            event('minimal', '开始单次手动认证', mode=mode)
            stop_core()
            start_core(mode, conf, nic)
            ok, elapsed = wait_authentication(mode, nic, timeout=40, component='minimal')
            message = ('认证成功，有线联网已验证（%d 秒）。' if ok else
                       '未确认认证成功（%d 秒），请按住 Shift 双击程序查看完整界面和日志。') % elapsed
            notify_result('JMU 夜间联网', message, warning=not ok)
            return 0 if ok else 1
    except Exception as exc:
        event('minimal', '单次认证未完成', level='ERROR', reason=str(exc))
        notify_result('JMU 夜间联网', '认证未完成：' + str(exc), warning=True)
        return 2
