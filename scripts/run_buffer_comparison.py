"""Muted device experiment. Injected feed delays test tolerance, not the user's root cause."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_FORCE_STDERR_LOGGING"] = "1"

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import MainWindow
from audio_diagnostics import AudioDiagnostics
from buffer_test import BUFFER_SIZES, BufferProbe, prepare_pcm
from core import _run, resolve_tool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "artifacts" / "buffer-comparison")
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10:
        parser.error("rounds must be between 1 and 10")
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / "synthetic.wav"
    _run([resolve_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
          "sine=frequency=997:sample_rate=48000:duration=6", str(source)])
    qt = QApplication([])
    qt.setApplicationName("AudioCut")
    log = AudioDiagnostics(args.output, mode="automated_comparison")
    results = []
    probe = BufferProbe(log)
    probe.volume = 0
    window = None
    injection = QTimer()
    def stall():
        log.record("injected_delay", duration_ms=200, target="UI/feed thread")
        time.sleep(0.2)
    injection.timeout.connect(stall)
    injection.setInterval(1000)
    def wait_until(condition, timeout=20):
        deadline = time.perf_counter() + timeout
        while not condition() and time.perf_counter() < deadline:
            QTest.qWait(5)
        if not condition():
            raise RuntimeError("Diagnostic experiment timed out")
    try:
        # First inspect the production chain, with Qt's own renderer messages enabled.
        window = MainWindow(diagnostics=log)
        window.audio.setMuted(True)
        window.open_path(source)
        wait_until(lambda: window.player.position() > 100)
        injection.start()
        wait_until(lambda: window.player.position() >= 5900)
        injection.stop()
        wait_until(lambda: window.jobs == 0)
        window.close()
        log.player = None
        # All buffer trials decode once, then reuse the same PCM bytes and device.
        probe.pcm, probe.pcm_hash = prepare_pcm(source, probe.format)
        probe.finished.connect(results.append)
        for repetition in range(args.rounds):
            for delayed in (False, True):
                sizes = BUFFER_SIZES if repetition % 2 == 0 else tuple(reversed(BUFFER_SIZES))
                for size in sizes:
                    log.record("experiment_condition", repetition=repetition + 1, delayed=delayed, requested_ms=size)
                    probe.start(size)
                    if delayed:
                        injection.start()
                    wait_until(lambda: not probe.running)
                    injection.stop()
                    results[-1].update(repetition=repetition + 1, injected_delay_ms=200 if delayed else 0)
                    print(json.dumps(results[-1]), flush=True)
        assert all(r["reason"] == "eof" for r in results)
        assert len({r["pcm_sha256"] for r in results}) == 1
        assert len({r["native_period_frames"] for r in results}) == 1
    finally:
        injection.stop()
        probe.stop("cleanup")
        if window is not None:
            window.close()
        log.close()
    output = dict(log=str(log.path.resolve()), results=results,
                  limitation="Muted synthetic test; injected UI/feed stalls are not proof of a production/hardware fault")
    (args.output / "results.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    if log.writer_error or log.dropped:
        raise RuntimeError("Incomplete diagnostic log")


if __name__ == "__main__":
    main()
