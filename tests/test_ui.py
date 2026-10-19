"""Real Qt playback and export smoke tests. Audio output is muted during tests."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QContextMenuEvent, QFontDatabase, QPainterPathStroker, QPalette
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app import MainWindow
from core import CURVES, Edit, gain_at, probe, resolve_tool
from theme import COLORS, DARK_COLORS, LIGHT_COLORS, apply_theme
from widgets import SaveDialog, fade_path
from ncm_fixture import make_ncm


class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        for font in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + font)
        apply_theme(cls.qt)
        cls.root = Path(__file__).resolve().parent / ("ui-tmp-" + uuid.uuid4().hex)
        cls.root.mkdir()
        cls.source = cls.root / "测试音频.wav"
        subprocess.run([resolve_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                        "aevalsrc=0.3*sin(2*PI*440*t)*(0.55+0.45*sin(2*PI*1.1*t)):s=48000:d=8",
                        "-metadata", "title=UI test title", "-c:a", "pcm_s24le", str(cls.source)], check=True)

    @classmethod
    def tearDownClass(cls):
        if cls.root.parent == Path(__file__).resolve().parent and cls.root.name.startswith("ui-tmp-"):
            shutil.rmtree(cls.root)

    def setUp(self):
        self.window = MainWindow()
        self.window.audio.setMuted(True)
        self.window.show()
        QTest.qWait(40)

    def tearDown(self):
        self.wait_for(lambda: self.window.jobs == 0)
        if self.window.info:
            self.window.saved_edit = self.window.edit
        self.window.close()
        QTest.qWait(30)

    def wait_for(self, condition, seconds=25):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.qt.processEvents()
            if condition():
                return
            QTest.qWait(20)
        self.fail("Timed out waiting for UI; status=" + self.window.status.text())

    def load(self):
        self.window.open_path(self.source)
        self.wait_for(lambda: self.window.info is not None and not self.window.busy)
        self.wait_for(lambda: self.window.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        self.wait_for(lambda: self.window.player.position() > 80)

    def test_ncm_autoplay_save_directory_and_cache_cleanup(self):
        flac = self.root / "ncm-source.flac"
        subprocess.run([resolve_tool("ffmpeg"), "-v", "error", "-y", "-i", str(self.source), str(flac)], check=True)
        source = self.root / "云音乐测试.ncm"
        source.write_bytes(make_ncm(flac.read_bytes(), {"musicName": "NCM title"}))
        self.window.open_path(source)
        self.wait_for(lambda: self.window.info is not None and not self.window.busy)
        self.wait_for(lambda: self.window.player.position() > 80)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.assertIn(source.name, self.window.windowTitle())
        self.assertEqual(self.window.last_directory, str(source.parent))
        dialog = SaveDialog(self.window.info, self.window)
        destination, fmt, keep = dialog.result_options()
        self.assertEqual(destination, source.with_name(source.stem + "_edit.flac"))
        self.assertEqual(fmt, "flac")
        self.window.player.pause()
        self.window.mode_button.click()
        self.window.select_range(1, 4)
        self.window.change_fade("in", 0.5)
        self.window.toggle_play()
        self.wait_for(lambda: self.window.using_preview and not self.window.busy)
        self.window.begin_export(destination, fmt, keep)
        self.wait_for(lambda: not self.window.busy)
        self.assertAlmostEqual(probe(destination).duration, 3, places=3)
        self.assertEqual(probe(destination).tags.get("title"), "NCM title")
        self.wait_for(lambda: self.window.jobs == 0)
        cache = self.window.temp_dir
        self.window.close()
        self.assertFalse(cache.exists())

    def test_complete_play_edit_preview_save_flow(self):
        digest = hashlib.sha256(self.source.read_bytes()).digest()
        self.load()
        self.assertFalse(self.window.editing)
        self.assertFalse(self.window.editor.isVisible())
        self.assertAlmostEqual(self.window.audio.volume(), 0.8, places=6)
        self.window.toggle_play()
        self.window.mode_button.click()
        self.assertTrue(self.window.editor.isVisible())
        self.window.select_range(1, 4)
        self.window.change_fade("in", 0.5)
        self.window.change_fade("out", 0.75)
        self.window.change_curve("in", "hsin")
        self.window.change_curve("out", "exp3")
        self.assertEqual(self.window.edit, Edit(1, 4, 0.5, 0.75, "hsin", "exp3"))
        self.window.toggle_play()
        self.wait_for(lambda: not self.window.busy and self.window.using_preview)
        self.wait_for(lambda: self.window.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        self.wait_for(lambda: self.window.player.position() > 80)
        self.assertAlmostEqual(probe(self.window.preview_path).duration, 3, places=3)
        self.window.toggle_play()
        self.window.seek(2.0)
        self.wait_for(lambda: abs(self.window.player.position() - 1000) < 80)
        self.window.mode_button.click()
        self.assertFalse(self.window.editor.isVisible())
        self.assertEqual(self.window.edit.duration, 3)
        self.window.mode_button.click()
        self.wait_for(lambda: self.window.jobs == 0)

        evidence = Path(__file__).resolve().parents[1] / "evidence"
        evidence.mkdir(exist_ok=True)
        self.window.grab().save(str(evidence / "editor.png"))
        dialog = SaveDialog(self.window.info, self.window)
        destination, format_key, keep = dialog.result_options()
        self.assertEqual(destination.parent, self.source.parent)
        self.assertEqual(destination.stem, self.source.stem + "_edit")
        self.assertTrue(keep)
        dialog.show()
        QTest.qWait(40)
        dialog.grab().save(str(evidence / "save.png"))
        dialog.close()
        self.window.begin_export(destination, format_key, keep)
        self.wait_for(lambda: not self.window.busy)
        output = probe(destination)
        self.assertAlmostEqual(output.duration, 3, places=3)
        self.assertEqual(output.tags.get("title"), "UI test title")
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), digest)
        self.assertIn("已保存", self.window.status.text())

    def test_compatible_playback_complete_flow(self):
        if not self.compatible_backend("test_compatible_playback_complete_flow"):
            return
        self.test_complete_play_edit_preview_save_flow()
        self.assertIn("兼容播放", self.window.windowTitle())
        self.assertEqual(self.window.info.path, self.source.resolve())
        cached = Path(self.window.player.source().toLocalFile())
        self.assertNotEqual(cached, self.source)
        fmt = self.window.audio.device().preferredFormat()
        self.assertEqual(probe(cached).sample_rate, fmt.sampleRate())
        self.assertEqual(probe(cached).channels, fmt.channelCount())
        count = len(self.window.playback_cache)
        self.window.restore_source()
        self.assertFalse(self.window.busy)
        self.assertEqual(len(self.window.playback_cache), count)
        self.wait_for(lambda: self.window.jobs == 0)
        cache_directory = self.window.temp_dir
        self.window.close()
        self.assertFalse(cache_directory.exists())

    def test_theme_switch_preserves_playback_and_edit(self):
        self.assertTrue(self.window.theme_button.isEnabled())
        self.load()
        self.window.set_editing(True)
        self.window.update_edit(Edit(1, 6, 0.6, 0.8))
        self.window.toggle_play()
        self.wait_for(lambda: not self.window.busy and self.window.using_preview)
        self.wait_for(lambda: self.window.player.position() > 80)
        edit, source = self.window.edit, self.window.player.source()
        volume = self.window.audio.volume()
        geometry = self.window.wave.geometry()
        evidence = Path(__file__).resolve().parents[1] / "evidence"
        evidence.mkdir(exist_ok=True)
        try:
            for dark, colors in ((True, DARK_COLORS), (False, LIGHT_COLORS)):
                position = self.window.player.position()
                self.window.theme_button.click()
                QTest.qWait(60)
                self.assertEqual(self.qt.property("dark_theme"), dark)
                self.assertEqual(COLORS, colors)
                self.assertEqual(self.window.theme_button.isChecked(), dark)
                self.assertEqual(self.window.theme_button.accessibleName(), "切换到浅色主题" if dark else "切换到深色主题")
                self.assertEqual(self.window.player.source(), source)
                self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
                self.assertGreaterEqual(self.window.player.position(), position)
                self.assertEqual(self.window.edit, edit)
                self.assertTrue(self.window.editing)
                self.assertEqual(self.window.audio.volume(), volume)
                self.assertEqual(self.window.wave.geometry(), geometry)
                self.assertEqual(self.window.play_button.height(), 50)
                self.assertEqual(self.window.theme_button.height(), 40)
                self.assertNotIn("@", self.qt.styleSheet())
                name = "dark" if dark else "light"
                self.window.grab().save(str(evidence / f"theme-{name}.png"))
                dialog = SaveDialog(self.window.info, self.window)
                dialog.show()
                QTest.qWait(30)
                self.assertEqual(dialog.palette().color(QPalette.ColorRole.Window).name().upper(), colors["background"])
                self.assertEqual(dialog.name_edit.palette().color(QPalette.ColorRole.Base).name().upper(), colors["surface"])
                dialog.grab().save(str(evidence / f"theme-{name}-save.png"))
                dialog.close()
                menu = self.window.wave.show_curve_menu("in", self.window.wave.mapToGlobal(QPoint(160, 70)))
                QTest.qWait(30)
                self.assertEqual(menu.palette().color(QPalette.ColorRole.Window).name().upper(), colors["surface"])
                menu.grab().save(str(evidence / f"theme-{name}-curves.png"))
                menu.close()
        finally:
            apply_theme(self.qt)
            self.window.refresh_theme_icons()

    def test_frameless_window_controls_drag_and_resize(self):
        window = self.window
        self.assertTrue(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        handle = window.windowHandle()
        with patch.object(handle, "startSystemMove", return_value=True) as move, \
                patch.object(handle, "startSystemResize", return_value=True) as resize:
            QTest.mouseClick(window.header, Qt.MouseButton.LeftButton, pos=QPoint(80, 40))
            move.assert_called_once()
            move.reset_mock()
            for point, edges in (
                (QPoint(1, 1), Qt.Edge.TopEdge | Qt.Edge.LeftEdge),
                (QPoint(window.width() - 2, 1), Qt.Edge.TopEdge | Qt.Edge.RightEdge),
                (QPoint(1, window.height() - 2), Qt.Edge.BottomEdge | Qt.Edge.LeftEdge),
                (QPoint(window.width() - 2, window.height() - 2), Qt.Edge.BottomEdge | Qt.Edge.RightEdge),
                (QPoint(1, 100), Qt.Edge.LeftEdge),
                (QPoint(window.width() - 2, 100), Qt.Edge.RightEdge),
                (QPoint(100, 1), Qt.Edge.TopEdge),
                (QPoint(100, window.height() - 2), Qt.Edge.BottomEdge),
            ):
                QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=point)
                resize.assert_called_with(edges)
            QTest.mouseClick(window.maximize_button, Qt.MouseButton.LeftButton)
            QTest.qWait(30)
            self.assertTrue(window.isMaximized())
            self.assertEqual(window.maximize_button.accessibleName(), "还原窗口")
            move.assert_not_called()
            resize.reset_mock()
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(1, 100))
            resize.assert_not_called()
            QTest.mouseDClick(window.header, Qt.MouseButton.LeftButton, pos=QPoint(80, 40))
            QTest.qWait(30)
            self.assertFalse(window.isMaximized())
            window.minimize_button.click()
            self.assertTrue(window.isMinimized())
            window.showNormal()
            window.resize(800, 530)
            QTest.qWait(30)
            before = window.header.geometry()
            window.centralWidget().verticalScrollBar().setValue(10000)
            QTest.qWait(20)
            self.assertEqual(window.header.geometry(), before)
            self.assertTrue(window.close_button.isVisible())
            self.assertGreater(window.open_button.width(), 80)

    def test_frameless_close_button_keeps_unsaved_edit_guard(self):
        self.load()
        self.wait_for(lambda: self.window.jobs == 0)
        self.window.update_edit(Edit(1, 4))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            self.window.close_button.click()
            question.assert_called_once()
            self.assertTrue(self.window.isVisible())
            self.assertFalse(self.window.closed)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.window.close_button.click()
        self.assertTrue(self.window.closed)

    def test_compatible_ncm_playback_and_cleanup(self):
        if not self.compatible_backend("test_compatible_ncm_playback_and_cleanup"):
            return
        self.test_ncm_autoplay_save_directory_and_cache_cleanup()

    def test_compatible_conversion_failure_can_retry(self):
        if not self.compatible_backend("test_compatible_conversion_failure_can_retry"):
            return
        with patch("app.render_playback", side_effect=RuntimeError("conversion failed")), patch.object(QMessageBox, "warning") as warning:
            self.window.open_path(self.source)
            self.wait_for(lambda: warning.called and not self.window.busy)
        self.assertIsNotNone(self.window.pending_playback)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlaybackState.StoppedState)
        self.window.toggle_play()
        self.wait_for(lambda: not self.window.busy and self.window.player.position() > 80)
        self.assertIsNone(self.window.pending_playback)

    def compatible_backend(self, test_name):
        # Qt chooses its backend once per process; isolate the native mode tests.
        if sys.platform == "win32" and os.environ.get("QT_MEDIA_BACKEND") != "windows":
            environment = os.environ.copy()
            environment["QT_MEDIA_BACKEND"] = "windows"
            result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                                     "-p", "test_ui.py", "-k", test_name, "-v"],
                                    cwd=Path(__file__).resolve().parents[1], env=environment,
                                    capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
            return False
        self.window.compatible_audio = True
        return True

    def test_empty_error_and_reset(self):
        self.assertFalse(self.window.play_button.isEnabled())
        evidence = Path(__file__).resolve().parents[1] / "evidence"
        evidence.mkdir(exist_ok=True)
        self.window.grab().save(str(evidence / "empty.png"))
        with patch.object(QMessageBox, "warning") as warning:
            self.window.open_path(self.root / "missing.wav")
            self.wait_for(lambda: not self.window.busy)
            warning.assert_called_once()
        self.assertIsNone(self.window.info)
        self.load()
        self.window.set_editing(True)
        self.window.select_range(2, 6)
        self.window.change_fade("in", 3)
        self.window.select_range(3, 4)
        self.assertLessEqual(self.window.edit.fade_in, 1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            previous = self.window.info
            self.window.open_path(self.source)
            self.assertIs(self.window.info, previous)
            self.assertEqual(self.window.edit.duration, 1)
        self.window.reset_button.click()
        self.assertEqual(self.window.edit, Edit(0, 8))
        self.assertEqual(self.window.fade_in_label.text(), "淡入  0.000 s")
        self.assertEqual(self.window.fade_out_label.text(), "淡出  0.000 s")
        self.assertFalse(self.window.dirty())

    def test_save_formats_and_validation(self):
        self.load()
        self.window.player.pause()
        dialog = SaveDialog(self.window.info, self.window)
        for i in range(dialog.format_combo.count()):
            if dialog.format_combo.itemData(i) == "mp3":
                dialog.format_combo.setCurrentIndex(i)
                break
        destination, fmt, keep = dialog.result_options()
        self.assertEqual(destination.suffix, ".mp3")
        self.assertEqual(fmt, "mp3")
        dialog.name_edit.setText("../bad")
        with patch.object(QMessageBox, "warning") as warning:
            dialog.accept()
            self.assertNotEqual(dialog.result(), SaveDialog.DialogCode.Accepted)
        dialog.close()

    def test_first_preview_seek_and_reset_seek(self):
        self.load()
        self.window.player.pause()
        self.window.set_editing(True)
        self.window.select_range(2, 4)
        self.window.seek(3)
        self.wait_for(lambda: not self.window.busy and self.window.pending_media is None)
        self.assertTrue(self.window.using_preview)
        self.wait_for(lambda: abs(self.window.player.position() - 1000) < 60)
        self.window.reset_edit()
        self.window.seek(6)
        self.wait_for(lambda: self.window.pending_media is None)
        self.assertFalse(self.window.using_preview)
        self.wait_for(lambda: abs(self.window.player.position() - 6000) < 60)
        self.window.toggle_play()
        self.wait_for(lambda: self.window.player.position() > 6100)

    def test_close_cancels_background_waveform_without_blocking(self):
        def slow_wave(info, bins, cancel):
            cancel.wait(10)
            return []
        with patch("app.waveform", side_effect=slow_wave):
            self.load()
            start = time.monotonic()
            self.window.close()
            self.assertLess(time.monotonic() - start, 0.3)
            self.wait_for(lambda: self.window.closed)
            self.assertFalse(self.window.isVisible())

    def test_edit_cancels_pending_autoplay(self):
        self.load()
        self.window.pending_media = (0, True)
        self.window.update_edit(Edit(1, 4))
        self.assertIsNone(self.window.pending_media)
        self.window.media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlaybackState.PausedState)

    def test_right_click_curve_menu_and_playing_update(self):
        self.load()
        self.window.player.pause()
        self.window.set_editing(True)
        self.window.update_edit(Edit(0, 8, 2, 2))
        QTest.qWait(30)
        wave = self.window.wave
        for side, chosen in (("in", "sine_in"), ("out", "sine_out")):
            path = dict(wave._fade_paths())[side]
            point = path.pointAtPercent(0.5).toPoint()
            self.assertEqual(wave._curve_at(QPointF(point)), side)
            event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, wave.mapToGlobal(point))
            QApplication.sendEvent(wave, event)
            menu = wave._curve_menu
            actions = [a for a in menu.actions() if a.isCheckable()]
            self.assertEqual([a.data() for a in actions], list(CURVES.values()))
            self.assertEqual(sum(a.isChecked() for a in actions), 1)
            self.assertTrue(all(not a.icon().isNull() for a in actions))
            before = self.window.edit
            next(a for a in actions if a.data() == chosen).trigger()
            menu.close()
            self.assertEqual(getattr(self.window.edit, "curve_" + side), chosen)
            self.assertEqual(getattr(self.window.edit, "curve_" + ("out" if side == "in" else "in")),
                             getattr(before, "curve_" + ("out" if side == "in" else "in")))
        self.window.toggle_play()
        self.wait_for(lambda: not self.window.busy and self.window.player.position() > 100)
        previous = self.window.preview_key
        menu = wave.show_curve_menu("in", wave.mapToGlobal(QPoint(40, 50)))
        next(a for a in menu.actions() if a.data() == "exp141").trigger()
        menu.close()
        self.wait_for(lambda: not self.window.busy and self.window.pending_media is None)
        self.assertNotEqual(previous, self.window.preview_key)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.window.player.pause()
        point = dict(wave._fade_paths())["out"].pointAtPercent(0.5).toPoint()
        QApplication.sendEvent(wave, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, wave.mapToGlobal(point)))
        self.assertTrue(wave._curve_menu.isVisible())
        self.assertEqual(next(a.data() for a in wave._curve_menu.actions() if a.isChecked()), "sine_out")
        wave._curve_menu.close()
        self.window.update_edit(Edit(0, 8, 0.001, 0))
        self.assertEqual(wave._curve_at(dict(wave._fade_paths())["in"].pointAtPercent(0.5)), "in")
        self.window.reset_edit()
        self.assertEqual(wave._fade_paths(), [])

    def test_top_fade_handles_drag_preview_and_limits(self):
        self.load()
        self.window.set_editing(True)
        wave = self.window.wave
        self.window.update_edit(Edit(1, 7, 0, 0, "sine_in", "exp3"))
        QTest.qWait(30)
        def drag(handle, seconds):
            rect = dict(wave._handles())[handle].boundingRect()
            direction = 1 if handle == "fade_in" else -1
            point = QPoint(round((rect.right() if direction < 0 else rect.left()) + direction * 3),
                           round(rect.top() + 3))
            self.assertEqual(wave._handle_at(QPointF(point)), handle)
            destination = point + QPoint(round(seconds / wave._duration() * wave._plot().width()), 0)
            before = self.window.edit
            QTest.mousePress(wave, Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual(self.window.edit, before)
            QTest.mouseMove(wave, destination)
            QTest.mouseRelease(wave, Qt.MouseButton.LeftButton, pos=destination)
        with patch.object(self.window, "prepare_preview", wraps=self.window.prepare_preview) as preview:
            drag("fade_in", 2)
            self.assertAlmostEqual(self.window.edit.fade_in, 2, delta=0.015)
            self.assertEqual(self.window.edit.fade_out, 0)
            drag("fade_out", -1)
            self.assertAlmostEqual(self.window.edit.fade_out, 1, delta=0.015)
            self.assertEqual((self.window.edit.start, self.window.edit.end), (1, 7))
            self.assertEqual((self.window.edit.curve_in, self.window.edit.curve_out), ("sine_in", "exp3"))
            self.assertEqual(self.window.fade_in_label.text(), f"淡入  {self.window.edit.fade_in:.3f} s")
            self.assertEqual(self.window.fade_out_label.text(), f"淡出  {self.window.edit.fade_out:.3f} s")
            preview.assert_not_called()
        self.window.toggle_play()
        self.wait_for(lambda: not self.window.busy and self.window.player.position() > 80)
        self.assertTrue(self.window.using_preview)
        self.assertEqual(self.window.preview_key, (self.window.source_id, self.window.revision))
        drag("fade_in", -10)
        self.assertEqual(self.window.edit.fade_in, 0)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
        drag("fade_out", -10)
        self.assertEqual(self.window.edit.fade_out, 6)
        drag("fade_in", 10)
        self.assertEqual(self.window.edit.fade_in, 6)
        self.assertEqual(len(wave._fade_paths()), 2)
        drag("fade_out", 10)
        self.assertEqual(self.window.edit.fade_out, 0)
        self.window.set_editing(False)
        self.assertEqual(wave._handles(), [])

    def test_bottom_range_handles_and_narrow_selection(self):
        self.load()
        self.window.player.pause()
        self.window.set_editing(True)
        wave = self.window.wave
        self.window.update_edit(Edit(1, 7, 2, 2))
        QTest.qWait(30)
        def drag(handle, seconds):
            point = dict(wave._handles())[handle].boundingRect().center().toPoint()
            self.assertEqual(wave._handle_at(QPointF(point)), handle)
            destination = point + QPoint(round(seconds / wave._duration() * wave._plot().width()), 0)
            QTest.mousePress(wave, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseMove(wave, destination)
            QTest.mouseRelease(wave, Qt.MouseButton.LeftButton, pos=destination)
        drag("start", 1)
        self.assertAlmostEqual(self.window.edit.start, 2, delta=0.015)
        self.assertEqual(self.window.edit.end, 7)
        self.assertEqual(self.window.edit.fade_in, 2)
        drag("end", -1)
        self.assertAlmostEqual(self.window.edit.end, 6, delta=0.015)
        self.assertAlmostEqual(self.window.edit.start, 2, delta=0.015)
        center = QPoint(round(wave._x(self.window.edit.start)), round(wave._plot().center().y()))
        self.assertIsNone(wave._handle_at(QPointF(center)))
        with patch.object(self.window, "prepare_preview"):
            before = self.window.edit
            QTest.mouseClick(wave, Qt.MouseButton.LeftButton, pos=center)
            self.assertEqual(self.window.edit, before)
        drag("start", 20)
        self.assertAlmostEqual(self.window.edit.duration, 0.001, places=6)
        self.assertLessEqual(self.window.edit.fade_in, self.window.edit.duration)
        self.assertLessEqual(self.window.edit.fade_out, self.window.edit.duration)
        for handle in ("start", "end"):
            point = dict(wave._handles())[handle].boundingRect().center()
            self.assertEqual(wave._handle_at(point), handle)
        drag("start", -20)
        drag("end", 20)
        self.assertEqual((self.window.edit.start, self.window.edit.end), (0, 8))

    def test_single_mode_icon_keeps_preview_geometry_and_playback(self):
        self.assertFalse(self.window.mode_button.isEnabled())
        self.load()
        self.assertEqual(self.window.mode_button.text(), "")
        self.assertFalse(self.window.mode_button.icon().isNull())
        for width, height in ((980, 590), (800, 530), (1100, 800)):
            self.window.resize(width, height)
            QTest.qWait(30)
            preview = self.window.wave.geometry()
            transport = self.window.play_button.geometry()
            size = self.window.size()
            for expected in (True, False):
                self.window.mode_button.click()
                QTest.qWait(30)
                self.assertEqual(self.window.editing, expected)
                self.assertEqual(self.window.mode_button.isChecked(), expected)
                self.assertEqual(self.window.editor.isVisible(), expected)
                self.assertEqual(self.window.wave.geometry(), preview)
                self.assertEqual(self.window.play_button.geometry(), transport)
                self.assertEqual(self.window.size(), size)
                self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.window.player.pause()
        self.window.activateWindow()
        self.window.mode_button.setFocus()
        QTest.keyClick(self.window, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
        QTest.qWait(30)
        self.assertTrue(self.window.mode_button.isChecked())
        self.window.update_edit(Edit(1, 6, 1, 2))
        before = self.window.edit
        self.window.mode_button.click()
        self.window.mode_button.click()
        self.assertEqual(self.window.edit, before)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlaybackState.PausedState)

    def test_curve_geometry_endpoints_and_flush_playhead(self):
        for rect in (QRectF(5, 5, 54, 34), QRectF(0, 0, 1100, 260), QRectF(0, 0, 0.01, 180)):
            for curve in CURVES.values():
                for side in ("in", "out"):
                    path = fade_path(rect, curve, side)
                    stroker = QPainterPathStroker()
                    stroker.setWidth(0.3)
                    stroke = stroker.createStroke(path)
                    for i in range(1, 400):
                        t = i / 400
                        gain = gain_at(t, curve)
                        if side == "out":
                            gain = 1 - gain
                        self.assertTrue(stroke.contains(QPointF(rect.left() + t * rect.width(), rect.bottom() - gain * rect.height())), (curve, side, t, rect))
        self.load()
        self.window.player.pause()
        self.window.set_editing(True)
        self.assertEqual(self.window.edit.curve_in, "sine_in")
        self.assertEqual(self.window.edit.curve_out, "sine_out")
        self.window.update_edit(Edit(1, 7, 1, 2))
        wave = self.window.wave
        plot = wave._plot()
        for side, path in wave._fade_paths():
            endpoint = path.currentPosition() if side == "in" else QPointF(path.elementAt(0).x, path.elementAt(0).y)
            handle = dict(wave._handles())["fade_" + side]
            self.assertEqual(endpoint, QPointF(handle.elementAt(0).x, handle.elementAt(0).y))
        bounds = QRectF(wave._x(1), plot.top(), wave._x(7) - wave._x(1), plot.height())
        for t in (1, 3, 7):
            wave.set_position(t)
            stem, top, bottom = wave._playhead_rects()
            for rect in (stem, top, bottom):
                self.assertTrue(bounds.contains(rect))
            self.assertEqual(stem.top(), plot.top())
            self.assertEqual(stem.bottom(), plot.bottom())
            if t == 1:
                self.assertEqual(stem.left(), bounds.left())
            elif t == 7:
                self.assertEqual(stem.right(), bounds.right())


if __name__ == "__main__":
    unittest.main(verbosity=2)
