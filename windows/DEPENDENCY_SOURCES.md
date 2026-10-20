# Windows EXE 对应源码与许可证

本程序允许按 GNU GPL v3 修改和再发布。程序源代码、构建脚本与对应的
`codex-quota-float-1.1.1.zip` 随本次 Release 提供；便携 ZIP 和 EXE 内也包含这份源码 ZIP。
所有嵌入的许可证均位于 `licenses/`，实际构建版本和源码地址记录在 `BUILD_INFO.json`。

未修改的上游依赖源码可直接从以下位置获取：

- PyQt5 5.15.11（GPL-3.0）：https://pypi.org/project/PyQt5/5.15.11/#files
  下载 Source Distribution，即 `PyQt5-5.15.11.tar.gz`。
- Qt 5.15.2（LGPL-3.0，部分第三方组件使用其各自许可证）：
  https://download.qt.io/official_releases/qt/5.15/5.15.2/single/qt-everywhere-src-5.15.2.tar.xz
  包括 Qt 自带第三方组件的源码与许可。Qt 的构建来源说明：
  https://pypi.org/project/PyQt5-Qt5/5.15.2/
- PyQt5-sip 12.20.0（BSD-2-Clause）：https://pypi.org/project/PyQt5-sip/12.20.0/#files
  下载 Source Distribution。
- PyInstaller 6.22.3（GPL-2.0 附打包例外；部分代码采用 Apache-2.0）：
  https://github.com/pyinstaller/pyinstaller/archive/refs/tags/v6.22.3.tar.gz
- CPython（PSF License）：实际 Python 版本和直接下载地址见 `BUILD_INFO.json`；
  上游源码索引：https://www.python.org/downloads/source/

重建：在 Windows x64 上创建 Python 3.12 虚拟环境，安装根目录 `requirements.txt`
及 `windows/requirements-build.txt`，在根目录执行 `python windows/build_exe.py`。
构建工具不会修改 Qt 或 PyQt5，用户可以使用兼容的修改版重新构建程序；本程序不限制
为调试库修改而进行的反向工程。维护者应在发布二进制文件时同时保留这些源码入口和
对应项目源码，不应删除同一 Release 的源码附件。
