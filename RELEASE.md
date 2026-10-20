# 发布 v1.1.0

本版提供一个含 `linux/`、`windows/` 的源码 ZIP，共用根目录的文档、依赖清单和许可证。两个系统分别创建虚拟环境、安装 Python 3.10+ 与 PyQt5，并使用各自已登录的 Codex。

Linux 目录中的 11 个程序、测试和资源文件与原提交 `f8548e6` 逐字节一致，其内部版本号 `0.2.0` 保留。整体发布版本为 `1.1.0`，Windows 内部版本为 `1.1.0`。

## 生成与检查

按 README 在对应系统目录创建 `.venv` 并安装依赖。以下命令从仓库根目录运行。

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

无显示设备的 Linux 环境可在测试、渲染命令前加 `QT_QPA_PLATFORM=offscreen`。本机验证只能覆盖本机的目标系统；等待 GitHub Actions 的两系统检查完成后再创建 Release。

`--refresh-checksums` 生成源码包并更新应提交的根目录 `SHA256SUMS`。根目录打包器读取显式的公开文件清单，并核对 `LINUX_BASELINE.json`；Linux 文件保留原始字节，Windows 启动脚本使用 CRLF，其余新增公开文本使用 LF。

最终上传的文件只有：

- `release/codex-quota-float-1.1.0.zip`
- `release/codex-quota-float-1.1.0.zip.sha256`

ZIP 内的根目录 `SHA256SUMS` 校验各公开文件，旁边的 `.zip.sha256` 校验整个 ZIP。验证命令检查两层校验、公开文件清单、发布版本和 Linux 基线，不解压或运行包内代码。`release/`、`build/`、虚拟环境及用户运行数据不提交到仓库。

## 更新仓库

以下命令由维护者执行。先确认当前分支为 `main`，远端为 `https://github.com/ShuyuYan/codex-quota-float.git`，并已完成上面的验证和打包。

```powershell
git status --short
git remote -v
git branch --show-current

# 同时暂存新增目录与已移动的旧文件
git add -A
git diff --cached --name-status
git diff --cached --check
git commit -m "Release v1.1.0: separate Windows and Linux apps"

git pull --rebase origin main
git push origin main
```

提交前检查暂存内容，只应包含公开源码、资源、文档和校验记录。此处使用 `git add -A`，因为目录调整同时包含原根目录文件的删除和系统子目录文件的新增。

若 `pull --rebase` 发生冲突，解决冲突后重新验证再推送。同步远端造成发布内容变化时，重新生成源码包和根目录校验、提交更新，再推送；最终发布包必须对应打标签的提交。

等待 [Tests 工作流](https://github.com/ShuyuYan/codex-quota-float/actions/workflows/tests.yml) 中的源码发布检查和 Ubuntu / Windows × Python 3.10 / 3.12 检查全部通过，再给该提交打标签：

```powershell
git tag -a v1.1.0 -m "Codex Quota Float v1.1.0 - Windows and Linux"
git push origin v1.1.0
```

## 创建 GitHub Release

Git 推送和标签不会自动创建 GitHub Release。

在 [新建 Release](https://github.com/ShuyuYan/codex-quota-float/releases/new) 页面选择 `v1.1.0` 标签，标题填写 `Codex Quota Float v1.1.0 — Windows / Linux`，正文复制 [RELEASE_NOTES.md](RELEASE_NOTES.md)，上传上面的 ZIP 与校验文件并发布。

已安装并登录 GitHub CLI 的维护者也可从仓库根目录运行：

```powershell
gh release create v1.1.0 release/codex-quota-float-1.1.0.zip release/codex-quota-float-1.1.0.zip.sha256 --repo ShuyuYan/codex-quota-float --verify-tag --title "Codex Quota Float v1.1.0 - Windows / Linux" --notes-file RELEASE_NOTES.md
```

仓库首页右侧 About 简介需在 GitHub 页面单独更新，例如：

```text
A lightweight Windows and Linux desktop widget showing Codex 5-hour and weekly quota remaining, with reset countdowns.
```

后续发布应同步更新根目录打包器的发布版本、Windows 内部版本及共享文档，再重新生成校验和源码包。Linux 原版文件与基线保持不变。
