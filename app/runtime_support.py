"""Validated settings, real-time waits, scoped process control and strict HTTP probes."""
import ipaddress
import ctypes
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time
from office_ip_policy import check_office_ip
from package_runtime import data_dir
from runtime_log import event

NO_WINDOW = 0x08000000
PROBES = ('http://connect.rom.miui.com/generate_204',
          'http://connectivitycheck.platform.hicloud.com/generate_204')


def read_config(path):
    try:
        fields = Path(path).read_text(encoding='utf-8-sig').split()
    except OSError:
        event('config', '读取配置失败', level='ERROR')
        raise ValueError('无法读取账号配置，请打开设置重新保存。') from None
    if len(fields) != 5:
        raise ValueError('配置必须包含完整的五项，请打开设置重新保存。')
    user, password, address, mask, service = fields
    if not user or not password or '"' in user + password or user == '202500000000' or password == 'yourpassword':
        raise ValueError('账号配置无效，请填写自己的账号密码。')
    check_office_ip(address)
    ipaddress.IPv4Network('0.0.0.0/' + mask)
    if service not in ('0', '1', '2', '3'):
        raise ValueError('运营商设置无效，请重新选择。')
    event('config', '配置校验通过', office_ip=address, mask=mask, service=service)
    return dict(user=user, pwd=password, oip=address, omask=mask, svc=service)


def probe_network(src_ip=None, *, timeout=6, component='network'):
    started = time.monotonic()
    deadline = started + max(0, timeout)
    for url in PROBES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        per_probe = min(3.0, remaining)
        args = ['curl.exe', '-sS', '--noproxy', '*', '--connect-timeout', str(min(2, per_probe)),
                '--max-time', str(per_probe), '-o', 'NUL', '-w', '%{http_code}']
        if src_ip:
            args += ['--interface', src_ip]
        try:
            result = subprocess.run(args + [url], capture_output=True,
                                    timeout=per_probe + 0.2, creationflags=NO_WINDOW)
            code = result.stdout.decode('ascii', errors='replace').strip()
            ok = result.returncode == 0 and code == '204'
            event(component, '联网检测', source=src_ip or '系统默认出口', url=url,
                  curl_exit=result.returncode, http_status=code, online=ok,
                  elapsed=round(time.monotonic() - started, 3))
            if ok:
                return True
        except (OSError, subprocess.TimeoutExpired) as exc:
            event(component, '联网检测失败', level='WARNING', source=src_ip or '系统默认出口',
                  url=url, reason=type(exc).__name__, elapsed=round(time.monotonic() - started, 3))
    return False


def wait_check(probe, timeout=40, interval=2, *, component='authentication'):
    # interval=0 retains the explicit offline, attempt-count API used by legacy tests.
    if interval == 0:
        for attempt in range(1, max(1, int(timeout)) + 1):
            if probe():
                return True, attempt
        return False, timeout
    started = time.monotonic()
    deadline = started + max(0, timeout)
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        if probe():
            elapsed = math.ceil(time.monotonic() - started)
            event(component, '联网验证完成', verified=True, attempts=attempts, elapsed=elapsed)
            return True, elapsed
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))
    elapsed = math.ceil(time.monotonic() - started)
    event(component, '联网验证超时', level='WARNING', verified=False, attempts=attempts,
          elapsed=elapsed, requested_timeout=timeout)
    return False, elapsed


def process_info():
    exe = str(data_dir() / 'jmusupplicant.exe').replace("'", "''")
    script = ("$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false);"
              "$items=@(Get-CimInstance Win32_Process -Filter \"Name='jmusupplicant.exe'\" | "
              "Where-Object {$_.ExecutablePath -eq '" + exe + "'} | ForEach-Object {"
              "[pscustomobject]@{pid=$_.ProcessId;mode=$(if($_.CommandLine -match '(^|\\s)-n(\\s|$)'){'bypass'}else{'normal'})}});"
              "ConvertTo-Json -InputObject $items -Compress")
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                                capture_output=True, timeout=12, creationflags=NO_WINDOW)
        if result.returncode:
            raise OSError('Process enumeration failed')
        records = json.loads(result.stdout.decode('utf-8-sig'))
        if not isinstance(records, list):
            raise ValueError('Invalid process list')
        return records
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        event('process', '认证进程检查失败', level='WARNING', reason=type(exc).__name__)
        # Do not start a second instance if process ownership could not be checked.
        raise RuntimeError('无法确认本程序的认证进程，请检查系统进程查询权限。') from None


def auth_mode():
    records = process_info()
    if records:
        return records[0]['mode']
    state = read_auth_state()
    if state.get('verified') and abs(state.get('boot', 0) - boot_epoch()) < 5:
        try:
            device = (data_dir() / 'nic.txt').read_text(encoding='utf-8-sig').strip()
            if device.casefold() == state.get('device', '').casefold():
                return state.get('mode')
        except OSError:
            pass
    return None


