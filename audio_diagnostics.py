"""Opt-in telemetry. Enable QT_FORCE_STDERR_LOGGING before Qt initializes."""

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
import uuid

from PySide6.QtCore import QObject, QLoggingCategory, QStandardPaths, Qt, QTimer, qInfo, qSetMessagePattern, qVersion
from PySide6.QtGui import QKeySequence, QShortcut


class _LogFile(RotatingFileHandler):
    def handleError(self, record):
        raise OSError("诊断日志写入失败") from sys.exc_info()[1]


def format_details(fmt):
    return dict(rate=fmt.sampleRate(), channels=fmt.channelCount(), sample_format=fmt.sampleFormat().name)


def _stderr_pipe():
    if os.name != "nt":
        return os.pipe()
    import ctypes
    from ctypes import wintypes
    import msvcrt
    read_handle, write_handle = wintypes.HANDLE(), wintypes.HANDLE()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreatePipe.argtypes = (ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p, wintypes.DWORD)
    if not kernel.CreatePipe(ctypes.byref(read_handle), ctypes.byref(write_handle), None, 65536):
        raise ctypes.WinError(ctypes.get_last_error())
    return (msvcrt.open_osfhandle(read_handle.value, os.O_RDONLY | os.O_BINARY),
            msvcrt.open_osfhandle(write_handle.value, os.O_WRONLY | os.O_BINARY))


def _native_stderr_descriptor():
    if os.name != "nt":
        return 2
    import ctypes
    # Load the system CRT already used by Python/Qt, not a renamed PyInstaller copy.
    crt = ctypes.CDLL(str(Path(os.environ["SystemRoot"]) / "System32" / "ucrtbase.dll"))
    crt.__acrt_iob_func.argtypes = (ctypes.c_uint,)
    crt.__acrt_iob_func.restype = ctypes.c_void_p
    crt._fileno.argtypes = (ctypes.c_void_p,)
    stream = crt.__acrt_iob_func(2)
    if crt._fileno(stream) < 0:
        # Windowed PyInstaller apps have a detached C stderr FILE, not just a missing handle.
        result = ctypes.c_void_p()
        crt.freopen_s.argtypes = (ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)
        if crt.freopen_s(ctypes.byref(result), b"NUL", b"w", stream):
            raise OSError("无法初始化原生日志输出。")
    descriptor = crt._fileno(stream)
    if descriptor < 0:
        raise OSError("原生日志输出不可用。")
    return descriptor


def _sync_stderr_handle(descriptor):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.SetStdHandle.argtypes = (wintypes.DWORD, wintypes.HANDLE)
        if not kernel.SetStdHandle(wintypes.DWORD(-12), msvcrt.get_osfhandle(descriptor)):
            raise ctypes.WinError(ctypes.get_last_error())


