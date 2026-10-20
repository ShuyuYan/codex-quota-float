#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -eu
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${PYTHON:-}" ]]; then
    interpreter="$PYTHON"
elif [[ -x "$project_dir/.venv/bin/python" ]]; then
    interpreter="$project_dir/.venv/bin/python"
else
    interpreter="python3"
fi
if ! command -v "$interpreter" >/dev/null 2>&1; then
    printf '%s\n' '未找到 Python。请安装 Python 3.10+，或通过 PYTHON 指定解释器。' >&2
    exit 1
fi
exec "$interpreter" "$project_dir/app.py" "$@"