def boot_epoch():
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetTickCount64.restype = ctypes.c_ulonglong
    return int(time.time() - kernel.GetTickCount64() / 1000)


def read_auth_state():
    try:
        state = json.loads((data_dir() / 'auth_state.json').read_text(encoding='utf-8'))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def auth_state(mode, device=None, *, verified=False):
    previous = read_auth_state()
    state = dict(mode=mode, device=device or previous.get('device', ''), verified=verified,
                 boot=boot_epoch(), time=time.time())
    try:
        temp = data_dir() / 'auth_state.tmp'
        temp.write_text(json.dumps(state), encoding='utf-8')
        os.replace(temp, data_dir() / 'auth_state.json')
    except OSError as exc:
        event('authentication', '保存认证状态失败', level='WARNING', reason=type(exc).__name__)


def stop_core(wait=7):
    records = process_info()
    for record in records:
        result = subprocess.run(['taskkill.exe', '/F', '/PID', str(int(record['pid']))],
                                capture_output=True, timeout=12, creationflags=NO_WINDOW)
        event('authentication', '停止本目录认证进程', pid_target=record['pid'], exit_code=result.returncode)
        if result.returncode:
            raise RuntimeError('无法停止原认证进程，请关闭后重试。')
    time.sleep(wait)


def start_core(mode, conf, nic):
    exe = str(data_dir() / 'jmusupplicant.exe')
    args = [exe, '-u', conf['user'], '-p', conf['pwd'], '-s', '0' if mode == 'bypass' else conf['svc'],
            '--interface_card', nic]
    if mode == 'bypass':
        args += ['-n', '--ip', conf['oip'], '--mask', conf['omask']]
    environment = os.environ.copy()
    environment['JMU_MIDNIGHT_SERVICE'] = conf['svc']
    started = time.monotonic()
    auth_state(mode, nic, verified=False)
    event('authentication', '启动认证', mode=mode, service=conf['svc'], device=nic,
          office_ip=conf['oip'] if mode == 'bypass' else None)
    try:
        proc = subprocess.Popen(args, cwd=str(data_dir()), env=environment,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except OSError as exc:
        event('authentication', '启动认证失败', level='ERROR', reason=type(exc).__name__,
              winerror=getattr(exc, 'winerror', None))
        raise RuntimeError('认证程序未能启动，请检查程序文件和访问权限。') from None
    event('authentication', '认证进程已启动', pid_target=proc.pid, mode=mode)
    def monitor():
        code = proc.wait()
        event('authentication', '认证进程退出', level='INFO' if code == 0 else 'WARNING',
              pid_target=proc.pid, exit_code=code, mode=mode,
              elapsed=round(time.monotonic() - started, 3))
    threading.Thread(target=monitor, name='auth-exit-monitor', daemon=True).start()
    return proc


def manual_auth(app, mode, service=None):
    from nic_manager import resolve_nic, wired_ip
    if not app.auth_lock.acquire(blocking=False):
        app.root.after(0, lambda: app.tip.config(text='已有认证操作进行中，请稍候'))
        event('manual', '认证被跳过', reason='已有认证操作')
        return
    started = time.monotonic()
    app._auth_phase = '检查配置和网卡'
    try:
        conf = read_config(data_dir() / 'config.txt')
        if service is not None:
            conf['svc'] = service
        adapter = resolve_nic(force=True)
        event('manual', '手动认证开始', mode=mode, device=adapter['device'], interface=adapter['name'])
        app._auth_phase = '释放旧认证进程'
        stop_core()
        app._auth_phase = '启动认证并验证联网'
        start_core(mode, conf, adapter['device'])
        def bound_probe():
            ip = wired_ip()
            return bool(ip) and probe_network(ip, component='manual')
        ok, elapsed = wait_check(bound_probe, component='manual')
        auth_state(mode, adapter['device'], verified=ok)
        text = ('认证成功，有线网络已验证可用（%d 秒）' if ok else
                '未确认认证成功：有线联网验证失败（实际检测 %d 秒），请查看日志') % elapsed
        app.root.after(0, lambda text=text: app.tip.config(text=text))
        event('manual', '手动认证结束', verified=ok, mode=mode,
              total_elapsed=round(time.monotonic() - started, 3))
    except Exception as exc:
        text = '认证未完成：' + str(exc)
        event('manual', '手动认证异常', level='ERROR', reason=str(exc), error_type=type(exc).__name__)
        app.root.after(0, lambda text=text: app.tip.config(text=text))
    finally:
        app._auth_phase = ''
        app.auth_lock.release()