class AudioDiagnostics(QObject):
    def __init__(self, directory=None, mode="player", parent=None, capture_qt=True):
        super().__init__(parent)
        if capture_qt:
            self.stderr_descriptor = _native_stderr_descriptor()
        directory = Path(directory or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation)) / "audio-diagnostics"
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8] + ".jsonl")
        self.handler = _LogFile(self.path, maxBytes=5_000_000, backupCount=2, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.queue = queue.Queue(maxsize=4096)
        self.origin = time.perf_counter()
        self.dropped = 0
        self.closed = False
        self.player = None
        self.writer_error = None
        self.stopping = threading.Event()
        self.writer = threading.Thread(target=self._write, name="audio-diagnostic-log", daemon=True)
        self.writer.start()
        self.capture_qt = capture_qt
        self.old_rules = os.environ.get("QT_LOGGING_RULES", "")
        if capture_qt:
            # Python message handlers can deadlock against QMediaPlayer.stop()'s native thread join.
            # Qt writes to a native pipe instead; a separate reader performs Python logging.
            self.saved_stderr = os.dup(self.stderr_descriptor)
            read_fd, write_fd = _stderr_pipe()
            os.dup2(write_fd, self.stderr_descriptor)
            os.close(write_fd)
            _sync_stderr_handle(self.stderr_descriptor)
            self.old_force_stderr = os.environ.get("QT_FORCE_STDERR_LOGGING")
            os.environ["QT_FORCE_STDERR_LOGGING"] = "1"
            self.old_pattern = os.environ.get("QT_MESSAGE_PATTERN", "%{if-category}%{category}: %{endif}%{message}")
            qSetMessagePattern("AUDIOCUT_QT|%{time process}|%{threadid}|%{type}|%{category}|%{message}")
            self.reader = threading.Thread(target=self._read_qt, args=(read_fd,), name="qt-log-reader", daemon=True)
            self.reader.start()
            QLoggingCategory.setFilterRules(self.old_rules + "\nqt.multimedia.ffmpeg.audiorenderer.debug=true")
        self.record("session_start", utc=datetime.now(timezone.utc).isoformat(), qt=qVersion(), mode=mode,
                    backend_requested=os.environ.get("QT_MEDIA_BACKEND", "auto"),
                    limits="UI/media events are not hardware underrun counters; no audio samples recorded")
        if capture_qt:
            qInfo(f"AudioCut clock anchor: session_ms={(time.perf_counter() - self.origin) * 1000:.3f}")
        self.last_tick = self.last_sample = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

    def record(self, event, **fields):
        if self.closed:
            return
        item = dict(t_ms=round((time.perf_counter() - self.origin) * 1000, 3),
                    event=event, thread=threading.get_ident(), **fields)
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def _write(self):
        try:
            while not self.stopping.is_set() or not self.queue.empty():
                try:
                    item = self.queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                line = json.dumps(item, ensure_ascii=False)
                record = logging.LogRecord("audio-diagnostics", logging.INFO, "", 0, line, (), None)
                self.handler.emit(record)
        except Exception as exc:
            self.writer_error = str(exc)
        finally:
            self.handler.close()

    def _read_qt(self, descriptor):
        header = re.compile(r"^AUDIOCUT_QT\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|(.*)$")
        context = {}
        not_first = False
        with os.fdopen(descriptor, "rb") as stream:
            for raw in stream:
                line = raw.decode("utf-8", errors="replace").rstrip()
                match = header.match(line)
                if match:
                    native_time, native_thread, level, category, line = match.groups()
                    context = dict(native_process_time=native_time.strip(), native_thread=native_thread,
                                   level=level, category=category)
                    not_first = False
                self.record("qt_message", message=line[:8192], **context)
                if "First frame: false" in line:
                    not_first = True
                if not_first and "Audio sink state:" in line and "IdleState" in line:
                    self.record("renderer_idle_candidate", **context,
                                detail="Candidate only; native_process_time is Qt emission time; correlate with transport and marks")

    def attach_player(self, window, player, audio):
        self.window = window
        self.player, self.audio = player, audio
        player.mediaStatusChanged.connect(lambda state: self.record("media_status", state=state.name, position_ms=player.position()))
        player.playbackStateChanged.connect(lambda state: self.record("playback_state", state=state.name, position_ms=player.position()))
        player.bufferProgressChanged.connect(lambda value: self.record("media_buffer_progress", value=value))
        player.sourceChanged.connect(lambda url: self.record("source", path=url.toLocalFile()))
        player.errorOccurred.connect(lambda error, message: self.record("player_error", error=error.name, message=message))
        audio.deviceChanged.connect(lambda: self.device_event(audio.device()))
        self.device_event(audio.device())
        self.mark_shortcut = QShortcut(QKeySequence("Ctrl+M"), window)
        def mark():
            self.record("heard_glitch", position_ms=player.position(), state=player.playbackState().name)
            window.status.setText("已标记听到爆点的位置 · 诊断日志：" + str(self.path))
        self.mark_shortcut.activated.connect(mark)
        window.status.setText("播放诊断已开启 · 听到爆点按 Ctrl+M · " + str(self.path))
        def title_changed(title):
            if not title.endswith(" · 播放诊断"):
                window.setWindowTitle(title + " · 播放诊断")
        window.windowTitleChanged.connect(title_changed)
        title_changed(window.windowTitle())

    def device_event(self, device):
        self.record("output_device", name=device.description(), device_id=bytes(device.id()).hex(),
                    preferred_format=format_details(device.preferredFormat()))

    def _tick(self):
        now = time.perf_counter()
        interval = (now - self.last_tick) * 1000
        self.last_tick = now
        if interval > 75:
            self.record("ui_timer_delay", interval_ms=round(interval, 3), expected_ms=50)
        if self.writer_error and self.player is not None:
            self.window.status.setText("诊断日志写入失败：" + self.writer_error)
        if self.player is not None and now - self.last_sample >= 1:
            self.last_sample = now
            self.record("player_sample", position_ms=self.player.position(), state=self.player.playbackState().name,
                        media_status=self.player.mediaStatus().name, media_buffer_progress=self.player.bufferProgress(),
                        muted=self.audio.isMuted(), volume=self.audio.volume(), dropped_records=self.dropped)

    def close(self):
        if self.closed:
            return
        self.timer.stop()
        if self.capture_qt:
            QLoggingCategory.setFilterRules(self.old_rules)
            qSetMessagePattern(self.old_pattern)
            os.dup2(self.saved_stderr, self.stderr_descriptor)
            os.close(self.saved_stderr)
            _sync_stderr_handle(self.stderr_descriptor)
            if self.old_force_stderr is None:
                os.environ.pop("QT_FORCE_STDERR_LOGGING", None)
            else:
                os.environ["QT_FORCE_STDERR_LOGGING"] = self.old_force_stderr
            self.reader.join(timeout=3)
        self.record("session_end", dropped_records=self.dropped)
        self.closed = True
        self.stopping.set()
        self.writer.join(timeout=3)
