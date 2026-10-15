from __future__ import annotations

import logging
import queue
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from core import CURVES, Edit, export_audio, open_audio, probe, render_preview, waveform
from theme import apply_theme, icon
from widgets import SaveDialog, Waveform, time_text


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("轻剪 AudioCut")
        self.setWindowIcon(icon("music"))
        self.resize(980, 590)
        self.setMinimumSize(800, 530)
        self.setAcceptDrops(True)
        self.info = None
        self.edit = None
        self.editing = False
        self.busy = False
        self.closing = False
        self.closed = False
        self.pending_media = None
        self.wave_cancel = threading.Event()
        self.source_id = 0
        self.revision = 0
        self.preview_key = None
        self.preview_path = None
        self.using_preview = False
        self.last_directory = str(Path.home())
        self.events = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.temp_dir = Path(tempfile.gettempdir()) / ("audiocut-" + uuid.uuid4().hex)
        self.temp_dir.mkdir()
        self.jobs = 0
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self.position_changed)
        self.player.playbackStateChanged.connect(self.playback_changed)
        self.player.mediaStatusChanged.connect(self.media_status_changed)
        self.player.errorOccurred.connect(self.playback_error)
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.drain_events)
        self.timer.start(40)
        self._shortcuts()
        self.refresh_controls()

    def _button(self, text, name, callback, object_name=""):
        button = QPushButton(icon(name), text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if object_name:
            button.setObjectName(object_name)
        button.clicked.connect(callback)
        return button

    def _build_ui(self):
        body = QWidget()
        body.setObjectName("centralWidget")
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.setCentralWidget(scroll)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(32, 24, 32, 20)
        layout.setSpacing(18)
        top = QHBoxLayout()
        brand = QLabel("轻剪  <span style='color:#8891A3;font-size:13px'>AudioCut</span>")
        brand.setObjectName("appTitle")
        brand.setFont(QFont("Microsoft YaHei UI", 17, QFont.Weight.DemiBold))
        top.addWidget(brand)
        top.addStretch()
        self.open_button = self._button("打开音频", "open", self.choose_file)
        self.open_button.setToolTip("打开文件并自动播放 · Ctrl+O")
        top.addWidget(self.open_button)
        self.save_button = self._button("保存", "save", self.save, "primary")
        self.save_button.setIcon(icon("save", "#FFFFFF"))
        self.save_button.setToolTip("保存裁剪与淡入淡出效果 · Ctrl+S")
        top.addWidget(self.save_button)
        layout.addLayout(top)

        row = QHBoxLayout()
        file_info = QVBoxLayout()
        file_info.setSpacing(6)
        self.filename = QLabel("让声音，刚刚好。")
        self.filename.setObjectName("fileTitle")
        self.filename.setTextFormat(Qt.TextFormat.PlainText)
        self.filename.setMinimumWidth(0)
        self.file_detail = QLabel("打开即播放，需要时轻松剪辑。")
        self.file_detail.setObjectName("muted")
        file_info.addWidget(self.filename)
        file_info.addWidget(self.file_detail)
        row.addLayout(file_info, 1)
        self.mode_button = self._button("", "scissors", lambda: self.set_editing(not self.editing), "modeToggle")
        self.mode_button.setCheckable(True)
        self.mode_button.setFixedSize(40, 40)
        self.mode_button.setIconSize(QSize(22, 22))
        self.mode_button.setAccessibleName("编辑模式")
        row.addWidget(self.mode_button)
        layout.addLayout(row)

        self.wave = Waveform()
        self.wave.seekRequested.connect(self.seek)
        self.wave.selectionChanged.connect(self.select_range)
        self.wave.fadeChanged.connect(self.change_fade)
        self.wave.curveChanged.connect(self.change_curve)
        layout.addWidget(self.wave, 1)

        transport = QHBoxLayout()
        self.back_button = self._button("", "back", self.restart)
        self.back_button.setToolTip("回到片段开头 · Home")
        self.back_button.setAccessibleName("回到片段开头")
        self.play_button = self._button("", "play", self.toggle_play, "playButton")
        self.play_button.setIcon(icon("play", "#FFFFFF", 24))
        self.play_button.setFixedSize(50, 50)
        self.play_button.setToolTip("播放 / 暂停 · 空格")
        self.play_button.setAccessibleName("播放或暂停")
        transport.addWidget(self.back_button)
        transport.addWidget(self.play_button)
        transport.addSpacing(12)
        self.clock_label = QLabel("00:00  /  00:00")
        self.clock_label.setObjectName("clock")
        transport.addWidget(self.clock_label)
        transport.addStretch()
        self.play_hint = QLabel("打开文件后自动播放")
        self.play_hint.setObjectName("muted")
        transport.addWidget(self.play_hint)
        transport.addSpacing(18)
        volume_icon = QLabel()
        volume_icon.setPixmap(icon("volume").pixmap(18, 18))
        transport.addWidget(volume_icon)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(96)
        self.volume.setAccessibleName("播放音量")
        self.volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        transport.addWidget(self.volume)
        layout.addLayout(transport)

        self.editor = QFrame()
        self.editor.setObjectName("editor")
        # Keep the waveform and transport stationary when the editor row is hidden.
        policy = self.editor.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.editor.setSizePolicy(policy)
        panel = QHBoxLayout(self.editor)
        panel.setContentsMargins(18, 6, 12, 6)
        panel.setSpacing(28)
        self.fade_in_label = QLabel("淡入  0.000 s")
        self.fade_out_label = QLabel("淡出  0.000 s")
        for label in (self.fade_in_label, self.fade_out_label):
            label.setMinimumWidth(130)
            label.setTextFormat(Qt.TextFormat.PlainText)
            panel.addWidget(label)
        panel.addStretch()
        self.reset_button = QPushButton("重置编辑")
        self.reset_button.setObjectName("textButton")
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.clicked.connect(self.reset_edit)
        panel.addWidget(self.reset_button)
        layout.addWidget(self.editor)

        footer = QHBoxLayout()
        self.status = QLabel("拖入一个音频文件，或按 Ctrl+O 打开")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedSize(90, 4)
        self.progress.setTextVisible(False)
        self.progress.hide()
        footer.addWidget(self.progress)
        shortcuts = QLabel("空格 播放 / 暂停")
        shortcuts.setObjectName("muted")
        footer.addWidget(shortcuts)
        layout.addLayout(footer)

    def _shortcuts(self):
        for key, callback in (("Ctrl+O", self.choose_file), ("Ctrl+S", self.save),
                              ("Ctrl+E", lambda: self.set_editing(not self.editing)),
                              ("Space", self.space), ("Home", self.restart)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)

    def space(self):
        if isinstance(QApplication.focusWidget(), QComboBox):
            return
        self.toggle_play()

    def dirty(self):
        return self.info is not None and self.edit != Edit(0, self.info.duration)

    def confirm_discard(self):
        return not self.dirty() or self.edit == getattr(self, "saved_edit", None) or QMessageBox.question(
            self, "尚未保存", "当前编辑尚未保存。要放弃这些编辑吗？",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Discard

    def choose_file(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "打开音频", self.last_directory,
            "音频文件 (*.ncm *.wav *.wave *.mp3 *.flac *.m4a *.aac *.ogg *.oga *.opus *.aif *.aiff);;所有文件 (*)",
        )
        if path:
            self.open_path(Path(path))

    def open_path(self, path, confirm=True):
        if self.busy or (confirm and not self.confirm_discard()):
            return
        self.player.pause()
        self.pending_media = None
        self.wave_cancel.set()
        self.wave_cancel = threading.Event()
        self.source_id += 1
        self.pending_open_autoplay = True
        self.set_busy(True, "正在读取音频…")
        self.run_job("open", open_audio, Path(path), self.temp_dir)

    def run_job(self, kind, function, *args):
        token = self.source_id
        self.jobs += 1
        def run():
            try:
                self.events.put((kind, token, function(*args), None))
            except Exception as exc:
                logging.exception("AudioCut %s", kind)
                self.events.put((kind, token, None, str(exc)))
        self.executor.submit(run)

    def drain_events(self):
        while True:
            try:
                kind, token, result, error = self.events.get_nowait()
            except queue.Empty:
                return
            self.jobs -= 1
            if self.closing:
                if self.jobs == 0:
                    self.busy = False
                    self.close()
                continue
            if token != self.source_id:
                continue
            if error:
                if kind == "wave":
                    self.status.setText("音频可播放，波形读取失败：" + error)
                    continue
                self.set_busy(False, "操作未完成")
                if kind == "export":
                    self.restore_source()
                QMessageBox.warning(self, "操作未完成", error)
                continue
            if kind == "open":
                self.loaded(result)
            elif kind == "wave":
                self.wave.set_audio(self.info, result)
                self.wave.set_edit(self.edit, self.editing)
            elif kind == "preview":
                self.preview_path = result
                self.preview_key = (self.source_id, self.revision)
                self.set_busy(False, "试听已就绪，包含裁剪与淡入淡出")
                self.set_media(result, True, self.pending_seek, self.pending_play)
            elif kind == "export":
                self.set_busy(False, "已保存：" + str(result))
                if result.resolve() == self.info.path.resolve():
                    self.set_busy(True, "正在刷新保存后的音频…")
                    self.source_id += 1
                    self.pending_open_autoplay = False
                    self.run_job("open", probe, result)
                else:
                    self.saved_edit = self.edit
                    self.restore_source()
                    self.save_button.setText("已保存")

    def loaded(self, info):
        self.info = info
        self.edit = Edit(0, info.duration)
        self.saved_edit = self.edit
        self.revision += 1
        self.preview_key = None
        self.last_directory = str(info.original_path.parent)
        self.filename.setToolTip(info.original_path.name)
        self.filename.setText(self.filename.fontMetrics().elidedText(
            info.original_path.name, Qt.TextElideMode.ElideMiddle, self.width() - 270))
        channels = {1: "单声道", 2: "立体声"}.get(info.channels, f"{info.channels} 声道")
        depth = f"  ·  {info.bit_depth} bit" if info.bit_depth else ""
        self.file_detail.setText(f"{info.original_path.suffix[1:].upper()}  ·  {info.sample_rate / 1000:g} kHz  ·  {channels}{depth}")
        self.setWindowTitle(info.original_path.name + " — 轻剪 AudioCut")
        self.editing = False
        self.sync_fields()
        self.wave.set_audio(info, [])
        self.wave.set_edit(self.edit, False)
        self.set_busy(False, "已打开 · 点击波形跳转，切换编辑可裁剪和淡化")
        self.set_media(info.path, False, 0, self.pending_open_autoplay)
        self.run_job("wave", waveform, info, 1200, self.wave_cancel)

    def set_media(self, path, preview, position, play):
        self.player.stop()
        self.using_preview = preview
        self.pending_media = (position, play)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.media_status_changed(self.player.mediaStatus())
        self.position_changed(round(position * 1000))

    def media_status_changed(self, status):
        if self.pending_media is not None and status in (
            QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            position, play = self.pending_media
            self.pending_media = None
            self.player.setPosition(round(position * 1000))
            if play:
                self.player.play()

    def restore_source(self):
        self.preview_key = None
        self.set_media(self.info.path, False, self.edit.start, False)

    def set_busy(self, busy, message=None):
        self.busy = busy
        self.progress.setVisible(busy)
        if message:
            self.status.setText(message)
        self.refresh_controls()

    def refresh_controls(self):
        loaded = self.info is not None and not self.busy
        self.open_button.setEnabled(not self.busy)
        for button in (self.play_button, self.back_button, self.save_button,
                       self.mode_button):
            button.setEnabled(loaded)
        self.wave.setEnabled(loaded)
        self.editor.setEnabled(loaded)
        self.editor.setVisible(self.editing)
        self.mode_button.setChecked(self.editing)
        self.mode_button.setIcon(icon("scissors", "#FFFFFF" if self.editing else "#657086", 22))
        mode_hint = "编辑模式 · 点击返回播放" if self.editing else "播放模式 · 点击进入编辑"
        self.mode_button.setToolTip(mode_hint + " · Ctrl+E")
        self.mode_button.setAccessibleDescription(mode_hint)
        self.play_hint.setText("试听编辑效果" if self.dirty() else "原音播放" if self.info else "打开文件后自动播放")

    def set_editing(self, editing):
        if self.info is None or self.busy:
            return
        self.editing = editing
        self.wave.set_edit(self.edit, editing)
        self.refresh_controls()

    def sync_fields(self):
        self.fade_in_label.setText(f"淡入  {self.edit.fade_in:.3f} s")
        self.fade_out_label.setText(f"淡出  {self.edit.fade_out:.3f} s")
        self.wave.set_edit(self.edit, self.editing)

    def change_curve(self, side, curve):
        if self.busy or not self.edit or curve not in CURVES.values() or side not in ("in", "out"):
            return
        edit = replace(self.edit, **{"curve_" + side: curve})
        if edit == self.edit:
            return
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        position = self.player.position() / 1000 - (0 if self.using_preview else self.edit.start)
        self.update_edit(edit)
        if playing:
            self.prepare_preview(max(0, min(edit.duration, position)), True)

    def change_fade(self, side, seconds):
        if self.busy or not self.edit or side not in ("in", "out"):
            return
        self.update_edit(replace(self.edit, **{"fade_" + side: max(0, min(self.edit.duration, seconds))}))

    def select_range(self, start, end):
        duration = end - start
        self.update_edit(replace(self.edit, start=start, end=end,
                                 fade_in=min(self.edit.fade_in, duration),
                                 fade_out=min(self.edit.fade_out, duration)))

    def update_edit(self, edit):
        if edit == self.edit:
            return
        edit.validate(self.info.duration)
        self.player.pause()
        self.pending_media = None
        self.edit = edit
        self.revision += 1
        self.preview_key = None
        if not self.dirty() and self.using_preview:
            self.set_media(self.info.path, False, edit.start, False)
        self.sync_fields()
        self.wave.set_position(edit.start)
        self.clock_label.setText(f"00:00  /  {time_text(edit.duration)}")
        self.save_button.setText("保存")
        self.status.setText("编辑已更新 · 按空格试听效果")
        self.refresh_controls()

    def reset_edit(self):
        if self.info and not self.busy:
            self.update_edit(Edit(0, self.info.duration))

    def toggle_play(self):
        if not self.info or self.busy:
            return
        if self.pending_media is not None:
            position, play = self.pending_media
            self.pending_media = (position, not play)
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            return
        if self.dirty() and self.preview_key != (self.source_id, self.revision):
            self.prepare_preview(0, True)
        elif not self.dirty() and self.using_preview:
            self.set_media(self.info.path, False, 0, True)
        else:
            if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self.player.setPosition(0)
            self.player.play()

    def prepare_preview(self, relative_position, autoplay):
        self.player.pause()
        self.pending_seek = relative_position
        self.pending_play = autoplay
        destination = self.temp_dir / f"preview-{self.source_id}-{self.revision}.wav"
        self.set_busy(True, "正在准备试听…")
        self.run_job("preview", render_preview, self.info, self.edit, destination)

    def seek(self, position):
        if not self.info or self.busy:
            return
        position = min(self.edit.end, max(self.edit.start, position))
        if self.dirty() and self.preview_key != (self.source_id, self.revision):
            self.prepare_preview(position - self.edit.start,
                                 self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        else:
            offset = self.edit.start if self.using_preview else 0
            relative = position - offset
            if self.pending_media is not None:
                self.pending_media = (relative, self.pending_media[1])
            else:
                self.player.setPosition(round(relative * 1000))

    def restart(self):
        if self.info and not self.busy:
            self.seek(self.edit.start)

    def position_changed(self, milliseconds):
        if not self.info:
            return
        absolute = milliseconds / 1000 + (self.edit.start if self.using_preview else 0)
        self.wave.set_position(absolute)
        relative = max(0, min(self.edit.duration, absolute - self.edit.start))
        self.clock_label.setText(f"{time_text(relative)}  /  {time_text(self.edit.duration)}")

    def playback_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setIcon(icon("pause" if playing else "play", "#FFFFFF", 24))
        self.play_button.setAccessibleName("暂停" if playing else "播放")

    def playback_error(self, error, message):
        if error != QMediaPlayer.Error.NoError:
            self.status.setText("无法播放：" + message)

    def save(self):
        if not self.info or self.busy:
            return
        self.player.pause()
        self.pending_media = None
        dialog = SaveDialog(self.info, self)
        if dialog.exec() != SaveDialog.DialogCode.Accepted:
            return
        destination, format_key, keep_metadata = dialog.result_options()
        overwrite = destination.exists()
        if overwrite and QMessageBox.question(
            self, "替换已有文件", f"文件已存在：\n{destination}\n\n确定替换吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.begin_export(destination, format_key, keep_metadata, overwrite)

    def begin_export(self, destination, format_key, keep_metadata, overwrite=False):
        self.player.stop()
        self.pending_media = None
        # Release Windows' source file handle before an explicitly approved replacement.
        self.player.setSource(QUrl())
        self.set_busy(True, "正在保存音频…")
        self.run_job("export", export_audio, self.info, self.edit, Path(destination),
                     format_key, keep_metadata, overwrite)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if not self.busy and len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.open_path(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.info:
            self.filename.setText(self.filename.fontMetrics().elidedText(
                self.info.original_path.name, Qt.TextElideMode.ElideMiddle, self.width() - 270))

    def closeEvent(self, event: QCloseEvent):
        if self.closed:
            event.accept()
            return
        if self.busy:
            self.status.setText("正在处理音频，请完成后再关闭")
            event.ignore()
            return
        if not self.closing and self.dirty() and not self.confirm_discard():
            event.ignore()
            return
        if self.jobs:
            self.closing = True
            self.wave_cancel.set()
            self.player.stop()
            self.set_busy(True, "正在结束波形读取，随后关闭…")
            event.ignore()
            return
        self.player.stop()
        self.player.setSource(QUrl())
        self.timer.stop()
        self.executor.shutdown(wait=False)
        for path in list(self.temp_dir.glob("preview-*.wav")) + list(self.temp_dir.glob("ncm-*")):
            path.unlink(missing_ok=True)
        self.temp_dir.rmdir()
        self.closed = True
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AudioCut")
    apply_theme(app)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        QTimer.singleShot(0, lambda: window.open_path(Path(sys.argv[1])))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
