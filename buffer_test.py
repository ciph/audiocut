"""Controlled PCM buffer comparison; intentionally separate from QMediaPlayer."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import tempfile
import time
import uuid

from PySide6.QtCore import QByteArray, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from audio_diagnostics import format_details
from core import _run, open_audio, resolve_tool


BUFFER_SIZES = (110, 250, 500)


def prepare_pcm(path, fmt):
    """Decode once, capped at 45 seconds, so all trials use identical bytes."""
    formats = {QAudioFormat.SampleFormat.UInt8: "u8", QAudioFormat.SampleFormat.Int16: "s16le",
               QAudioFormat.SampleFormat.Int32: "s32le", QAudioFormat.SampleFormat.Float: "f32le"}
    if fmt.sampleFormat() not in formats or not 8000 <= fmt.sampleRate() <= 192000 or not 1 <= fmt.channelCount() <= 8:
        raise ValueError("该设备格式不支持缓冲对照测试。")
    with tempfile.TemporaryDirectory(prefix="audiocut-buffer-") as folder:
        info = open_audio(Path(path), Path(folder))
        pcm = _run([resolve_tool("ffmpeg"), "-v", "error", "-nostdin", "-i", str(info.path),
                    "-t", "45", "-map", "0:a:0", "-vn", "-ar", str(fmt.sampleRate()),
                    "-ac", str(fmt.channelCount()), "-f", formats[fmt.sampleFormat()], "pipe:1"], timeout=120)
    if not pcm or len(pcm) % fmt.bytesPerFrame():
        raise ValueError("未能生成完整的 PCM 音频帧。")
    return QByteArray(pcm), hashlib.sha256(pcm).hexdigest()


class BufferProbe(QObject):
    finished = Signal(dict)

    def __init__(self, diagnostics, device=None, parent=None):
        super().__init__(parent)
        self.log = diagnostics
        self.device = device if device is not None else QMediaDevices.defaultAudioOutput()
        self.format = self.device.preferredFormat()
        self.pcm = QByteArray()
        self.pcm_hash = ""
        self.sink = None
        self.running = False
        self.volume = 0.8
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.pump)
        self.timer.setInterval(10)
        self.log.device_event(self.device)

    def start(self, buffer_ms):
        if buffer_ms not in BUFFER_SIZES or self.pcm.isEmpty():
            raise ValueError("请先打开音频，并选择 110、250 或 500 ms。")
        if self.device.isNull() or not self.device.isFormatSupported(self.format):
            raise ValueError("输出设备不可用或格式不受支持。")
        self.stop("switch")
        self.trial = uuid.uuid4().hex[:8]
        self.requested_ms = buffer_ms
        self.offset = 0
        self.primed = False
        self.empty_observations = self.idle_events = 0
        self.max_gap_ms = 0.0
        self.min_queued_ms = float("inf")
        self.started = self.last_pump = self.last_sample = time.perf_counter()
        self.sink = QAudioSink(self.device, self.format, self)
        self.sink.setVolume(self.volume)
        self.sink.setBufferSize(self.format.bytesForDuration(buffer_ms * 1000))
        self.running = True
        self.sink.stateChanged.connect(self._state_changed)
        self.io = self.sink.start()
        self.actual_bytes = self.sink.bufferSize()
        self.actual_ms = self.format.durationForBytes(self.actual_bytes) / 1000
        self.native_frames = self.sink.nativePeriodFrameCount()
        self.log.record("trial_start", trial=self.trial, requested_ms=buffer_ms, actual_ms=self.actual_ms,
                        actual_bytes=self.actual_bytes, native_period_frames=self.native_frames,
                        format=format_details(self.format), pcm_sha256=self.pcm_hash, pcm_bytes=self.pcm.size(),
                        volume=self.volume, feed_interval_ms=10, chain="PCM -> QAudioSink push -> fixed device")
        if self.io is None or self.sink.error() != QtAudio.Error.NoError:
            error = self.sink.error().name
            self.stop("error")
            raise RuntimeError("无法打开音频输出：" + error)
        self.pump()
        self.timer.start()

    def pump(self):
        if not self.running:
            return
        now = time.perf_counter()
        gap_ms = (now - self.last_pump) * 1000
        self.last_pump = now
        free = self.sink.bytesFree()
        queued_ms = self.format.durationForBytes(max(0, self.actual_bytes - free)) / 1000
        pending = self.offset < self.pcm.size()
        if self.primed and pending:
            self.max_gap_ms = max(self.max_gap_ms, gap_ms)
            self.min_queued_ms = min(self.min_queued_ms, queued_ms)
            if free == self.actual_bytes:
                self.empty_observations += 1
                self.log.record("buffer_empty_observed", trial=self.trial, refill_gap_ms=gap_ms,
                                position_ms=self.position_ms(), detail="Ringbuffer empty; host/device may still hold audio")
            if gap_ms > 30:
                self.log.record("refill_delay", trial=self.trial, gap_ms=gap_ms, queued_ms=queued_ms)
        count = min(free, self.pcm.size() - self.offset)
        count -= count % self.format.bytesPerFrame()
        if count > 0:
            written = self.io.write(self.pcm.mid(self.offset, count))
            if written < 0 or written % self.format.bytesPerFrame():
                self.stop("write_error")
                return
            self.offset += written
            self.primed |= written > 0
        if now - self.last_sample >= 0.25:
            self.last_sample = now
            self.log.record("buffer_sample", trial=self.trial, queued_ms=queued_ms,
                            refill_gap_ms=gap_ms, submitted_bytes=self.offset,
                            processed_us=self.sink.processedUSecs(), state=self.sink.state().name)
        if self.sink.error() != QtAudio.Error.NoError:
            self.stop("error")
        elif not pending and self.sink.state() == QtAudio.State.IdleState:
            self.stop("eof")

    @Slot()
    def _state_changed(self):
        if not self.running:
            return
        # Qt 6.12's binding cannot convert this signal's legacy QAudio::State argument.
        # Read current state instead; short transitions may be missed while the UI is blocked.
        state = self.sink.state()
        self.log.record("sink_state", trial=self.trial, state=state.name, submitted_bytes=self.offset,
                        error=self.sink.error().name)
        if state == QtAudio.State.IdleState and self.primed and self.offset < self.pcm.size():
            self.idle_events += 1
            self.log.record("sink_starved", trial=self.trial, position_ms=self.position_ms())

    def position_ms(self):
        return self.sink.processedUSecs() / 1000 if self.sink else 0

    def mark(self):
        self.log.record("heard_glitch", trial=self.trial if self.running else None,
                        position_ms=self.position_ms(), running=self.running)

    def stop(self, reason="user"):
        self.timer.stop()
        if self.running:
            self.running = False
            summary = dict(trial=self.trial, requested_ms=self.requested_ms, actual_ms=self.actual_ms,
                           native_period_frames=self.native_frames, pcm_sha256=self.pcm_hash, volume=self.volume,
                           reason=reason, elapsed_ms=(time.perf_counter() - self.started) * 1000,
                           max_refill_gap_ms=self.max_gap_ms,
                           min_queued_ms=None if self.min_queued_ms == float("inf") else self.min_queued_ms,
                           empty_observations=self.empty_observations, starvation_events=self.idle_events)
            self.log.record("trial_end", **summary)
            self.finished.emit(summary)
        if self.sink is not None:
            self.sink.reset()
            self.sink.deleteLater()
            self.sink = None


class BufferTestWindow(QWidget):
    def __init__(self, diagnostics):
        super().__init__()
        self.setWindowTitle("轻剪 · 音频缓冲对照")
        self.resize(680, 330)
        self.log = diagnostics
        self.probe = BufferProbe(diagnostics, parent=self)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.future = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        note = QLabel("先打开音频，再依次试听 A / B / C；每次从同一位置播放前 45 秒。\n听到爆点时按 Ctrl+M 标记。请暂停其他播放器。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.open_button = QPushButton("打开音频")
        self.open_button.clicked.connect(self.choose)
        layout.addWidget(self.open_button)
        row = QHBoxLayout()
        self.play_buttons = []
        for label, milliseconds in zip("ABC", BUFFER_SIZES):
            button = QPushButton(f"{label} · {milliseconds} ms")
            button.clicked.connect(lambda checked=False, value=milliseconds: self.play(value))
            button.setEnabled(False)
            self.play_buttons.append(button)
            row.addWidget(button)
        layout.addLayout(row)
        controls = QHBoxLayout()
        stop = QPushButton("停止")
        stop.clicked.connect(lambda: self.probe.stop())
        mark = QPushButton("听到爆点 · 标记")
        mark.clicked.connect(self.mark)
        controls.addWidget(stop)
        controls.addWidget(mark)
        layout.addLayout(controls)
        self.shortcut = QShortcut(QKeySequence("Ctrl+M"), self)
        self.shortcut.activated.connect(self.mark)
        self.status = QLabel("等待打开音频")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        details = QLabel("对照使用固定 PCM 和输出设备；数值为请求缓冲，播放后显示实际值。\n此窗口用于验证缓冲容错，不等同于正式播放器的内部调度。\n日志：" + str(diagnostics.path))
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(details)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.prepared)
        self.probe.finished.connect(self.completed)

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开用于对照的音频")
        if path:
            self.load_path(path)

    def load_path(self, path):
        if self.future:
            return
        self.probe.stop("new_source")
        self.source_name = Path(path).name
        self.probe.pcm = QByteArray()
        self.open_button.setEnabled(False)
        for button in self.play_buttons:
            button.setEnabled(False)
        self.status.setText("正在准备同一份 PCM 音频…")
        self.log.record("probe_source", path=str(path))
        self.future = self.executor.submit(prepare_pcm, path, QAudioFormat(self.probe.format))
        self.poll.start(50)

    def prepared(self):
        if not self.future or not self.future.done():
            return
        self.poll.stop()
        try:
            self.probe.pcm, self.probe.pcm_hash = self.future.result()
            for button in self.play_buttons:
                button.setEnabled(True)
            self.status.setText("准备就绪 · " + self.source_name + " · " + self.probe.device.description())
            self.setWindowTitle(self.source_name + " — 轻剪 · 音频缓冲对照")
        except Exception as exc:
            self.log.record("prepare_error", message=str(exc))
            self.status.setText("准备失败：" + str(exc))
        self.future = None
        self.open_button.setEnabled(True)

    def play(self, milliseconds):
        try:
            self.probe.start(milliseconds)
            self.status.setText(f"正在播放 · 请求 {milliseconds} ms / 实际 {self.probe.actual_ms:g} ms")
        except Exception as exc:
            self.log.record("probe_error", message=str(exc))
            self.status.setText(str(exc))

    def mark(self):
        self.probe.mark()
        self.status.setText("已记录爆点时间，请继续试听或切换下一组。")

    def completed(self, result):
        self.status.setText(f"本轮结束 · 缓冲见底观测 {result['empty_observations']} 次；这不等于可闻爆点次数。")

    def closeEvent(self, event):
        if self.future:
            self.status.setText("正在准备音频，请完成后再关闭。")
            event.ignore()
            return
        self.probe.stop("close")
        self.executor.shutdown(wait=False)
        event.accept()
