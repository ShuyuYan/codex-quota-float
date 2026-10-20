#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Small, draggable quota indicator. This is an independent desktop window."""
import argparse
import hashlib
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
from runtime import (APP_VERSION as VERSION, PROJECT_ROOT, ensure_output_streams,
                     launch_command, launch_directory, log_path, settings_path)

ROOT = PROJECT_ROOT
REFRESH_MS = 60_000
WIDTH, HEIGHT = 64, 128
FONT_FAMILY = "Microsoft YaHei UI" if sys.platform == "win32" else "Noto Sans CJK SC"


def instance_name():
    """Keep each user's local socket private and stable across project copies."""
    if sys.platform == "win32":
        identity = hashlib.sha256(str(Path.home()).casefold().encode("utf-8")).hexdigest()[:24]
    else:
        identity = str(os.getuid())
    return f"codex-quota-float-{identity}"


def start_background(demo=False, smoke_test=None):
    import subprocess
    process_options = {"start_new_session": True}
    if sys.platform == "win32":
        process_options = {"creationflags": subprocess.CREATE_NO_WINDOW}
    child_args = launch_command()
    if demo:
        child_args.append("--demo")
    if smoke_test:
        child_args.extend(["--smoke-test", str(smoke_test)])
    destination = log_path()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    if getattr(sys, "frozen", False):
        # A detached one-file child must own its extracted files after this
        # process exits, instead of sharing its parent's temporary bundle.
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    with destination.open("ab") as log:
        child = subprocess.Popen(child_args, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 cwd=launch_directory(), env=environment, close_fds=True, **process_options)
    return child.pid


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


