# 认证核心构建

这是 jmuSupplicant 的本地 Windows 移植，保留上游源码版权头；组合核心采用 GPL-3.0-or-later，详见根目录 NOTICE.md。

在 MSYS2 MINGW64 环境安装工具链与 libiconv，并从 https://npcap.com/#download 获取 Npcap SDK，解压到本机目录。SDK 和驱动不随项目分发。

```bash
pacman -S --needed mingw-w64-x86_64-gcc mingw-w64-x86_64-libiconv
python tools/build_core.py --sdk /path/to/npcap-sdk
```

也可在 Windows Python 中指定 `--gcc` 为 MinGW-w64 gcc.exe 的完整路径。构建仅生成文件，不执行认证；输出复制到 `app/` 供 GUI 打包。

兼容层中的部分 POSIX 信号及锁函数为空实现，由 Python 外层负责互斥、进程管理和联网超时。现有发行核心为已使用的预构建版本；未宣称不同工具链下能逐字节复现二进制。
