from runtime_log import event
from runtime_support import read_config, probe_network, wait_check, auth_mode, stop_core, start_core, auth_state, wait_authentication, server_confirmed, server_status, read_auth_state, monitor_stability
from nic_manager import resolve_nic, NicError
from switch_notifications import record_switch, notify_night_failure, read_switch_status
# -*- coding: utf-8 -*-
"""Night switching plus at most four half-hour attempts to restore the carrier.

Ordinary daytime invocations exit before configuration, NIC or network queries.
Only the explicit recovery slots may touch an existing night connection.
"""
import argparse
import datetime
import os
import subprocess
import sys
import time
from office_ip_policy import check_office_ip
from schedule import is_blackout, should_prepare_bypass, should_run, is_carrier_recovery_time

from package_runtime import data_dir
BASE = str(data_dir())
CFG = os.path.join(BASE, "config.txt")
NIC = os.path.join(BASE, "nic.txt")
EXE = os.path.join(BASE, "jmusupplicant.exe")
LOG = os.path.join(BASE, "auto_switch.log")

PROBE = "http://connect.rom.miui.com/generate_204"
NO_WINDOW = 0x08000000

SVC_NAMES = {"0": "教育网", "1": "联通", "2": "移动", "3": "电信"}
HOLD_SEC = 60          # 切完后静置多久再确认
PORT_WAIT = 30         # 等端口开放的上限

def log(msg):
    event("scheduler", "自动切换事件", detail=msg)


def read_conf():
    return read_config(CFG)


def read_nic():
    return resolve_nic(force=True)["device"]


def ps(cmd, timeout=15):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def current_mode():
    return auth_mode()


def wired_ip():
    from nic_manager import wired_ip as shared_wired_ip
    return shared_wired_ip()


def kill_proc(wait=7):
    return stop_core(wait)


def start_proc(mode, conf, nic):
    selected = resolve_nic(force=True, preferred=nic)
    return start_core(mode, conf, selected["device"])


def link_up():
    from nic_manager import link_up as shared_link_up
    return shared_link_up()


def online(timeout=4, attempts=1):
    ip = wired_ip()
    return bool(ip) and probe_network(ip, timeout=timeout, component="scheduler")


def wait_online(max_sec=PORT_WAIT, step=4):
    state = read_auth_state()
    return wait_authentication(state.get("mode"), state.get("device"), max_sec, 1, component="scheduler")


def rollback_edu(conf, nic):
    """回退到教育网破解模式"""
    log("  [回] 回退教育网模式…")
    kill_proc()
    start_proc("bypass", conf, nic)
    ok, sec = wait_online(35)
    if ok:
        log("  [OK] 已回到教育网（%d 秒后恢复）" % sec)
    else:
        log("  [!!] 回退失败（%d 秒内没通）—— 需要人工处理" % sec)
    return ok


def switch_to(mode, conf, nic, *, stability=False):
    record_switch("PENDING", mode, "等待本次服务器回应与有线联网验证")
    kill_proc()
    start_proc(mode, conf, nic)
    ok, elapsed = wait_online(35)
    if ok and stability:
        ok = monitor_stability(mode, nic, HOLD_SEC, 2)
    auth_state(mode, nic, verified=ok)
    event("scheduler", "切换验证结果", mode=mode, verified=ok, elapsed=elapsed, server_status=server_status())
    if ok:
        record_switch("VERIFIED", mode, "本次认证的完整成功回应与有线联网均已确认", connected=True)
    else:
        record_switch("FAILED", mode, "未收到本次完整认证成功回应，或有线联网验证未通过", connected=online())
    return ok


def visit_carrier_portal(nic):
    """Request the local portal silently; its HTTP response is not auth proof."""
    adapter = resolve_nic(preferred=nic)
    if adapter['device'].casefold() != nic.casefold() or not adapter.get('ip'):
        raise NicError('所选有线网卡已改变或没有地址，停止本次运营商恢复。')
    try:
        result = subprocess.run(['curl.exe', '-sS', '--noproxy', '*', '--interface', adapter['ip'],
                                 '--connect-timeout', '2', '--max-time', '4', '-o', 'NUL',
                                 '-w', '%{http_code}', 'http://10.8.2.2/'],
                                capture_output=True, timeout=5, creationflags=NO_WINDOW)
        code = result.stdout.decode('ascii', errors='replace').strip()
        reached = result.returncode == 0 and code.isdigit() and 200 <= int(code) < 400
        event('carrier', '静默访问运营商入口', http_status=code, curl_exit=result.returncode,
              reached=reached, authentication_verified=False)
        return reached
    except (OSError, subprocess.TimeoutExpired) as exc:
        event('carrier', '访问运营商入口未完成', level='WARNING', reason=type(exc).__name__)
        return False


