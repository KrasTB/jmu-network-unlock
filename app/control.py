from runtime_log import event
from runtime_support import read_config, probe_network, wait_check, auth_mode, process_info, stop_core, manual_auth
from nic_manager import resolve_nic, NicError
# -*- coding: utf-8 -*-
"""JMU 夜间联网（重写版 2）

一个窗口管三件事：连接 / 状态 / 断开。

两条铁律：
  1. 这个程序本身**从不主动断开网络** —— 启动它不杀任何进程、不重启认证，
     只有你点「断开」才会停服务，点「连接」「重新认证」才会启动认证。
  2. 状态检查全部放在后台线程里做，界面绝不阻塞。之前窗口一闪就没，就是因为
     建完窗口立刻在同一线程里连跑好几次 PowerShell，事件循环根本没机会跑起来。

布局用 pack，不用 place。
"""
import datetime
import os
import socket
import subprocess
import sys
import threading
import time
from office_ip_policy import check_office_ip
import tkinter as tk
from tkinter import messagebox
from schedule import is_blackout, should_prepare_bypass

from package_runtime import data_dir
BASE = str(data_dir())
sys.path.insert(0, BASE)
EXE = os.path.join(BASE, "jmusupplicant.exe")
CFG = os.path.join(BASE, "config.txt")
NICF = os.path.join(BASE, "nic.txt")
LOG = os.path.join(BASE, "runtime.log")   # 「日志」按钮打开的就是它
STARTUP_STATUS = os.path.join(BASE, "startup_status.txt")
ERR = os.path.join(BASE, "control_error.log")

NO_WINDOW = 0x08000000
AUTH_WAIT = 40
AUTH_POLL = 2
C_OK, C_BAD, C_WARN, C_IDLE = "#1e9e4a", "#c0392b", "#d68910", "#7f8c8d"
BG = "#f5f6f7"


def logerr(msg):
    event("ui", "界面事件", detail=msg)


def sh(args, timeout=8):
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        return (r.stdout or b"").decode("gbk", "replace")
    except Exception:
        return ""


def kill_and_wait(wait=7):
    return stop_core(wait)


def pyw():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        cand = exe[:-10] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    return exe


# ---------------- 状态采集（只在后台线程里跑） ----------------

def collect():
    from nic_manager import collect as shared_collect
    return shared_collect()


def probe_net(src_ip=None):
    return probe_network(src_ip, component="ui")


def wired_ip():
    from nic_manager import wired_ip as shared_wired_ip
    return shared_wired_ip()


def wired_online():
    """Probe only through the physical wired adapter; never fall back to another route."""
    ip = wired_ip()
    return bool(ip) and probe_net(ip)


def wait_for_wired_online(probe, timeout=AUTH_WAIT, interval=AUTH_POLL):
    return wait_check(probe, timeout, interval)


