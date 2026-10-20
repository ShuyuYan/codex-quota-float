# Codex Quota Float v1.1.0 — Windows / Linux

本次发布将两个系统的程序分别放入 `linux/`、`windows/`，共用根目录的安装说明、依赖清单和许可证。

Linux 目录保留原提交 `f8548e6` 的 11 个程序、测试和资源文件，内容不变。新增 Windows 10 / 11 原生适配，支持无控制台后台运行、Codex 自动查找、桌面与开始菜单快捷方式、高 DPI 显示，以及 AppData 配置和日志路径。

两个版本均提供五小时与每周剩余额度、重置时间、拖动置顶、外观切换和单实例功能。

## 下载

- `codex-quota-float-1.1.0.zip`：含 `linux/` 和 `windows/` 的源码包。
- `codex-quota-float-1.1.0.zip.sha256`：上述 ZIP 的 SHA-256 校验文件。

这是源码发布，不包含 Python、PyQt5 或 Codex，不提供独立 `.exe`。需要 Python **3.10+**，以及已通过 ChatGPT 账号登录、支持 `codex app-server` 的 Codex。Linux 以 X11 桌面为目标；Wayland 下的置顶和定位取决于桌面环境；macOS 尚未适配。

## 快速开始

解压后，从包含 README 的根目录开始。

Windows PowerShell：

```powershell
cd windows
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ..\requirements.txt
.\run.cmd --background
```

Linux：

```bash
cd linux
python3 -m venv .venv
.venv/bin/python -m pip install -r ../requirements.txt
bash run.sh --background
```

离线预览使用 `--demo`，一次性查询真实账户使用 `--check`。Windows 后续可直接双击 `windows/run.cmd` 启动。

## 升级

先退出旧版，解压新版后进入对应系统目录，重新创建虚拟环境并安装依赖。已有用户配置会继续读取；请使用新版目录中的 Python 执行 `install_shortcut.py --force`，更新快捷方式。虚拟环境不能跨目录或跨系统直接移动。

整体发布版本为 **v1.1.0**；Windows 内部版本为 `1.1.0`。Linux 程序保持原样，内部版本号保留 `0.2.0`。

完整说明见 [README](https://github.com/ShuyuYan/codex-quota-float/blob/v1.1.0/README.md)，更新记录见 [CHANGELOG](https://github.com/ShuyuYan/codex-quota-float/blob/v1.1.0/CHANGELOG.md)。项目采用 GPL-3.0-only，由社区开发，与 OpenAI 无隶属关系。
