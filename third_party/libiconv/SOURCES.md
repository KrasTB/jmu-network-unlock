# libiconv 1.19-1 对应源码

运行 DLL 与本地安装的 MSYS2 `mingw-w64-x86_64-libiconv 1.19-1` 校验一致。

- 上游源码：https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.19.tar.gz
- SHA256：`88dd96a8c0464eca144fc791ae60cd31cd8ee78321e67397e25fc095c4a19aa6`
- MSYS2 配方及补丁固定于提交 `045d46aedb9fdbd93b0900b1e20c1a6c73f23072`：https://github.com/msys2/MINGW-packages/tree/045d46aedb9fdbd93b0900b1e20c1a6c73f23072/mingw-w64-libiconv

本目录保留 PKGBUILD、全部补丁及 iconv.pc。GNU 原始 tar.gz 随 GitHub Release 的完整源码附件提供；也可从上述固定来源取得并核对校验和。

在 MSYS2 MINGW64 环境准备 PKGBUILD 所列依赖后，可按配方使用 `makepkg-mingw` 构建；依赖工具链由 MSYS2 官方包提供。库许可全文位于根目录 licenses/。
