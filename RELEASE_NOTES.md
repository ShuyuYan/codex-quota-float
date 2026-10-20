# Codex Quota Float v1.1.1 — Windows EXE / Linux

Windows 现在可以下载后双击启动，无需安装 Python 或运行命令。本版使用新标签 **v1.1.1**，保留已发布的 v1.1.0。Linux 保持原版程序：`linux/` 的 11 个文件与原提交 `f8548e6` 逐字节一致。

两个系统的源码分别位于 `windows/`、`linux/`，共用根目录的 README 和许可证。均可显示五小时与每周剩余额度、重置时间，支持拖动置顶、切换外观和单实例运行。

## Windows：下载后双击

1. 先安装 Codex，并用 ChatGPT 账号登录。
2. 下载 **`CodexQuotaFloat-1.1.1-windows-x64.exe`**，放到固定文件夹。
3. **双击 EXE**，稍等片刻即可看到悬浮窗。右键可以刷新、切换外观、创建桌面快捷方式或退出。

支持 **Windows 10 / 11，64 位 x64**。EXE 内含 Python、PyQt5 和所需界面依赖；不包含 Codex。程序自动查找 Codex CLI 或 Codex 桌面应用，读取真实额度仍需网络与已登录账号。

`CodexQuotaFloat-1.1.1-windows-x64.zip` 是附带使用说明、许可证和第三方说明的便携包，解压后双击其中的 EXE 即可。普通用户不需要下载 GitHub 自动生成的 `Source code`。

## Linux：使用原版源码

下载并解压 **`codex-quota-float-1.1.1.zip`**，从包含 README 的根目录运行：

```bash
cd linux
python3 -m venv .venv
.venv/bin/python -m pip install -r ../requirements.txt
bash run.sh --background
```

需要 Python **3.10+**，以及已通过 ChatGPT 账号登录、支持 `codex app-server` 的 Codex。以 X11 桌面为目标，Wayland 的置顶和定位取决于桌面环境。

## 下载文件

| 文件 | 用途 |
| --- | --- |
| `CodexQuotaFloat-1.1.1-windows-x64.exe` | Windows 双击运行 |
| `CodexQuotaFloat-1.1.1-windows-x64.zip` | Windows 便携包，含 EXE、说明和许可证 |
| `codex-quota-float-1.1.1.zip` | Linux 与 Windows 项目源码、测试及构建工具 |
| `DEPENDENCY_SOURCES.md` | Windows 所含开源依赖的版本、官方下载地址与源码获取说明 |
| EXE 与两个 ZIP 各自同名的 `.sha256` | SHA-256 校验值 |

## 升级

先右键退出旧版。Windows EXE 用户替换原文件后双击即可，位置与外观设置继续保留；由源码版迁移时，将旧快捷方式改为新版 EXE。Linux 与 Windows 源码用户按 README 重新创建虚拟环境，并用 `install_shortcut.py --force` 更新已有快捷方式。

整体版本为 **v1.1.1**，Windows 内部版本为 `1.1.1`，Linux 原内部版本 `0.2.0` 保留。

完整说明见 [README](https://github.com/ShuyuYan/codex-quota-float/blob/v1.1.1/README.md)，更新记录见 [CHANGELOG](https://github.com/ShuyuYan/codex-quota-float/blob/v1.1.1/CHANGELOG.md)。项目采用 GPL-3.0-only，由社区开发，与 OpenAI 无隶属关系。
