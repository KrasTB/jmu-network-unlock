"""One physical wired adapter for authentication and bound connectivity checks."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from package_runtime import data_dir
from runtime_log import event


class NicError(RuntimeError):
    pass


_cache = None
_cache_at = 0.0
_cache_base = None
_lock = threading.RLock()


def inventory(base=None):
    base = Path(base) if base is not None else data_dir()
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(base / 'getnic.ps1'), '-Inventory'],
                                capture_output=True, timeout=25, creationflags=0x08000000)
        if result.returncode:
            raise NicError('无法读取系统网卡，请检查 Windows 网络服务。')
        info = json.loads(result.stdout.decode('utf-8-sig'))
        if not isinstance(info, dict) or not isinstance(info.get('adapters'), list):
            raise ValueError('Invalid adapter inventory')
        return info
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise NicError('读取网卡失败，请稍后重试；仍失败时查看系统网络服务。') from exc


def capture_devices():
    # Enumeration only: no packet capture, authentication, or driver changes.
    folder = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'Npcap'
    class PcapIf(ctypes.Structure):
        pass
    PcapIf._fields_ = [('next', ctypes.POINTER(PcapIf)), ('name', ctypes.c_char_p),
                      ('description', ctypes.c_char_p), ('addresses', ctypes.c_void_p), ('flags', ctypes.c_uint)]
    try:
        with os.add_dll_directory(str(folder)):
            lib = ctypes.CDLL(str(folder / 'wpcap.dll'))
            lib.pcap_findalldevs.argtypes = [ctypes.POINTER(ctypes.POINTER(PcapIf)), ctypes.c_char_p]
            lib.pcap_findalldevs.restype = ctypes.c_int
            lib.pcap_freealldevs.argtypes = [ctypes.POINTER(PcapIf)]
            head = ctypes.POINTER(PcapIf)()
            error = ctypes.create_string_buffer(256)
            if lib.pcap_findalldevs(ctypes.byref(head), error) != 0:
                raise NicError('Npcap 无法枚举网卡，请检查驱动服务和访问权限。')
            names = set()
            try:
                node = head
                while node:
                    if node.contents.name:
                        names.add(node.contents.name.decode('ascii'))
                    node = node.contents.next
            finally:
                lib.pcap_freealldevs(head)
            return names
    except OSError as exc:
        raise NicError('Npcap 未就绪，请检查驱动安装和访问权限。') from exc


def select_adapter(adapters, preferred=''):
    candidates = [a for a in adapters if a.get('wired') is True and a.get('status') == 'Up']
    manual = [a for a in adapters if a.get('selectable', a.get('wired')) is True and a.get('status') == 'Up']
    for adapter in manual:
        if adapter['device'].casefold() == preferred.casefold():
            return adapter
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise NicError('多块有线网卡已连接，请在“设置 → 认证网卡”选择校园网对应的网卡。')
    if manual:
        raise NicError('检测到连接中的网卡，但驱动未明确报告有线类型。请在“设置 → 认证网卡”手动选择 USB 网卡。')
    if any(not a.get('wired') and a.get('status') == 'Up' for a in adapters):
        raise NicError('当前只有 Wi-Fi 等非有线连接可用。请接好校园网网线；本助手不能通过 Wi-Fi 完成此有线认证。')
    raise NicError('没有已连接的物理有线网卡，请插好网线；使用转接器时请确认已识别。')


def resolve_nic(*, base=None, force=False, preferred=None):
    global _cache, _cache_at, _cache_base
    base = Path(base) if base is not None else data_dir()
    with _lock:
        if not force and preferred is None and _cache is not None and _cache_base == base and time.monotonic() - _cache_at < 3:
            return dict(_cache)
        _cache = None
        info = inventory(base)
        explicit = preferred is not None
        if preferred is None:
            try:
                preferred = (base / 'nic.txt').read_text(encoding='utf-8-sig').strip()
            except OSError:
                preferred = ''
        devices = {s.casefold() for s in capture_devices()}
        for item in info['adapters']:
            event('nic', '网卡候选检查', base=base, interface=item['name'], device=item['device'],
                  status=item.get('status'), wired=item.get('wired'), selectable=item.get('selectable'),
                  visible_to_npcap=item['device'].casefold() in devices)
        visible = [a for a in info['adapters'] if a['device'].casefold() in devices]
        if not any(a.get('selectable', a.get('wired')) and a.get('status') == 'Up' for a in visible):
            # Preserve the distinction between absent Ethernet and absent capture access.
            select_adapter(info['adapters'], preferred)
            raise NicError('已识别有线网卡，但 Npcap 未提供该设备。请检查驱动服务、安装选项和访问权限。')
        adapter = dict(select_adapter(visible, preferred))
        if explicit and adapter['device'].casefold() != preferred.casefold():
            raise NicError('所选网卡已断开，请刷新后重新选择。')
        path = base / 'nic.txt'
        if not path.exists() or path.read_text(encoding='utf-8-sig').strip() != adapter['device']:
            temp = path.with_suffix('.tmp')
            temp.write_text(adapter['device'] + '\n', encoding='ascii')
            os.replace(temp, path)
            event('nic', '已保存网卡选择', base=base, interface=adapter['name'], device=adapter['device'],
                  reason='手动指定' if explicit else '自动识别或恢复有效选择')
        event('nic', '认证网卡已确认', base=base, interface=adapter['name'], device=adapter['device'],
              source=adapter.get('ip'), route=info.get('default_alias'))
        adapter.update(default_alias=info.get('default_alias', ''), supp=info.get('supp', ''))
        _cache, _cache_at, _cache_base = adapter, time.monotonic(), base
        return dict(adapter)


def wired_ip():
    try:
        return resolve_nic().get('ip', '')
    except (NicError, OSError):
        return ''


def link_up():
    try:
        return resolve_nic()['status'] == 'Up'
    except (NicError, OSError):
        return False


def collect():
    try:
        adapter = resolve_nic()
        return {'STATUS': adapter['status'], 'IP': adapter.get('ip', ''),
                'IFACE': adapter.get('default_alias', ''), 'SUPP': adapter.get('supp', ''),
                'NIC_NAME': adapter['name']}
    except (NicError, OSError) as exc:
        return {'STATUS': 'Down', 'IP': '', 'IFACE': '', 'SUPP': '', 'NIC_ERROR': str(exc)}


def choose_dialog(parent, base=None):
    import tkinter as tk
    from tkinter import ttk
    import queue
    base = Path(base) if base is not None else data_dir()
    window = tk.Toplevel(parent)
    window.title('认证网卡')
    window.transient(parent)
    window.resizable(False, False)
    status = tk.StringVar(value='正在读取本机网卡…')
    ttk.Label(window, textvariable=status, wraplength=540).pack(padx=18, pady=12)
    picker = ttk.Combobox(window, state='readonly', width=72)
    picker.pack(padx=18, pady=8)
    entries = []
    events = queue.Queue()
    chosen = [False]

    def scan():
        save_button.config(state='disabled')
        refresh_button.config(state='disabled')
        status.set('正在对照 Windows 与 Npcap 网卡列表…')
        def work():
            try:
                info = inventory(base)
                ready = [a for a in info['adapters'] if a.get('selectable', a.get('wired')) and a['status'] == 'Up']
                devices = {s.casefold() for s in capture_devices()}
                ready = [a for a in ready if a['device'].casefold() in devices]
                if not ready:
                    select_adapter(info['adapters'])
                    raise NicError('已连接有线网卡，但 Npcap 未提供该设备，请检查驱动和访问权限。')
                events.put((ready, '请选择连接校园网的有线网卡，保存后再点击重新认证。'))
            except Exception as exc:
                events.put(([], str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll():
        try:
            ready, message = events.get_nowait()
        except queue.Empty:
            window.after(100, poll)
            return
        if ready == 'saved':
            chosen[0] = True
            window.destroy()
            return
        entries[:] = ready
        picker['values'] = [a['name'] + ' — ' + a.get('description', '') + ' — ' + (a.get('ip') or '尚未取得 IPv4') for a in ready]
        if ready:
            picker.current(0)
        status.set(message)
        save_button.config(state='normal' if ready else 'disabled')
        refresh_button.config(state='normal')
        window.after(100, poll)

    def save():
        index = picker.current()
        if index < 0 or index >= len(entries):
            return
        # Query again so unplugging a device while this dialog is open cannot save it.
        selected = entries[index]['device']
        save_button.config(state='disabled')
        refresh_button.config(state='disabled')
        def work():
            try:
                adapter = resolve_nic(base=base, force=True, preferred=selected)
                if adapter['device'].casefold() != selected.casefold():
                    raise NicError('所选网卡已断开，请刷新后重新选择。')
                events.put(('saved', ''))
            except Exception as exc:
                events.put(([], str(exc)))
        threading.Thread(target=work, daemon=True).start()

    buttons = ttk.Frame(window)
    buttons.pack(pady=14)
    refresh_button = ttk.Button(buttons, text='刷新', command=scan)
    refresh_button.pack(side='left', padx=8)
    save_button = ttk.Button(buttons, text='使用所选网卡', command=save)
    save_button.pack(side='left', padx=8)
    scan()
    window.after(100, poll)
    parent.wait_window(window)
    return chosen[0]