def reset_date(resets_at):
    if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)):
        return "--.--"
    if not math.isfinite(resets_at) or resets_at <= 0:
        return "--.--"
    try:
        reset = QtCore.QDateTime.fromSecsSinceEpoch(int(resets_at))
    except (OverflowError, ValueError):
        return "--.--"
    return reset.toString("MM.dd") if reset.isValid() else "--.--"


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
                             "weekly": {"remaining": 80, "resets_at": time.time() + 5 * 24 * 3600}}
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
        weekly = (self.snapshot or {}).get("weekly") or {}
        self.paint_quota(painter, "five_hour", reset_countdown(first.get("resets_at")), 13)
        self.paint_quota(painter, "weekly", reset_date(weekly.get("resets_at")), 68)
        painter.end()

    def paint_quota(self, painter, key, label, top):
        entry = (self.snapshot or {}).get(key) or {}
        remaining = entry.get("remaining")
        stale = bool(self.problem and self.snapshot)
        color = QtGui.QColor("#98a2ad") if stale else color_for(remaining)
        small = QtGui.QFont(FONT_FAMILY, 8)
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
        large = QtGui.QFont(FONT_FAMILY, 9, QtGui.QFont.DemiBold)
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
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            menu.addSeparator()
            menu.addAction("创建桌面快捷方式", self.install_shortcuts)
        menu.addSeparator()
        menu.addAction("关于与许可证", self.show_about)
        menu.addAction("退出悬浮球", self.close)
        menu.exec_(event.globalPos())

    def show_about(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("关于 Codex 额度悬浮球")
        dialog.resize(620, 440)
        layout = QtWidgets.QVBoxLayout(dialog)
        description = QtWidgets.QLabel(
            f"<b>Codex Quota Float {VERSION}</b><br>"
            "社区项目，与 OpenAI 无隶属关系。采用 GPL-3.0-only，按许可证提供且不作担保。<br>"
            "使用 Python、PyQt5 和 Qt。允许按相应许可修改和再发布。<br>"
            '<a href="https://github.com/ShuyuYan/codex-quota-float/releases">下载对应源码与发布文件</a>')
        description.setOpenExternalLinks(True)
        description.setWordWrap(True)
        layout.addWidget(description)
        tabs = QtWidgets.QTabWidget()
        files = [(ROOT / "LICENSE", "项目许可"), (ROOT / "THIRD_PARTY_NOTICES.md", "第三方说明"),
                 (ROOT / "DEPENDENCY_SOURCES.md", "依赖源码")]
        if (ROOT / "licenses").is_dir():
            files.extend((path, path.stem) for path in sorted((ROOT / "licenses").iterdir()) if path.is_file())
        for path, label in files:
            if path.is_file():
                text = QtWidgets.QPlainTextEdit()
                text.setReadOnly(True)
                text.setPlainText(path.read_text(encoding="utf-8", errors="replace"))
                tabs.addTab(text, label)
        layout.addWidget(tabs)
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec_()

    def install_shortcuts(self):
        from windows_shortcut import main as install
        if install(["--force"]) == 0:
            QtWidgets.QMessageBox.information(
                self, "快捷方式已创建", "已创建桌面和开始菜单快捷方式。\n移动 EXE 后，请再次创建快捷方式。")
        else:
            QtWidgets.QMessageBox.warning(
                self, "快捷方式创建失败", f"请检查目录写入权限，详细信息见：\n{log_path()}")

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
    ensure_output_streams()
    arguments = sys.argv[1:]
    if arguments[:1] in (["--launch"], ["--install-shortcut"]):
        from windows_shortcut import main as shortcut_main
        return shortcut_main(arguments if arguments[0] == "--launch" else arguments[1:])
    parser = argparse.ArgumentParser(description="Codex 五小时 / 周额度悬浮球")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--demo", action="store_true", help="离线示例，不读取真实额度")
    parser.add_argument("--render", type=Path, help="离线导出组件 PNG，不打开桌面窗口")
    parser.add_argument("--check", action="store_true", help="读取一次真实额度后退出，不打开窗口")
    parser.add_argument("--background", action="store_true", help="后台启动，日志写入用户的日志目录")
    parser.add_argument("--status", action="store_true", help="检查悬浮球是否正在运行")
    parser.add_argument("--output", type=Path, help="将 --status / --check 的结果写入 UTF-8 文件")
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.smoke_test:
        args.demo = True
    if args.output and not (args.status or args.check):
        parser.error("--output 需要与 --status 或 --check 一起使用")
    def report(message, error=False):
        if args.output:
            try:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(message + "\n", encoding="utf-8")
            except OSError:
                print("无法保存检查结果，请检查输出目录写入权限。", file=sys.stderr)
                return False
        else:
            print(message, file=sys.stderr if error else sys.stdout)
        return True
    if args.status:
        from PyQt5 import QtNetwork
        status_app = QtCore.QCoreApplication(sys.argv[:1])
        probe = QtNetwork.QLocalSocket()
        probe.connectToServer(instance_name())
        running = probe.waitForConnected(1000)
        probe.disconnectFromServer()
        return 0 if report(json.dumps({"running": running})) else 1
    if args.check:
        from quota_reader import read_quota
        try:
            if not report(json.dumps(read_quota(), ensure_ascii=False)):
                return 1
        except RuntimeError as exc:
            report(str(exc), error=True)
            return 1
        return
    if args.background:
        try:
            pid = start_background(demo=args.demo, smoke_test=args.smoke_test)
        except OSError:
            print("后台启动失败，请检查 Python 环境和日志目录写入权限。", file=sys.stderr)
            return 1
        print(f"已启动悬浮球，进程 {pid}。")
        return
    if args.render:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps)
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("codex-quota-float")
    app.setWindowIcon(QtGui.QIcon(str(ROOT / "quota-icon.svg")))
    app.setQuitOnLastWindowClosed(True)
    if args.render and sys.platform == "win32":
        # Qt's offscreen plugin does not enumerate Windows system fonts.
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "segoeuib.ttf"):
            if (fonts / filename).is_file():
                QtGui.QFontDatabase.addApplicationFont(str(fonts / filename))
    if args.render:
        window = QuotaFloat(demo=True)
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
    name = instance_name()
    # Named pipe servers are not exclusive on Windows. Hold an OS-backed lock
    # as well, so simultaneous launches cannot both become the visible instance.
    lock_directory = log_path().parent
    try:
        lock_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        raise SystemExit("悬浮球启动失败：无法创建用户运行目录。") from None
    instance_lock = QtCore.QLockFile(str(lock_directory / f"{name}.lock"))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(0):
        if instance_lock.error() != QtCore.QLockFile.LockFailedError:
            raise SystemExit("悬浮球启动失败：无法创建本地单实例锁。")
        probe = QtNetwork.QLocalSocket()
        probe.connectToServer(name)
        probe.waitForConnected(1000)
        probe.disconnectFromServer()
        return
    socket = QtNetwork.QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(200):
        socket.disconnectFromServer()
        return
    QtNetwork.QLocalServer.removeServer(name)
    server = QtNetwork.QLocalServer(app)
    server.setSocketOptions(QtNetwork.QLocalServer.UserAccessOption)
    if not server.listen(name):
        raise SystemExit("悬浮球启动失败：无法创建本地单实例锁。")
    window = QuotaFloat(demo=args.demo)
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
    if args.smoke_test:
        QtCore.QTimer.singleShot(1500, window.close)
    result = app.exec_()
    if args.smoke_test:
        args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
        marker = args.smoke_test.with_suffix(args.smoke_test.suffix + ".tmp")
        marker.write_text(json.dumps({"version": VERSION, "frozen": bool(getattr(sys, "frozen", False)),
                                      "demo": window.demo, "closed": window.closing,
                                      "pid": os.getpid(), "parent_pid": os.getppid()}), encoding="utf-8")
        marker.replace(args.smoke_test)
    return result


if __name__ == "__main__":
    sys.exit(main() or 0)
