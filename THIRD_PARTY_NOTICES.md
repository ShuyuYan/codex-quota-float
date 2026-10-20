# Third-party dependencies

The application is licensed under **GPL-3.0-only**; see the root `LICENSE`.
The Linux application remains source-only. The Windows EXE and portable ZIP
include the runtime components needed to run without a separate Python
installation. Codex is installed and authenticated separately.

## Windows binary distribution

The build collects the actual installed components' license files into
`licenses/`, includes them in the EXE, and places copies in the portable ZIP.
Keep those files when redistributing the binary. The corresponding project
source is supplied as `codex-quota-float-1.1.2.zip` in the same Release and in
the portable ZIP. The dependency versions and official corresponding-source
download locations are provided in
[dependency source instructions](https://github.com/ShuyuYan/codex-quota-float/blob/v1.1.2/windows/DEPENDENCY_SOURCES.md), also included
as `DEPENDENCY_SOURCES.md` in the portable ZIP and uploaded as a separate
Release attachment.

| Component | Terms and source |
| --- | --- |
| CPython and its standard library | Python Software Foundation License and the component notices included with Python. See [Python license](https://docs.python.org/3/license.html). |
| PyQt5 | GNU GPL v3; this project uses the GPL distribution. See [Riverbank licensing](https://www.riverbankcomputing.com/software/pyqt/intro). |
| PyQt5-sip | BSD-2-Clause, as stated in the installed distribution's metadata and license. See [SIP project](https://github.com/Python-SIP/sip). |
| Qt 5 libraries and plugins | The PyQt5-Qt5 distribution supplies Qt under LGPL v3, with additional notices for third-party components included in Qt. See [Qt open-source terms](https://www.qt.io/development/open-source-lgpl-obligations). |
| PyInstaller bootloader and runtime hooks | GPL v2 or later with the PyInstaller bootloader exception; selected files are Apache-2.0. See [PyInstaller license](https://pyinstaller.org/en/v6.22.3/license.html). |
| OpenSSL and other Python runtime components, when bundled | Their own license texts and copyright notices, retained from the Python distribution. See the collected Python license and [dependency source instructions](https://github.com/ShuyuYan/codex-quota-float/blob/v1.1.2/windows/DEPENDENCY_SOURCES.md). |

The PyInstaller exception permits distributing a combined executable while
retaining the obligations of the application's dependencies. PyQt's GPL
terms and Qt's applicable terms continue to apply. The project does not
change or remove those licenses and does not impose restrictions on
modifying or rebuilding its open-source components.

The application and packaging source is in this repository. For rebuilding,
see [dependency source instructions](windows/DEPENDENCY_SOURCES.md). Dependency
versions and source locations must be kept aligned with each binary build;
the build should not silently substitute incompatible versions or omit
license files.

## Separately installed Codex

Codex is called through its app-server protocol. No Codex executable,
credentials, or account data is bundled in either the project source or the
Windows binary. See [app-server documentation](https://learn.chatgpt.com/docs/app-server).

## Project artwork

`linux/quota-icon.svg` and `windows/quota-icon.svg` are original project
assets. `windows/quota-icon.ico` is the Windows icon rendition. Both
platform directories' `preview-widget.png` files are rendered from the
project's demo interface and contain only example quota data.
