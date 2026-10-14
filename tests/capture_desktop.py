"""Capture the real desktop UI using a supplied audio file (muted, read-only)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import MainWindow
from core import Edit
from theme import apply_theme
from widgets import SaveDialog


app = QApplication([])
apply_theme(app)
window = MainWindow()
window.audio.setMuted(True)
window.show()
window.open_path(Path(sys.argv[1]))
end = time.monotonic() + 45
while time.monotonic() < end:
    app.processEvents()
    if window.info and window.jobs == 0 and window.player.position() > 50:
        break
    QTest.qWait(30)
else:
    raise RuntimeError("Audio did not load: " + window.status.text())
assert window.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
window.player.pause()
evidence = Path(__file__).resolve().parents[1] / "evidence"
evidence.mkdir(exist_ok=True)
window.grab().save(str(evidence / "desktop-player.png"))
preview_geometry = window.wave.geometry()
transport_geometry = window.play_button.geometry()
window.mode_button.click()
QTest.qWait(30)
assert window.wave.geometry() == preview_geometry
assert window.play_button.geometry() == transport_geometry
window.update_edit(Edit(4, window.info.duration - 6))
QTest.qWait(60)
window.grab().save(str(evidence / "range-handles-zero.png"))
for handle, delta in (("fade_in", 15), ("fade_out", -20)):
    rect = dict(window.wave._handles())[handle].boundingRect()
    point = QPoint(round(rect.left() + 3 if handle == "fade_in" else rect.right() - 3), round(rect.top() + 3))
    destination = point + QPoint(round(delta / window.info.duration * window.wave._plot().width()), 0)
    QTest.mousePress(window.wave, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(window.wave, destination)
    QTest.mouseRelease(window.wave, Qt.MouseButton.LeftButton, pos=destination)
assert abs(window.edit.fade_in - 15) < window.info.duration / window.wave._plot().width()
assert abs(window.edit.fade_out - 20) < window.info.duration / window.wave._plot().width()
assert (window.edit.start, window.edit.end) == (4, window.info.duration - 6)
QTest.qWait(60)
window.grab().save(str(evidence / "desktop-editor.png"))
window.wave.set_position(window.edit.end)
window.grab().save(str(evidence / "playhead-end.png"))
window.wave.set_position(window.edit.start)
menu = window.wave.show_curve_menu("in", window.wave.mapToGlobal(QPoint(170, 90)))
QTest.qWait(80)
menu.grab().save(str(evidence / "curve-menu.png"))
menu.close()
dialog = SaveDialog(window.info, window)
dialog.show()
QTest.qWait(60)
dialog.grab().save(str(evidence / "desktop-save.png"))
dialog.close()
window.resize(800, 530)
QTest.qWait(30)
assert window.centralWidget().verticalScrollBar().maximum() > 0
assert window.wave.geometry().bottom() < window.play_button.geometry().top()
window.grab().save(str(evidence / "desktop-compact.png"))
print(f"Native desktop OK: {window.info.duration:.3f}s, {len(window.wave.peaks)} waveform bins; top fade drags and compact scroll OK")
window.saved_edit = window.edit
window.close()
