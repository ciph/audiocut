"""Diagnostic boundaries: real playback, nonblocking logs, and controlled PCM."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_FORCE_STDERR_LOGGING"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QByteArray, qWarning
from PySide6.QtMultimedia import QAudioFormat, QMediaDevices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import MainWindow
from audio_diagnostics import AudioDiagnostics
from buffer_test import BUFFER_SIZES, BufferProbe, prepare_pcm
from core import _run, resolve_tool


class DiagnosticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_log_captures_qt_events_and_marks_without_changing_playback(self):
        with tempfile.TemporaryDirectory() as directory:
            log = AudioDiagnostics(directory)
            window = MainWindow(diagnostics=log)
            try:
                self.assertIs(window.player, log.player)
                window.audio.setMuted(True)
                window.trace_playback("seek", target_ms=123)
                log.mark_shortcut.activated.emit()
                qWarning("diagnostic-test-warning")
                log.last_tick -= 0.2
                log._tick()
                self.assertTrue(window.audio.isMuted())
            finally:
                window.close()
                log.close()
            records = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
            events = [record["event"] for record in records]
            self.assertEqual(events[0], "session_start")
            self.assertEqual(events[-1], "session_end")
            self.assertIn("transport", events)
            self.assertIn("heard_glitch", events)
            self.assertIn("ui_timer_delay", events)
            self.assertTrue(any(r.get("message") == "diagnostic-test-warning" for r in records))
            self.assertFalse(log.writer.is_alive())
            self.assertIsNone(log.writer_error)

    def test_buffer_trials_keep_pcm_and_device_and_ignore_normal_eof(self):
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            self.skipTest("No output device")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.wav"
            _run([resolve_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                  "sine=frequency=440:sample_rate=48000:duration=0.7", str(source)])
            log = AudioDiagnostics(directory, mode="buffer_test")
            probe = BufferProbe(log, device)
            results = []
            probe.finished.connect(results.append)
            try:
                probe.pcm, probe.pcm_hash = prepare_pcm(source, probe.format)
                original = QByteArray(probe.pcm)
                probe.volume = 0
                for size in BUFFER_SIZES:
                    probe.start(size)
                    deadline = time.perf_counter() + 5
                    while probe.running and time.perf_counter() < deadline:
                        QTest.qWait(10)
                    self.assertFalse(probe.running, "PCM did not finish")
                    self.assertEqual(results[-1]["reason"], "eof")
                    self.assertEqual(results[-1]["starvation_events"], 0)
                    self.assertGreater(results[-1]["actual_ms"], 0)
                    self.assertEqual(probe.pcm, original)
                self.assertEqual(len({r["pcm_sha256"] for r in results}), 1)
                self.assertEqual(len({r["native_period_frames"] for r in results}), 1)
                with self.assertRaises(ValueError):
                    probe.start(-1)
            finally:
                probe.stop("cleanup")
                log.close()
            records = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(r["event"] == "sink_state" and r["state"] == "ActiveState" for r in records))

    def test_prepare_rejects_invalid_format(self):
        with self.assertRaises(ValueError):
            prepare_pcm("does-not-exist.wav", QAudioFormat())


if __name__ == "__main__":
    unittest.main()
