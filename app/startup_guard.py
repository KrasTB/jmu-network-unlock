from runtime_log import event
from runtime_support import read_config, probe_network, wait_check, process_info, stop_core, auth_state, wait_authentication, read_auth_state
from nic_manager import resolve_nic, NicError
# -*- coding: utf-8 -*-
"""Logon-time authentication and wired-connectivity guard."""
import os
import subprocess
import time
from office_ip_policy import check_office_ip

from package_runtime import data_dir
BASE = str(data_dir())
EXE = os.path.join(BASE, "jmusupplicant.exe")
LOG = os.path.join(BASE, "startup_guard.log")
STATUS = os.path.join(BASE, "startup_status.txt")
NO_WINDOW = 0x08000000
MAX_ATTEMPTS = 3


def log(message):
    event("startup", "开机认证事件", detail=message)


def write_status(state, message, attempt=0):
    """Publish a small human-readable status file for the GUI."""
    temp = STATUS + ".tmp"
    text = "state=%s\nmessage=%s\nattempt=%d\ntime=%s\n" % (
        state, message, attempt, time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        with open(temp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temp, STATUS)
    except OSError:
        pass


def ps(command, timeout=15):
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            creationflags=NO_WINDOW,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def wired_ip():
    from nic_manager import wired_ip as shared_wired_ip
    return shared_wired_ip()


def link_up():
    try:
        return resolve_nic(force=True)["status"] == "Up"
    except (NicError, OSError) as exc:
        log(str(exc))
        write_status("WAITING", str(exc))
        return False


def online():
    ip = wired_ip()
    return bool(ip) and probe_network(ip, component="startup")


def auth_running():
    return bool(process_info())


def start_auth():
    from auto_switch import read_conf, read_nic, start_proc
    from schedule import is_blackout, should_prepare_bypass
    conf = read_conf()
    mode = "bypass" if is_blackout() or should_prepare_bypass() else "normal"
    start_proc(mode, conf, read_nic())
    return mode


def stop_auth():
    return stop_core()


def wait_online(timeout=40, interval=4):
    state = read_auth_state()
    return wait_authentication(state.get('mode'), state.get('device'), timeout, 1, component='startup')[0]


def ensure_connected():
    log("开机认证开始")
    try:
        read_config(os.path.join(BASE, "config.txt"))
    except (OSError, ValueError) as exc:
        write_status("FAILED", str(exc))
        event("startup", "配置检查失败", level="ERROR", reason=str(exc))
        return 2
    write_status("WAITING", "等待有线网卡")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            event("startup", "开始检查", attempt=attempt, max_attempts=MAX_ATTEMPTS)
            if not link_up():
                time.sleep(min(30, 10 * attempt))
                continue
            if online():
                write_status("VERIFIED", "有线网络已确认可用", attempt)
                return 0
            if auth_running():
                write_status("VERIFYING", "认证进程运行中，限时等待联网验证", attempt)
                if wait_online():
                    from runtime_support import auth_mode
                    auth_state(auth_mode(), verified=True)
                    write_status("VERIFIED", "有线网络已确认可用", attempt)
                    return 0
            stop_auth()
            write_status("AUTHENTICATING", "正在认证并验证有线网络", attempt)
            mode = start_auth()
            if wait_online():
                auth_state(mode, verified=True)
                write_status("VERIFIED", "认证成功，有线网络已确认可用", attempt)
                return 0
            write_status("RETRYING", "联网验证未通过，准备重试", attempt)
        except Exception as exc:
            event("startup", "本次开机认证失败", level="ERROR", attempt=attempt,
                  reason=str(exc), error_type=type(exc).__name__)
            write_status("RETRYING", "认证遇到错误，请查看运行日志", attempt)
        if attempt < MAX_ATTEMPTS:
            time.sleep(15 * attempt)
    write_status("FAILED", "未能确认有线联网，请查看 runtime.log", MAX_ATTEMPTS)
    log("开机认证达到重试上限，已停止重试")
    return 1


if __name__ == "__main__":
    raise SystemExit(ensure_connected())
