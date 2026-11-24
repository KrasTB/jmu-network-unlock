# JMU 夜间联网

适用于集美大学锐捷有线认证环境的 Windows 助手，提供普通认证、夜间认证方案、登录后自动认证及定时切换。

## 下载使用

从 [Releases](https://github.com/KrasTB/jmu-network-unlock/releases/latest) 下载 Windows 压缩包，完整解压，双击 **JMU 夜间联网.exe**。首次填写自己的账号密码，无需安装 Python。

- Windows 10/11 x64，需要连接校园网的有线网卡，支持 USB 网卡。
- 缺少 Npcap 时引导从官网下载；安装启用 WinPcap 兼容模式。驱动不随包分发。
- 未自动识别网卡时，在 **设置 → 认证网卡** 手动选择。
- **重新认证**按时段选择方案；**夜间认证**手动尝试夜间方案，期间可能短暂断网。
- “有线已连接”表示链路接通；“有线可上网 · 已验证”表示最近一次联网检测通过。进程运行和历史记录不等于当前能上网。

时间规则：周一至周四 23:00、周五至周日 24:00 起进入夜间时段，06:00 恢复；提前 8 分钟准备。关闭主窗口后仍由计划任务检查；到限制时段仍未确认夜间认证成功时，仅请求 Windows 右下角通知，同一次持续故障不重复提醒。系统通知设置可能隐藏提示。节假日文件需按学校通知维护，当前附表仅含 2026 年。

办公区认证 IP 默认 `172.20.1.10`，不是 Windows 网卡地址。多人填写同一地址可能相互影响；不同账号、端口及学校是否适用需实测，不保证绕过限制或无感切换。

密码保存在本机 `程序/config.txt`，分享时使用原始发行包。运行日志为 `程序/runtime.log`，隐藏账号密码并自动轮换；反馈问题前仍请检查日志是否含不想公开的网络信息。

## 源码与构建

目录：`app/` 为界面和调度代码；`core/` 为认证核心的 Windows 移植源码；`tools/` 为构建工具；`tests/` 为离线测试。

GUI 构建需要 Windows x64、Python 3.12（含 tkinter）：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
# 从同版本发行包提取已验证的核心和 DLL；也可自行编译 core/。
.venv\Scripts\python tools\prepare_runtime.py --archive 路径\JMU-night-network-windows-x64-v0.1.1.zip
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python tools\build.py
```

构建输出在 `dist/`。从源码启动为 `.venv\Scripts\python app\launcher.py`。

认证核心构建见 [core/README.md](core/README.md)。GUI 的测试不会使用真实账号认证；发行包通过中文路径、首次设置、网卡选择、状态提示和打包启动检查，未覆盖所有硬件或其他学校环境。

## 许可与来源

自有界面及脚本使用 MIT。认证核心含 jmuSupplicant 的 Apache-2.0 代码及 GPL-3.0-or-later 等第三方实现，组合核心按 GPLv3 分发；libiconv 保留自身许可。完整范围和来源见 [NOTICE.md](NOTICE.md) 与 [licenses/](licenses/)。

发行版同时提供源码包，包含核心源码和 libiconv 1.19 对应源码、补丁及构建配方。Npcap 不包含在源码包或运行包中。
