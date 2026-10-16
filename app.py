#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Small, draggable quota indicator. This is an independent desktop window."""
import argparse
import json
import math
import os
import signal
import sys
import threading
import time
import tempfile
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
from runtime import APP_VERSION as VERSION, PROJECT_ROOT, log_path, settings_path

ROOT = PROJECT_ROOT
REFRESH_MS = 60_000
WIDTH, HEIGHT = 64, 128


class QuotaWorker(QtCore.QThread):
    result = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.cancel_event = threading.Event()

    def run(self):
        from quota_reader import read_quota
        try:
            self.result.emit(read_quota(cancel_event=self.cancel_event))
        except Exception as exc:
            self.error.emit(str(exc))


def color_for(remaining):
    if remaining is None:
        return QtGui.QColor("#98a2ad")
    return QtGui.QColor("#e05a55" if remaining < 20 else "#c28a22" if remaining <= 50 else "#248566")


def reset_countdown(resets_at, now=None):
    if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)):
        return "--:--"
    if not math.isfinite(resets_at):
        return "--:--"
    seconds = max(0, resets_at - (time.time() if now is None else now))
    # Round up so an unelapsed final minute does not appear as 0:00.
    minutes = math.ceil(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}"


class QuotaFloat(QtWidgets.QWidget):
    def __init__(self, demo=False):
        super().__init__()
        self.setWindowTitle("Codex 额度悬浮球")
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setFixedSize(WIDTH, HEIGHT)
        self.setCursor(QtCore.Qt.OpenHandCursor)
        self.demo = demo
        self.settings_file = settings_path()
        self.dark = False
        self.snapshot = None
        self.problem = None
        self.drag_offset = None
        self.worker = None
        self.closing = False
        self.reported_start = False
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.clock_timer = QtCore.QTimer(self)
        self.clock_timer.timeout.connect(self.update)
        self.clock_timer.start(REFRESH_MS)
        self.load_position()
        if demo:
            self.snapshot = {"fetched_at": time.time(), "five_hour": {"remaining": 68, "resets_at": time.time() + 3 * 3600 + 27 * 60},
                             "weekly": {"remaining": 80, "resets_at": None}}
            self.update_tooltip()
        else:
            self.timer.start(REFRESH_MS)
            QtCore.QTimer.singleShot(0, self.refresh)

    def load_position(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        x, y = screen.x() + 2, screen.bottom() - HEIGHT - 66
        try:
            source = self.settings_file
            if not source.exists():
                for legacy in (ROOT / "settings.json", ROOT / ".local-only" / "settings.json"):
                    if legacy.is_file():
                        source = legacy
                        break
            prefs = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(prefs, dict):
                raise ValueError("Invalid settings object")
            self.dark = prefs.get("dark") is True
            if isinstance(prefs.get("x"), int) and isinstance(prefs.get("y"), int):
                x, y = prefs["x"], prefs["y"]
        except (OSError, ValueError, TypeError):
            pass
        self.move(x, y)
        self.keep_on_screen()

    def keep_on_screen(self):
        screen = QtWidgets.QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        self.move(max(bounds.left(), min(self.x(), bounds.right() - WIDTH + 1)),
                  max(bounds.top(), min(self.y(), bounds.bottom() - HEIGHT + 1)))

    def save_position(self):
        if self.demo:
            return
        temporary = None
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.settings_file.parent,
                                             prefix=".settings-", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"x": self.x(), "y": self.y(), "dark": self.dark}, handle)
            temporary.replace(self.settings_file)
        except OSError:
            self.setToolTip(self.toolTip() + "\n位置保存失败，请检查目录写入权限。")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def refresh(self):
        if self.demo or self.closing or self.worker is not None:
            return
        self.worker = QuotaWorker(self)
        self.worker.result.connect(self.accept_snapshot)
        self.worker.error.connect(self.accept_error)
        self.worker.finished.connect(self.finish_refresh)
        self.update_tooltip()
        self.worker.start()

    def accept_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.problem = None
        self.update_tooltip()
        self.update()
        if not self.reported_start:
            print("额度读取成功。", flush=True)
            self.reported_start = True

    def accept_error(self, message):
        self.problem = message
        self.update_tooltip()
        self.update()
        if not self.reported_start:
            print("QUOTA_ERROR " + message, flush=True)

    def finish_refresh(self):
        self.worker.deleteLater()
        self.worker = None
        self.update_tooltip()

    def update_tooltip(self):
        lines = ["Codex 额度余量" + ("（示例数据）" if self.demo else "")]
        for key, label in (("five_hour", "5 小时"), ("weekly", "Week")):
            entry = (self.snapshot or {}).get(key) or {}
            value = entry.get("remaining")
            lines.append(f"{label}：" + (f"剩余 {value:g}%" if value is not None else "暂无数据"))
            if entry.get("resets_at"):
                reset = QtCore.QDateTime.fromSecsSinceEpoch(int(entry["resets_at"]))
                lines.append("  重置：" + reset.toString("MM-dd HH:mm"))
        if self.problem:
            lines.append("刷新失败，灰色数字为上次读数。" if self.snapshot else "暂时无法读取额度。")
            lines.append(self.problem)
        elif self.worker is not None:
            lines.append("正在刷新…")
        if self.snapshot:
            updated = QtCore.QDateTime.fromSecsSinceEpoch(int(self.snapshot["fetched_at"]))
            lines.append("更新：" + updated.toString("HH:mm:ss"))
        lines.append("拖动调整位置 · 右键打开菜单 · 每分钟刷新")
        self.setToolTip("\n".join(lines))

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        body = QtCore.QRectF(6, 5, 52, 116)
        # Soft shadow, kept inside the transparent window's bounds.
        for spread, alpha in ((4, 3), (3, 5), (2, 7), (1, 9)):
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(body.adjusted(-spread, -spread + 2, spread, spread + 2), 26 + spread, 26 + spread)
        painter.setBrush(QtGui.QColor("#26292c" if self.dark else "#fcfdfc"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#464b4f" if self.dark else "#dde3df"), 1))
        painter.drawRoundedRect(body, 26, 26)
        painter.setPen(QtGui.QPen(QtGui.QColor("#44494c" if self.dark else "#e9edea"), 1))
        painter.drawLine(QtCore.QPointF(20, 63), QtCore.QPointF(44, 63))
        first = (self.snapshot or {}).get("five_hour") or {}
        self.paint_quota(painter, "five_hour", reset_countdown(first.get("resets_at")), 13)
        self.paint_quota(painter, "weekly", "Week", 68)
        painter.end()

    def paint_quota(self, painter, key, label, top):
        entry = (self.snapshot or {}).get(key) or {}
        remaining = entry.get("remaining")
        stale = bool(self.problem and self.snapshot)
        color = QtGui.QColor("#98a2ad") if stale else color_for(remaining)
        small = QtGui.QFont("Noto Sans CJK SC", 8)
        small.setPixelSize(10)
        painter.setFont(small)
        painter.setPen(QtGui.QColor("#bfc8c2" if self.dark else "#6b776f"))
        painter.drawText(QtCore.QRectF(6, top, 52, 14), QtCore.Qt.AlignCenter, label)
        battery = QtCore.QRectF(16, top + 17, 30, 11)
        painter.setPen(QtGui.QPen(color, 1.2))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(battery, 2.5, 2.5)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QtCore.QRectF(47, top + 20, 2, 5), 1, 1)
        if remaining is not None and remaining > 0:
            painter.drawRoundedRect(QtCore.QRectF(18, top + 19, 26 * min(100, max(0, remaining)) / 100, 7), 1, 1)
        elif remaining is None:
            painter.setPen(QtGui.QPen(color, 1))
            painter.drawLine(QtCore.QPointF(26, top + 22.5), QtCore.QPointF(35, top + 22.5))
        large = QtGui.QFont("Noto Sans CJK SC", 9, QtGui.QFont.DemiBold)
        large.setPixelSize(12)
        painter.setFont(large)
        painter.setPen(color if stale else QtGui.QColor("#edf2ee" if self.dark else "#25372c"))
        value = "—" if remaining is None else f"{remaining:.0f}%"
        painter.drawText(QtCore.QRectF(6, top + 30, 52, 17), QtCore.Qt.AlignCenter, value)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag_offset = event.globalPos() - self.pos()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & QtCore.Qt.LeftButton:
            self.move(event.globalPos() - self.drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self.drag_offset is not None:
            self.drag_offset = None
            self.setCursor(QtCore.Qt.OpenHandCursor)
            self.keep_on_screen()
            self.save_position()
            event.accept()

    def contextMenuEvent(self, event):
        menu = QtWidgets.QMenu(self)
        refresh = menu.addAction("立即刷新")
        refresh.setEnabled(not self.demo and self.worker is None)
        refresh.triggered.connect(self.refresh)
        theme = menu.addAction("深色外观")
        theme.setCheckable(True)
        theme.setChecked(self.dark)
        theme.triggered.connect(self.toggle_theme)
        menu.addSeparator()
        menu.addAction("退出悬浮球", self.close)
        menu.exec_(event.globalPos())

    def toggle_theme(self, checked):
        self.dark = checked
        self.save_position()
        self.update()

    def closeEvent(self, event):
        self.closing = True
        self.timer.stop()
        self.clock_timer.stop()
        self.save_position()
        if self.worker:
            self.worker.cancel_event.set()
            self.worker.wait(2500)
            if self.worker.isRunning():
                event.ignore()
                QtCore.QTimer.singleShot(200, self.close)
                return
        event.accept()

        # Qt.Tool windows do not reliably trigger quitOnLastWindowClosed.
        # End the event loop explicitly after the worker has stopped.
        QtCore.QTimer.singleShot(0, QtWidgets.QApplication.instance().quit)


def main():
    parser = argparse.ArgumentParser(description="Codex 五小时 / 周额度悬浮球")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--demo", action="store_true", help="离线示例，不读取真实额度")
    parser.add_argument("--render", type=Path, help="离线导出组件 PNG，不打开桌面窗口")
    parser.add_argument("--check", action="store_true", help="读取一次真实额度后退出，不打开窗口")
    parser.add_argument("--background", action="store_true", help="后台启动，日志写入用户的 XDG 状态目录")
    parser.add_argument("--status", action="store_true", help="检查悬浮球是否正在运行")
    args = parser.parse_args()
    if args.status:
        from PyQt5 import QtNetwork
        status_app = QtCore.QCoreApplication(sys.argv[:1])
        probe = QtNetwork.QLocalSocket()
        probe.connectToServer(f"codex-quota-float-{os.getuid()}")
        running = probe.waitForConnected(1000)
        probe.disconnectFromServer()
        print(json.dumps({"running": running}))
        return
    if args.check:
        from quota_reader import read_quota
        try:
            print(json.dumps(read_quota(), ensure_ascii=False))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return
    if args.background:
        import subprocess
        child_args = [sys.executable, str(ROOT / "app.py")]
        if args.demo:
            child_args.append("--demo")
        destination = log_path()
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with destination.open("ab") as log:
            child = subprocess.Popen(child_args, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     cwd=ROOT, start_new_session=True, close_fds=True)
        print(f"已启动悬浮球，进程 {child.pid}。")
        return
    if args.render:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("codex-quota-float")
    app.setQuitOnLastWindowClosed(True)
    window = QuotaFloat(demo=args.demo or bool(args.render))
    if args.render:
        args.render.parent.mkdir(parents=True, exist_ok=True)
        pixmap = QtGui.QPixmap(WIDTH * 4, HEIGHT * 4)
        pixmap.setDevicePixelRatio(4)
        pixmap.fill(QtCore.Qt.transparent)
        window.render(pixmap)
        if not pixmap.save(str(args.render)):
            raise SystemExit("无法保存预览图")
        return
    # One visible instance per user, using a local socket rather than an exposed port.
    from PyQt5 import QtNetwork
    name = f"codex-quota-float-{os.getuid()}"
    socket = QtNetwork.QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(200):
        socket.disconnectFromServer()
        return
    QtNetwork.QLocalServer.removeServer(name)
    server = QtNetwork.QLocalServer(app)
    if not server.listen(name):
        raise SystemExit("悬浮球启动失败：无法创建本地单实例锁。")
    def existing_connection():
        connection = server.nextPendingConnection()
        if connection:
            connection.disconnectFromServer()
            connection.deleteLater()
        window.show()
        window.raise_()
    server.newConnection.connect(existing_connection)
    signal.signal(signal.SIGTERM, lambda *_: window.close())
    signal.signal(signal.SIGINT, lambda *_: window.close())
    # Let Python handle termination signals even while Qt is idle.
    signal_timer = QtCore.QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(250)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    sys.exit(main() or 0)
