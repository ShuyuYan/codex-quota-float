# SPDX-License-Identifier: GPL-3.0-only
"""Read Codex account quotas through its local app-server protocol.

Authentication stays with Codex. This module never opens credential files and
never includes server output or stderr in a user-facing error.
"""

import json
import math
import os
import selectors
import subprocess
import time

from runtime import APP_VERSION, resolve_codex_binary

_MAX_LINE_BYTES = 4 * 1024 * 1024
_CANCEL_CHECK_SECONDS = 0.2


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _snapshot(raw):
    """Prefer the Codex bucket; do not silently choose another named bucket."""
    by_limit = raw.get("rateLimitsByLimitId")
    if isinstance(by_limit, dict) and by_limit:
        for key, value in by_limit.items():
            if isinstance(key, str) and key.lower() == "codex":
                return value if isinstance(value, dict) else {}
        for value in by_limit.values():
            if not isinstance(value, dict):
                continue
            limit_id = value.get("limitId", value.get("rateLimitId"))
            if isinstance(limit_id, str) and limit_id.lower() == "codex":
                return value
        return {}
    legacy = raw.get("rateLimits")
    return legacy if isinstance(legacy, dict) else raw


def _window(snapshot, duration):
    for name in ("primary", "secondary"):
        window = snapshot.get(name)
        if not isinstance(window, dict):
            continue
        if _number(window.get("windowDurationMins")) != duration:
            continue
        used = _number(window.get("usedPercent"))
        reset = _number(window.get("resetsAt"))
        return {
            "remaining": None if used is None else max(0.0, min(100.0, 100.0 - used)),
            "resets_at": (
                int(reset)
                if reset is not None and reset >= 0 and reset.is_integer()
                else None
            ),
        }
    return {"remaining": None, "resets_at": None}


def _shape_quota(raw, fetched_at=None):
    if not isinstance(raw, dict):
        raise RuntimeError("Codex 返回了无效的额度数据，请稍后重试。")
    snapshot = _snapshot(raw)
    return {
        "fetched_at": time.time() if fetched_at is None else fetched_at,
        "five_hour": _window(snapshot, 300),
        "weekly": _window(snapshot, 10080),
    }


def _cancelled(cancel_event):
    return cancel_event is not None and cancel_event.is_set()


def _send(child, message):
    try:
        child.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        child.stdin.flush()
    except (OSError, ValueError):
        raise RuntimeError("Codex 额度读取服务连接已中断，请稍后重试。") from None


def _cleanup(child):
    try:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=0.4)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=0.4)
        else:
            child.wait(timeout=0.4)
    except (OSError, subprocess.TimeoutExpired):
        # SIGKILL may already have completed between poll/terminate/wait calls.
        try:
            child.kill()
            child.wait(timeout=0.4)
        except (OSError, subprocess.TimeoutExpired):
            pass
    finally:
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def _read_result(child, deadline, cancel_event):
    buffer = b""
    initialized = False
    _send(child, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {
                "name": "codex-quota-float", "title": "Codex Quota Float", "version": APP_VERSION,
            },
        },
    })
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout, selectors.EVENT_READ)
        while True:
            if _cancelled(cancel_event):
                raise RuntimeError("额度读取已取消。")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("读取 Codex 额度超时，请稍后重试。")
            events = selector.select(min(remaining, _CANCEL_CHECK_SECONDS))
            if not events:
                if child.poll() is not None:
                    raise RuntimeError("Codex 额度读取服务提前结束，请稍后重试。")
                continue
            try:
                chunk = os.read(child.stdout.fileno(), 65536)
            except OSError:
                raise RuntimeError("Codex 额度读取服务连接已中断，请稍后重试。") from None
            if not chunk:
                raise RuntimeError("Codex 额度读取服务提前结束，请稍后重试。")
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if len(line) > _MAX_LINE_BYTES:
                    raise RuntimeError("Codex 返回了无效的额度数据，请稍后重试。")
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if not isinstance(message, dict) or type(message.get("id")) is not int:
                    continue
                if message["id"] == 1 and not initialized:
                    if "error" in message or not isinstance(message.get("result"), dict):
                        raise RuntimeError("Codex 额度服务初始化失败，请重新打开 Codex 后重试。")
                    initialized = True
                    _send(child, {"jsonrpc": "2.0", "method": "initialized"})
                    _send(child, {
                        "jsonrpc": "2.0", "id": 2,
                        "method": "account/rateLimits/read", "params": {},
                    })
                elif message["id"] == 2 and initialized:
                    if "error" in message:
                        raise RuntimeError("无法读取账户额度，请确认 Codex 已登录后重试。")
                    return message.get("result")
            if len(buffer) > _MAX_LINE_BYTES:
                raise RuntimeError("Codex 返回了无效的额度数据，请稍后重试。")


def read_quota(timeout=15, cancel_event=None):
    """Return quota percentages, or raise a credential-free RuntimeError.

    ``cancel_event`` may be a threading.Event; cancellation stops and reaps the
    app-server child. Missing quota values are returned as None, never 100%.
    """
    duration = _number(timeout)
    if duration is None or duration <= 0:
        raise RuntimeError("读取额度的等待时间无效。")
    if _cancelled(cancel_event):
        raise RuntimeError("额度读取已取消。")
    binary = resolve_codex_binary()
    deadline = time.monotonic() + duration
    try:
        child = subprocess.Popen(
            [binary, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
    except (OSError, ValueError):
        raise RuntimeError("无法启动 Codex 额度读取服务，请确认 Codex 已安装。") from None
    try:
        return _shape_quota(_read_result(child, deadline, cancel_event))
    finally:
        _cleanup(child)
