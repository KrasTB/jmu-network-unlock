# 许可范围与第三方归属

本项目不是学校或锐捷的官方客户端。

## 自有代码

`app/*.py`、自有 PowerShell 和 `tools/` 脚本采用根目录 MIT 许可。Python 界面以独立进程调用认证核心。

## 认证核心

- 上游：[ShanQincheng/jmuSupplicant](https://github.com/ShanQincheng/jmuSupplicant)，作者 ShanQincheng（入山），上游采用 Apache License 2.0。
- 本地 Windows 移植修改：Windows 网卡枚举与地址读取；POSIX 兼容层；相对锁文件和输出缓冲；第二阶段运营商通过 `JMU_MIDNIGHT_SERVICE` 配置。新增每次认证独立的状态文件，区分第一阶段与完整成功回应，兼容中文路径。对应源码完整保存在 `core/src`、`core/compat`。
- `core/src/mentohust_encryption` 包含 MentoHUST 相关实现；`ampheck.h`、`rjripemd128.c/.h` 明确采用 GPL-3.0-or-later，Copyright (C) 2009 Gabriel A. Petursson。
- Aleksey Kravchenko 的 RHash 代码、L. Peter Deutsch / Aladdin Enterprises 的 MD5 代码、RSA Data Security 的 MD5 代码保留各自原始头部声明，未统一改写为本项目许可。

含上述 GPL 部分的组合认证核心按 GPL-3.0-or-later 分发，同时保留 Apache-2.0 和其他适用条款；不能把整个核心称为仅 Apache-2.0。全文在 `licenses/`。源码文件原有的版权和许可头部优先保留。

## libiconv

运行包的 `libiconv-2.dll` 原样来自 MSYS2 `mingw-w64-x86_64-libiconv 1.19-1`；库保留 LGPL-2.1-or-later 等上游声明，相关文档使用 GPL。允许用户替换兼容 DLL，程序没有完整性检查来限制替换。

对应源码：GNU libiconv 1.19 原始压缩包，以及 MSYS2 构建配方与全部补丁。见 `third_party/libiconv/SOURCES.md`；完整材料随发行版源码附件一同提供。

## Python、Tcl/Tk 与 PyInstaller

GUI 打包包含 Python 3.12 和 Tcl/Tk，运行包附带其许可。PyInstaller 按 GPL 及其 bootloader 例外许可构建，不要求将独立应用改为 GPL；参考 https://pyinstaller.org/en/stable/license.html 。

## Npcap

Npcap 驱动、DLL 和安装器不随本项目再分发。程序仅引导用户从 https://npcap.com/ 下载官方安装器，并验证固定 SHA256 与签名。Npcap 的使用受其自身许可约束。
