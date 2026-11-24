"""Stop this project's authenticators without changing Windows IP/DNS settings."""
from package_runtime import data_dir
from runtime_log import event
from runtime_support import stop_core
from switch_notifications import record_switch


def paused():
    return (data_dir() / 'network_paused.flag').exists()


def resume():
    (data_dir() / 'network_paused.flag').unlink(missing_ok=True)


def restore_default(disable_autostart, disable_tasks):
    (data_dir() / 'network_paused.flag').touch()
    errors = []
    stopped = False
    for label, action in [('关闭自启动', lambda: disable_autostart(False)),
                          ('关闭自动任务', disable_tasks),
                          ('停止认证进程', lambda: stop_core(wait=0, all_copies=True))]:
        try:
            action()
            if label == '停止认证进程':
                stopped = True
        except Exception as exc:
            errors.append(label + '失败：' + str(exc))
    if stopped:
        for name in ('auth_state.json', 'auth_state.tmp'):
            try:
                (data_dir() / name).unlink(missing_ok=True)
            except OSError as exc:
                errors.append('清理认证状态失败：' + str(exc))
    record_switch('RESTORE_INCOMPLETE' if errors else 'STOPPED', None,
                  '；'.join(errors) if errors else '本项目认证及自动功能已停止，请使用校园网正常认证入口',
                  connected=None, problem_active=False)
    event('restore', '停止并恢复默认网络处理完成', stopped=stopped, errors=errors)
    return errors
