# 发布 v1.1.1

本版同时提供 Windows x64 EXE、Windows 便携 ZIP 和双系统源码 ZIP。普通 Windows 用户下载 EXE 后双击即可，无需安装 Python；Linux 继续使用原版源码和启动方式。

`linux/` 的 11 个程序、测试和资源文件与原提交 `f8548e6` 逐字节一致，内部版本号 `0.2.0` 保留。整体发布版本与 Windows 内部版本为 `1.1.1`。

## 在 Windows 构建与检查

维护者需要 Windows x64、Python 3.10+。以下命令从仓库根目录运行；已经有 `windows/.venv` 时跳过创建环境的一行。

```powershell
py -3 -m venv windows/.venv
.\windows\.venv\Scripts\python.exe -m pip install -r requirements.txt -r windows/requirements-build.txt
.\windows\.venv\Scripts\python.exe -m unittest discover -v
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows -v
.\windows\.venv\Scripts\python.exe release_source.py --refresh-checksums
.\windows\.venv\Scripts\python.exe windows/build_exe.py
.\windows\.venv\Scripts\python.exe windows/build_exe.py --verify
```

构建工具使用 PyInstaller 打包单文件、无控制台窗口的 EXE，收集实际环境中的许可证，并生成 Windows 便携包与校验文件。构建和自动冒烟检查使用离线示例数据，不读取维护者的 Codex 账号。安装构建依赖需要网络；最终附件必须同时提供依赖源码指引 `DEPENDENCY_SOURCES.md`，其中列出实际依赖版本及对应源码的官方下载地址。

`--verify` 检查现有发布附件，并运行 EXE 的离线渲染与状态检查。发布前还应从资源管理器双击 EXE，检查拖动、右键菜单、重复启动、退出和快捷方式，并在自己的已登录 Codex 环境中检查真实额度；真实账户检查结果不应提交到仓库。

`release_source.py --refresh-checksums` 更新应提交的根目录 `SHA256SUMS`，并生成源码 ZIP。公开文件使用显式清单，打包时同时核对 `LINUX_BASELINE.json`；Linux 文件保持原字节，Windows 启动脚本使用 CRLF，其余新增公开文本使用 LF。

`release/`、`build/`、虚拟环境及用户运行数据不提交到 Git。EXE 和 ZIP 作为 GitHub Release 的 Assets 上传。

## Linux 验证

按 README 在 `linux/` 创建虚拟环境并安装依赖后，从仓库根目录运行：

```bash
linux/.venv/bin/python -m unittest discover -v
linux/.venv/bin/python -m unittest discover -s linux -v
linux/.venv/bin/python linux/app.py --render build/linux-preview.png
linux/.venv/bin/python release_source.py --verify release/codex-quota-float-1.1.1.zip
```

无显示设备的 Linux 环境可在测试、渲染命令前加 `QT_QPA_PLATFORM=offscreen`。本机验证只覆盖本机目标系统，应等待 GitHub Actions 的 Ubuntu 和 Windows 检查都通过。

## 发布附件

同一个 GitHub Release 上传以下文件，其中 EXE 与两个 ZIP 各自提供同名 `.sha256`：

- `release/CodexQuotaFloat-1.1.1-windows-x64.exe`：普通 Windows 用户双击运行。
- `release/CodexQuotaFloat-1.1.1-windows-x64.zip`：便携包，包含 EXE、中文使用说明、项目许可证、第三方许可证与对应项目源码。
- `release/codex-quota-float-1.1.1.zip`：两个系统的项目源码、测试和构建工具。
- `release/DEPENDENCY_SOURCES.md`：Windows 二进制所含开源依赖的实际版本和对应源码的官方下载地址；此文档也包含在便携 ZIP 中。

源码 ZIP 内的 `SHA256SUMS` 校验各公开文件，附件旁边的 `.sha256` 校验整个下载文件。Windows EXE 内也保留运行时需要的第三方许可文件。项目源码与依赖源码获取说明应和 EXE 在同一个 Release 页面提供，并保留许可证。

## 更新仓库

以下命令由维护者执行。先检查当前分支、远端与文件差异，再提交；本文不会自动提交或推送。

```powershell
git status --short
git remote -v
git branch --show-current

git add -A
git --no-pager diff --cached --stat
git --no-pager diff --cached --check
git commit -m "Release v1.1.1: add one-click Windows EXE"
git pull --rebase origin main
git push origin main
```

远端应为 `https://github.com/ShuyuYan/codex-quota-float.git`，当前分支应为 `main`。暂存内容只应包含公开源码、资源、文档、工作流和校验记录。Git 分页查看界面可按 `q` 退出；上面使用 `--no-pager` 避免进入分页器。

若 `pull --rebase` 产生冲突，解决后重新验证再推送。若同步远端改变了发布内容，重新构建所有附件和校验文件，提交新的 `SHA256SUMS` 再推送；最终发布包必须对应打标签的提交。

等待 [GitHub Actions](https://github.com/ShuyuYan/codex-quota-float/actions) 的两系统测试、源码发布检查和 Windows EXE 构建通过。工作流产物可下载用于发布；发布附件应来自同一提交、同一次对应的构建。

## 标签与 GitHub Release

已发布的 **v1.1.0 保持不变**；本次 EXE 版本使用 **v1.1.1**。

先检查 `v1.1.1` 是否已经存在：

```powershell
git ls-remote --tags origin refs/tags/v1.1.1
```

没有输出时，可以为已验证的提交创建标签：

```powershell
git tag -a v1.1.1 -m "Codex Quota Float v1.1.1 - Windows EXE / Linux"
git push origin v1.1.1
```

如果标签已经存在，先核对它对应的提交和现有 Release；不要强制覆盖已发布标签。若旧版 `v1.1.1` 已正式发布，应改用新的版本号，并同步修改版本常量、文件名和说明后重新构建。

在 [新建 Release](https://github.com/ShuyuYan/codex-quota-float/releases/new) 页面选择正确标签，标题填写 `Codex Quota Float v1.1.1 — Windows EXE / Linux`，正文复制 [RELEASE_NOTES.md](RELEASE_NOTES.md)，上传全部 7 个附件后发布。

已安装并登录 GitHub CLI 的维护者，也可从仓库根目录运行：

```powershell
gh release create v1.1.1 release/CodexQuotaFloat-1.1.1-windows-x64.exe release/CodexQuotaFloat-1.1.1-windows-x64.exe.sha256 release/CodexQuotaFloat-1.1.1-windows-x64.zip release/CodexQuotaFloat-1.1.1-windows-x64.zip.sha256 release/codex-quota-float-1.1.1.zip release/codex-quota-float-1.1.1.zip.sha256 release/DEPENDENCY_SOURCES.md --repo ShuyuYan/codex-quota-float --verify-tag --title "Codex Quota Float v1.1.1 - Windows EXE / Linux" --notes-file RELEASE_NOTES.md
```

Git 推送和标签的发布行为以仓库工作流为准；本地命令不会代替维护者发布 GitHub Release。仓库首页 About 可更新为：

```text
A lightweight Codex quota widget for Windows and Linux. Download the Windows EXE and double-click to run.
```

后续发布应同步更新根目录打包器的发布版本、Windows 内部版本及共享文档，再重新生成所有附件和校验。Linux 原版文件与基线保持不变。