def last_log():
    import json
    try:
        with open(LOG, "rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 16000))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            try:
                record = json.loads(line)
                return "%s [%s] %s" % (record.get("time", ""), record.get("component", ""), record.get("event", ""))
            except ValueError:
                continue
    except OSError:
        pass
    return "暂无事件"


def startup_status():
    try:
        values = {}
        with open(STARTUP_STATUS, encoding="utf-8-sig") as stream:
            for line in stream:
                if "=" in line:
                    key, value = line.rstrip("\r\n").split("=", 1)
                    values[key] = value
        return values
    except OSError:
        return {}


# ---------------- 动作 ----------------

SVC_NAMES = {"0": "教育网", "1": "联通", "2": "移动", "3": "电信"}


def is_bypass_mode():
    mode = auth_mode()
    return None if mode is None else mode == "bypass"


def supplicant_running():
    return bool(process_info())


def read_conf():
    conf = read_config(CFG)
    nic = resolve_nic(force=True)["device"]
    return conf["user"], conf["pwd"], conf["oip"], conf["omask"], conf["svc"], nic


def current_service():
    try:
        with open(CFG, "r", encoding="utf-8", errors="ignore") as f:
            p = f.read().split()
        return p[4] if len(p) > 4 else "3"
    except Exception:
        return "3"


def save_service(svc):
    """只改第 5 个字段，其余原样保留"""
    try:
        with open(CFG, "r", encoding="utf-8", errors="ignore") as f:
            p = f.read().split()
        while len(p) < 5:
            p.append("3")
        p[4] = svc
        with open(CFG, "w", encoding="utf-8", newline="") as f:
            f.write(" ".join(p) + "\n")
        return True
    except Exception as e:
        logerr("save_service: %r" % (e,))
        return False


# ---------------- 界面 ----------------

class App:
    def __init__(self, root):
        self.root = root
        self.snap = {}
        self.net_wired = False
        self.net_any = False
        self.alive = True
        self.auth_lock = threading.Lock()

        root.title("JMU 夜间联网")
        root.configure(bg=BG)
        sw = root.winfo_screenwidth()
        sh_ = root.winfo_screenheight()
        root.geometry("560x580+%d+%d" % (int((sw - 560) / 2), int((sh_ - 580) / 3)))
        # 保证窗口真的显示出来（曾经被 topmost 压到屏幕外）
        root.deiconify()
        root.lift()

        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 2))
        self.dot = tk.Canvas(top, width=22, height=22, bg=BG, highlightthickness=0)
        self.dot.pack(side="left")
        self.circle = self.dot.create_oval(3, 3, 20, 20, fill=C_IDLE, outline="")
        self.head = tk.Label(top, text="正在检查有线连接…", font=("Microsoft YaHei", 15, "bold"),
                             bg=BG, fg="#2c3e50")
        self.head.pack(side="left", padx=8)

        # 模式徽章
        self.mode_badge = tk.Label(top, text="", font=("Microsoft YaHei", 10, "bold"),
                                   bg="#ecf0f1", fg="#7f8c8d", padx=10, pady=2)
        self.mode_badge.pack(side="left", padx=6)

        self.body = tk.Label(root, text="", justify="left", anchor="nw", bg=BG,
                             fg="#34495e", font=("Microsoft YaHei", 10))
        self.body.pack(fill="both", expand=True, padx=18, pady=6)

        btns = tk.Frame(root, bg=BG)
        btns.pack(fill="x", padx=12, pady=(0, 4))
        for text, w, color, cmd in (

                ("重新认证", 9, "#d68910", self.on_relogin),
                ("夜间认证", 9, "#c0392b", self.on_force_bypass),

                ("刷新测速", 8, "#16a085", self.on_speedtest),
                ("诊断", 6, "#8e44ad", self.on_diagnose),

                ("运行日志", 8, "#7f8c8d", self.on_log),
                ("关闭", 6, "#95a5a6", lambda: self.root.destroy())):
            b = tk.Button(btns, text=text, width=w, command=cmd, bg=color, fg="white",
                          relief="flat",
                          font=("Microsoft YaHei", 10, "bold" if text in ("重新认证", "夜间认证") else "normal"))
            b.pack(side="left", padx=3)

            if text == "重新认证":
                b.bind("<Button-3>", self._on_relogin_right)
                self.btn_relogin = b

        # ---- 诊断输出区（默认折叠）----
        self.diag_frame = tk.Frame(root, bg=BG)
        self.diag_text = tk.Text(self.diag_frame, height=10, bg="#1e1e1e", fg="#d4d4d4",
                                 font=("Consolas", 9), wrap="word", relief="flat")
        sb = tk.Scrollbar(self.diag_frame, command=self.diag_text.yview)
        self.diag_text.config(yscrollcommand=sb.set)
        self.diag_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.diag_shown = False

        self.tip = tk.Label(root, text="“重新认证”按时段选择方案；“夜间认证”手动使用夜间方案。",
                            bg=BG, fg="#7f8c8d", font=("Microsoft YaHei", 8), anchor="w")
        self.tip.pack(fill="x", padx=18, pady=(0, 10))

        logerr("window opened (threaded)")
        # 先让窗口画出来，再开始采数据
        root.after(150, self.start_worker)
        root.after(400, self.tick)
        self.force_bypass = False
        # 窗口画好后：非断网时段问一下要不要开破解
        root.after(1500, self._ask_bypass_mode)
        # 自动测速：等 worker 把模式（破解 / 普通 / 未运行）检测出来之后再开始，
        # 否则测速和模式检测两条 PowerShell 会打架，徽章还会晚一步出来。
        root.after(500, self._auto_speedtest_when_ready)

    def _auto_speedtest_when_ready(self, tries=0):
        """等模式检测出结果后，再自动测一次速。

        worker 第一轮会设置 self.bypass_mode（值可能是 None，表示进程没在跑 ——
        那也是"检测完成"）。最多等 40×300ms ≈ 12 秒，超时就先测，不等了。
        """
        if not hasattr(self, "bypass_mode") and tries < 40:
            self.root.after(300, lambda: self._auto_speedtest_when_ready(tries + 1))
            return
        if getattr(self, "_auto_speed_done", False):
            return
        self._auto_speed_done = True
        self.on_speedtest()

    def start_worker(self):
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        while self.alive:
            try:
                # 测速改为手动（点「刷新测速」）
                self.bypass_mode = is_bypass_mode()
                snap = collect()
                ip = snap.get("IP", "")
                self.net_wired = probe_net(ip) if (snap.get("STATUS") == "Up" and ip) else False
                # 有线已经通了就不用再探一次"任意网"，省掉一轮 curl
                self.net_any = True if self.net_wired else probe_net()
                snap["_last"] = last_log()
                snap["_startup"] = startup_status()
                snap["_time"] = datetime.datetime.now().strftime("%H:%M:%S")
                signature = (snap.get("STATUS"), snap.get("IP"), snap.get("IFACE"), self.net_wired, self.net_any)
                if signature != getattr(self, "_logged_network", None):
                    event("ui", "网络状态变化", interface=snap.get("NIC_NAME"), status=snap.get("STATUS"),
                          source=snap.get("IP"), route=snap.get("IFACE"), wired_online=self.net_wired,
                          other_online=self.net_any, reason=snap.get("NIC_ERROR"))
                    self._logged_network = signature
                self.snap = snap

            except Exception as e:
                logerr("worker: %r" % (e,))
            time.sleep(5)

    def tick(self):
        try:
            self.render()
        except Exception as e:
            logerr("tick: %r" % (e,))
        if self.alive:
            self.root.after(700, self.tick)

    def render(self):
        snap = self.snap
        if not snap:
            return
        up = snap.get("STATUS") == "Up"
        ip = snap.get("IP", "")
        if self.net_wired:
            color, title = C_OK, "有线可上网 · 已验证"
        elif self.net_any:
            color, title = C_WARN, "其他连接可上网 · 有线未验证"
        elif up and not ip:
            color, title = C_WARN, "有线已连接 · 等待获取地址"
        elif up:
            color, title = C_WARN, "有线已连接 · 联网验证未通过"
        else:
            color, title = C_BAD, "有线未就绪 · 请检查网卡或网线"
        phase = getattr(self, "_auth_phase", "")
        if phase:
            color, title = C_WARN, "正在认证 · 联网待验证"
        self.dot.itemconfig(self.circle, fill=color)
        self.head.config(text=title, fg=color)
        mode = getattr(self, "bypass_mode", None)
        badge = "最近方案：" + ("夜间认证" if mode is True else "运营商认证" if mode is False else "暂无记录")
        self.mode_badge.config(text=badge, bg="#ecf0f1", fg="#566573")
        startup = snap.get("_startup", {})
        labels = {"WAITING": "等待有线网卡", "AUTHENTICATING": "认证中，尚未验证联网",
                  "VERIFYING": "正在验证有线联网", "RETRYING": "上次未通过，准备重试",
                  "VERIFIED": "当时有线联网验证通过", "FAILED": "未能确认有线联网"}
        startup_line = labels.get(startup.get("state"), "暂无记录")
        if startup.get("state") in ("WAITING", "AUTHENTICATING", "VERIFYING", "RETRYING"):
            try:
                recorded = datetime.datetime.fromisoformat(startup.get("time", ""))
                if (datetime.datetime.now() - recorded).total_seconds() > 120:
                    startup_line = "上次任务未记录完成结果"
            except ValueError:
                startup_line = "记录时间无效，无法确认任务状态"
        if startup.get("time"):
            startup_line += "（" + startup["time"] + "）"
        speed = getattr(self, "speed_info", None) or {}
        latency, mbps = speed.get("lat"), speed.get("mbps")
        speed_line = "尚未测量"
        if latency is not None or mbps is not None:
            speed_line = "响应 %s；下载 %s" % (("%.0f ms" % latency) if latency is not None else "未测得",
                ("%.2f MB/s" % mbps) if mbps is not None else "未测得")
        from switch_notifications import read_switch_status
        switch = read_switch_status()
        switch_text = {'FAILED': switch.get('reason') or '自动切换未确认成功，请查看运行日志',
                       'PENDING': '正在认证，等待本次服务器回应与联网验证',
                       'VERIFIED': '最近一次切换已验证',
                       'CONNECTED': '有线联网已恢复，未重新认证'}.get(switch.get('status'), '暂无记录')
        rows = [("认证网卡", snap.get("NIC_NAME") or "尚未选定"),
                ("网卡检查", snap.get("NIC_ERROR") or ("链路已连接" if up else "链路未就绪")),
                ("有线地址", ip or "尚未取得"),
                ("认证进程", "运行中；进程存在不代表联网成功" if snap.get("SUPP") else "未运行；以联网验证为准"),
                ("默认出口", snap.get("IFACE") or "未取得"),
                ("有线联网", "正在重新验证" if phase else "最近检测通过" if self.net_wired else "尚未验证通过"),
                ("当前操作", phase or "空闲"),
                ("自动切换", switch_text),
                ("开机验证记录", startup_line), ("测速结果", speed_line),
                ("最近事件", snap.get("_last", "暂无事件")),
                ("检查时间", snap.get("_time", "正在检查"))]
        self.body.config(text="\n".join("%s：%s" % item for item in rows))

    # ---- 移动热点 ----




    # ---- 按钮 ----
    # ---- 启动时询问是否开破解（仅非断网时段）----
    def _ask_bypass_mode(self):
        try:
            if is_blackout() or getattr(self, "bypass_mode", None):
                return
            answer = messagebox.askyesno("选择认证方案",
                "当前为正常时段，是否现在尝试夜间认证方案？\n\n"
                "选择“是”会重新认证，期间可能短暂断网。\n"
                "选择“否”保留当前连接；需要时可点“重新认证”。")
            if answer:
                self.tip.config(text="正在启动夜间认证，随后验证有线联网…")
                threading.Thread(target=self._connect_bypass, daemon=True).start()
        except Exception as exc:
            logerr("选择认证方案失败：" + str(exc))

    def _connect_bypass(self):
        return manual_auth(self, "bypass")

    def on_force_bypass(self):
        """「破解」按钮：任何时候都能强制切到「办公区 IP + 教育网」（-n）。

        常规时段也允许 —— 想提前准备、或者运营商怎么都认证不过去时手动接管。
        """
        if getattr(self, "bypass_mode", None):
            self.tip.config(text="正在重新认证，期间网络可能短暂中断…")
        else:
            self.tip.config(text="正在启动夜间认证，随后验证有线联网…")
        threading.Thread(target=self._connect_bypass, daemon=True).start()

    def on_relogin(self):
        """左键：按时段自动选模式（断网时段 → 破解 / 正常时段 → 运营商）。

        想在任何时候强制破解，点左边的「破解」按钮。
        """
        if is_blackout() or should_prepare_bypass():
            self.tip.config(text="夜间或准备时段：正在认证，随后验证有线联网…")
            threading.Thread(target=self._connect_bypass, daemon=True).start()
        else:
            svc = current_service()
            self.tip.config(text="正常时段：正在使用「%s」认证，随后验证有线联网…" % SVC_NAMES.get(svc, svc))
            threading.Thread(target=self._connect_normal, args=(svc,), daemon=True).start()

    def _on_relogin_right(self, event):
        m = tk.Menu(self.root, tearoff=0, font=("Microsoft YaHei", 9))
        m.add_command(label="—— 正常时段用的运营商 ——", state="disabled")
        for name, val in (("教育网", "0"), ("联通", "1"), ("移动", "2"), ("电信", "3")):
            m.add_command(label="  " + name,
                          command=lambda v=val, n=name: self._switch_service(v, n))
        m.add_separator()
        m.add_command(label="  立即重新认证", command=self.on_relogin)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                m.grab_release()
            except Exception:
                pass

    def _switch_service(self, val, name):
        try:
            if save_service(val):
                self.tip.config(text="运营商改为「%s」，正在认证…" % name)
                threading.Thread(target=self._connect_normal, args=(val,), daemon=True).start()
            else:
                self.tip.config(text="写入 config.txt 失败")
        except Exception as e:
            logerr("switch_service: %r" % (e,))

    def _connect_normal(self, svc):
        return manual_auth(self, "normal", svc)

    def diag_write(self, line):
        self.diag_text.insert("end", line + "\n")
        self.diag_text.see("end")

    def on_diagnose(self):
        if not self.diag_shown:
            self.diag_frame.pack(fill="both", expand=False, padx=14, pady=(4, 6))
            self.diag_shown = True
        self.diag_text.delete("1.0", "end")
        self.diag_frame.pack(fill="both", expand=False, padx=14, pady=(4, 6))
        threading.Thread(target=self._run_diag, daemon=True).start()

    def _run_diag(self):
        def write(text):
            event("diagnostic", "诊断结果", detail=text)
            self.root.after(0, lambda text=text: self.diag_write(text))
        try:
            adapter = resolve_nic(force=True)
            write("认证网卡：%s；状态：%s" % (adapter["name"], adapter["status"]))
            write("有线地址：%s；默认出口：%s" % (adapter.get("ip") or "尚未取得 IPv4", adapter.get("default_alias") or "无"))
            ip = adapter.get("ip")
            wired = bool(ip) and probe_network(ip, component="diagnostic")
            other = wired or probe_network(component="diagnostic")
            write("有线联网：%s；系统默认出口联网：%s" % ("已验证" if wired else "未通过", "已验证" if other else "未通过"))
            write("认证进程：%s" % ("运行中" if process_info() else "未运行"))
            write("当前时段：%s" % ("夜间限制时段" if is_blackout() else "正常时段"))
            if wired:
                write("结论：所选有线网卡已通过联网验证。")
            elif other:
                write("结论：其他连接可上网，所选有线网卡尚未通过验证。")
            else:
                write("结论：联网验证未通过，请查看日志中的状态码及失败原因。")
        except Exception as exc:
            write("诊断未完成：" + str(exc))

    # ---- 手动测速 ----
    def on_speedtest(self):
        if getattr(self, "_speed_busy", False):
            self.tip.config(text="有线测速正在进行，请等待本次结果。")
            return
        if getattr(self, "_auth_phase", ""):
            self.tip.config(text="正在认证，请等待联网验证完成后再测速。")
            return
        self._speed_busy = True
        self.tip.config(text="正在测量所选有线网卡，请稍候…")
        threading.Thread(target=self._do_speedtest, daemon=True).start()

    def _do_speedtest(self):
        try:
            info = self._measure_speed()
            self.speed_info = info
            parts = []
            if info.get("lat") is not None:
                parts.append("请求响应 %.0f ms" % info["lat"])
            if info.get("mbps") is not None:
                parts.append("下载 %.2f MB/s" % info["mbps"])
            message = "有线测速结果：" + "；".join(parts) if parts else "有线测速未完成：" + info.get("reason", "测试服务器未返回有效结果")
            if self.alive:
                self.root.after(0, lambda message=message: self.tip.config(text=message))
                self.root.after(0, self.render)
        except Exception as exc:
            event("speed", "有线测速失败", level="WARNING", reason=type(exc).__name__)
        finally:
            self._speed_busy = False

    # ---- 简单测速 ----

    def _measure_speed(self):
        ip = wired_ip()
        if not ip or not probe_net(ip):
            return {"lat": None, "mbps": None, "reason": "所选有线网卡尚未通过联网验证"}
        base = ["curl.exe", "-sS", "--noproxy", "*", "--interface", ip, "--fail", "-o", "NUL"]
        latency = []
        for _ in range(2):
            output = sh(base + ["-m", "3", "-w", "%{time_starttransfer}", "https://www.qq.com"], timeout=4).strip()
            try:
                number = float(output) * 1000
                if 0 < number < 3000:
                    latency.append(number)
            except ValueError:
                pass
        output = sh(base + ["-m", "6", "-r", "0-1000000", "-w", "%{speed_download}",
                           "https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ls-lR.gz"], timeout=7).strip()
        try:
            speed = float(output) / 1000000
            speed = speed if speed > 0 else None
        except ValueError:
            speed = None
        measured = min(latency) if latency else None
        event("speed", "有线测速结果", source=ip, response_ms=measured, megabytes_per_second=speed)
        return {"lat": measured, "mbps": speed}

    def on_log(self):
        try:
            if not os.path.exists(LOG):
                with open(LOG, "a", encoding="utf-8"):
                    pass
            os.startfile(LOG)
        except Exception as e:
            logerr("openlog: %r" % (e,))


def main():
    root = tk.Tk()
    app = App(root)
    try:
        root.mainloop()
    finally:
        app.alive = False


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logerr("fatal: %r" % (e,))
        raise
