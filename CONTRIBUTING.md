# 参与贡献

`linux/` 保存原 Linux 提交 `f8548e6` 的 11 个程序、测试及资源文件，内容保持不变；Windows 适配在 `windows/` 内进行。README、依赖清单、许可证和发布工具在根目录共用。请勿为适配 Windows 改写 Linux 程序或重新生成其资源。

`LINUX_BASELINE.json` 记录原始提交与文件 SHA-256。打包和校验时会核对该基线；不要通过修改基线掩盖 Linux 文件变化。整体发布版本由根目录打包器管理，Windows 内部版本为 `1.1.0`，Linux 原内部版本 `0.2.0` 保留。

## 本地验证

使用 Python **3.10+**，按 [README.md](README.md) 在对应系统目录创建 `.venv`，安装根目录的 `requirements.txt`。以下命令均从仓库根目录运行。

Windows PowerShell：

```powershell
.\windows\.venv\Scripts\python.exe -m unittest test_release_source -v
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows -v
.\windows\.venv\Scripts\python.exe windows/app.py --render build/windows-preview.png
.\windows\.venv\Scripts\python.exe release_source.py --refresh-checksums
.\windows\.venv\Scripts\python.exe release_source.py --verify release/codex-quota-float-1.1.0.zip
```

Linux：

```bash
linux/.venv/bin/python -m unittest test_release_source -v
linux/.venv/bin/python -m unittest discover -s linux -v
linux/.venv/bin/python linux/app.py --render build/linux-preview.png
linux/.venv/bin/python release_source.py --refresh-checksums
linux/.venv/bin/python release_source.py --verify release/codex-quota-float-1.1.0.zip
```

无显示设备的 Linux 环境可在测试、渲染命令前加 `QT_QPA_PLATFORM=offscreen`。两个系统的测试分别发现、分别启动，避免同名模块互相导入。根目录 `test_release_source.py` 单独验证公共文件清单、Linux 基线与发布包。

测试使用假的 app-server，覆盖通信、超时、取消和进程清理，不应要求账户凭据或发送真实账户请求。新增行为应覆盖有意义的异常情况，继续将缺失数据显示为未知。除非有意修改产品行为，保留 60 秒的额度和倒计时更新间隔。

运行数据在 Linux 使用 XDG 目录，在 Windows 使用 AppData 目录；可执行文件位置通过环境变量覆盖。Windows 子进程保持无控制台窗口，调用原生程序时不经过 shell。

GitHub Actions 工作流分别验证源码发布和对应系统的程序，桌面测试覆盖 Ubuntu / Windows 及 Python 3.10 / 3.12。工作流结果与真实账户读取、桌面交互检查是不同的验证；发布前应在目标桌面环境完成必要的人工检查。

请勿提交真实额度输出、个人截图、凭据、本机快捷方式或虚拟环境。新增公开文件时，同时更新根目录 `release_source.py` 的显式文件清单；源码包只包含该清单与生成的 `SHA256SUMS`。发布步骤见 [RELEASE.md](RELEASE.md)。

贡献内容按项目的 GPL-3.0-only 许可证发布。