def recover_carrier(now):
    day = now.date().isoformat()
    slot = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0).isoformat(timespec='minutes')
    previous = read_switch_status()
    attempts = previous.get('carrier_recovery_attempts', 0) if previous.get('carrier_recovery_day') == day else 0
    attempts = attempts if isinstance(attempts, int) and attempts >= 0 else 0
    if (previous.get('carrier_recovered_day') == day or attempts >= 4 or
            previous.get('carrier_recovery_slot') == slot):
        event('carrier', '本轮不再尝试运营商恢复', attempts=attempts, day=day)
        return 0
    try:
        mode = current_mode()
        if mode == 'normal':
            event('carrier', '当前已使用运营商认证，保持原连接')
            return 0
        if mode != 'bypass' and read_auth_state().get('mode') != 'bypass':
            event('carrier', '没有需要恢复的夜间连接，保持现状')
            return 0
        # Persist the attempt before any portal/auth work: task restarts cannot
        # repeat a slot or reset the daily cap. Rollback is part of this attempt.
        record_switch('PENDING', 'normal', '静默尝试恢复运营商，等待本次认证及联网验证',
                      carrier_recovery_day=day, carrier_recovery_attempts=attempts + 1,
                      carrier_recovery_slot=slot)
        conf = read_conf()
        nic = read_nic()
        visit_carrier_portal(nic)
        if switch_to('normal', conf, nic):
            record_switch('VERIFIED', 'normal', '运营商认证与有线联网已确认，当天停止恢复尝试',
                          connected=True, carrier_recovered_day=day)
            return 0
        restored = switch_to('bypass', conf, nic)
        record_switch('FAILED', 'normal',
                      '运营商恢复未通过验证；已恢复夜间连接' if restored else '运营商恢复及夜间回退均未通过验证',
                      connected=restored, restored_mode='bypass' if restored else None)
        return 1
    except Exception as exc:
        event('carrier', '本次运营商恢复未完成', level='WARNING', reason=str(exc))
        record_switch('FAILED', 'normal', '运营商恢复未完成：' + str(exc), connected=False)
        return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-hold", action="store_true")
    args = ap.parse_args()
    now = datetime.datetime.now()
    night = is_blackout(now)
    prepare = should_prepare_bypass(now)
    # Daytime connectivity is managed by the existing session or an explicit
    # user action. A historical failure must never reopen automatic recovery.
    if not night and not prepare:
        if is_carrier_recovery_time(now):
            return recover_carrier(now)
        event("scheduler", "正常时段不执行自动联网检测或认证")
        return 0
    previous_switch = read_switch_status()
    recovery_due = previous_switch.get("status") == "FAILED" and previous_switch.get("connected") is False
    if not args.force and not should_run(now) and not recovery_due:
        event("scheduler", "本轮无需切换", reason="不在检查窗口")
        return 0
    try:
        conf = read_conf()
        nic = read_nic()
        mode = current_mode()
        healthy = online()
        accepted_bypass = server_confirmed("bypass", nic)
        event("scheduler", "切换决策", current_mode=mode, night=night, prepare=prepare,
              online=healthy, bypass_server_confirmed=accepted_bypass, service=conf["svc"])
        if night and healthy and accepted_bypass and not args.force:
            record_switch("VERIFIED", "bypass", "夜间认证已确认，有线当前可上网", connected=True)
            return 0
        if night and not accepted_bypass:
            notify_night_failure(now=now, connected=healthy, reason="已到限制时段，提前夜间认证仍未确认")
        if prepare and healthy and accepted_bypass and not args.force:
            return 0
        desired = "bypass"
        state = read_auth_state()
        age = max(0, time.time() - state.get("started", 0))
        same_attempt = state.get("mode") == desired and state.get("device") == nic
        # Give only a recent, real attempt a short chance to finish; stale processes
        # no longer impose an unconditional twenty-second wait on recovery.
        if same_attempt and age < 20 and server_status(state) in ("PENDING", "STAGE1_OK", "RETRYING"):
            if wait_online(15)[0]:
                record_switch("VERIFIED", desired, "正在进行的认证已完成验证", connected=True)
                return 0
        if same_attempt and age < 90 and not args.force and not state.get("verified"):
            event("scheduler", "暂缓重复认证", reason="距离上次尝试不足90秒", age=round(age, 1))
            return 1
        ok = switch_to(desired, conf, nic)
        if not ok:
            if prepare and mode == "normal" and not online():
                log("提前夜间认证失败且网络不可用，先恢复正常时段运营商连接")
                restored = switch_to("normal", conf, nic)
                record_switch("FAILED", "bypass",
                              "提前夜间认证未确认；已恢复运营商连接" if restored else "提前认证失败，恢复运营商也未通过验证",
                              connected=restored)
            if night:
                notify_night_failure(now=now, connected=online())
        return 0 if ok else 1
    except Exception as exc:
        event("scheduler", "自动切换失败", level="ERROR", reason=str(exc), error_type=type(exc).__name__)
        record_switch("FAILED", "bypass" if night or prepare else "normal", str(exc), connected=False)
        if night:
            notify_night_failure(now=now, connected=False, reason=str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
