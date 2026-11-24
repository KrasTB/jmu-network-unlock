from runtime_log import event
from runtime_support import read_config, probe_network, wait_check, auth_mode, stop_core, start_core, auth_state
from nic_manager import resolve_nic, NicError
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
    return wait_check(online, max_sec, step, component="scheduler")


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-hold", action="store_true")
    args = ap.parse_args()
    now = datetime.datetime.now()
    if not args.force and not should_run(now):
        event("scheduler", "本轮无需切换", reason="不在检查窗口")
        return 0
    try:
        conf = read_conf()
        nic = read_nic()
        mode = current_mode()
        night = is_blackout(now)
        prepare = should_prepare_bypass(now)
        healthy = online()
        event("scheduler", "切换决策", current_mode=mode, night=night, prepare=prepare,
              online=healthy, service=conf["svc"], forced=args.force)
        if night and healthy and not args.force:
            log("夜间有线网络可用，保持现状")
            return 0
        if not night and not prepare and healthy and not args.force:
            if mode != "bypass" or now.hour >= 22:
                log("当前网络可用，保持现状")
                return 0
        if prepare and healthy and mode == "bypass" and not args.force:
            log("已提前进入绕过模式，保持现状")
            return 0
        if not healthy and mode is not None:
            log("有认证状态但网络未通，进行有上限的等待")
            if wait_online(20)[0]:
                log("等待后已恢复，本轮保持现状")
                return 0
            log("等待结束仍不通，重新认证")
        desired = "bypass" if night or prepare else "normal"
        kill_proc()
        start_proc(desired, conf, nic)
        ok, elapsed = wait_online(35)
        auth_state(desired, nic, verified=ok)
        event("scheduler", "切换验证结果", mode=desired, verified=ok, elapsed=elapsed)
        if ok and desired == "normal" and not args.no_hold:
            log("首次联网通过，静置后确认稳定性")
            time.sleep(HOLD_SEC)
            ok = online()
            auth_state(desired, nic, verified=ok)
            event("scheduler", "稳定性复核", verified=ok, hold_seconds=HOLD_SEC)
        if not ok and desired == "normal":
            log("运营商验证失败，回退绕过模式")
            restored = rollback_edu(conf, nic)
            auth_state("bypass", nic, verified=restored)
            event("scheduler", "回退结果", restored=restored)
        return 0 if ok else 1
    except Exception as exc:
        event("scheduler", "自动切换失败", level="ERROR", reason=str(exc), error_type=type(exc).__name__)
        return 2


if __name__ == "__main__":
    sys.exit(main())
