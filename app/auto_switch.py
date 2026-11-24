from runtime_log import event
from runtime_support import read_config, probe_network, wait_check, auth_mode, stop_core, start_core, auth_state, wait_authentication, server_confirmed, server_status, read_auth_state, monitor_stability
from nic_manager import resolve_nic, NicError
from switch_notifications import record_switch, notify_night_failure, read_switch_status
# -*- coding: utf-8 -*-
"""每小时尝试把「教育网破解模式」切成「运营商普通模式」。

策略（2026-10-31 用户要求）：
    · 每小时试一次（不是只在 6:00 试一次）
    · 切过去要**二次确认稳定**（静置 60 秒再测），避免「测完通、随后被收回」的假成功
    · 不稳定就**立刻回退教育网**，保证网络可用
    · 不做短间隔重试 —— 反复认证会触发学校风控

流程：
    1. 当前没在跑 / 已是运营商 → 退出
    2. 教育网当前通吗？不通就先拉起教育网（不在无网状态上做切换）
    3. 切运营商 → 等端口开 → 测通
    4. 静置 60 秒 → 再测一次
        · 两次都通 → 完成，保持运营商
        · 任一次不通 → 回退教育网 → 结束（等下一个小时）

用法：
    python auto_switch.py              正常（每小时由计划任务触发）
    python auto_switch.py --force      即使当前已是运营商也重切一次
    python auto_switch.py --no-hold    跳过 60 秒稳定性确认（快速调试）
"""
import argparse
import datetime
import os
import subprocess
import sys
import time
from office_ip_policy import check_office_ip
from schedule import is_blackout, should_prepare_bypass, should_run

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-hold", action="store_true")
    args = ap.parse_args()
    now = datetime.datetime.now()
    previous_switch = read_switch_status()
    recovery_due = previous_switch.get("status") == "FAILED" and previous_switch.get("connected") is False
    if not args.force and not should_run(now) and not recovery_due:
        event("scheduler", "本轮无需切换", reason="不在检查窗口")
        return 0
    night = is_blackout(now)
    prepare = should_prepare_bypass(now)
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
        if not night and not prepare and healthy and not args.force:
            if mode != "bypass" or now.hour >= 22:
                if recovery_due:
                    record_switch("CONNECTED", mode, "有线联网已恢复，未重新认证", connected=True)
                return 0
        if prepare and healthy and accepted_bypass and not args.force:
            return 0
        desired = "bypass" if night or prepare else "normal"
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
        ok = switch_to(desired, conf, nic, stability=desired == "normal" and not args.no_hold)
        if not ok:
            if desired == "normal":
                log("运营商验证失败，立即回退夜间方案")
                restored = switch_to("bypass", conf, nic)
                record_switch("FAILED", desired,
                              "运营商切换失败；已回退并验证联网" if restored else "运营商切换及回退均未通过验证",
                              connected=restored, restored_mode="bypass" if restored else None)
            elif prepare and mode == "normal" and not online():
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
