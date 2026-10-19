import math
from pathlib import Path
import sys
import shutil
import unittest
from unittest.mock import patch
import wave
import uuid
from array import array
from concurrent.futures import CancelledError
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core


class AudioCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent / ("audio-cut-test-" + uuid.uuid4().hex)
        cls.root.mkdir()
        cls.source = cls.root / "原始 音频.wav"
        core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                   "aevalsrc=0.5:s=48000:d=3", "-c:a", "pcm_s16le", "-metadata",
                   "title=Audio Cut Test", "-metadata", "artist=Test Artist", str(cls.source)])
        cls.info = core.probe(cls.source)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def target(self, name):
        return self.root / name

    def samples(self, path):
        with wave.open(str(path), "rb") as reader:
            return reader.getframerate(), array("h", reader.readframes(reader.getnframes()))

    def test_probe_and_aliases(self):
        self.assertAlmostEqual(self.info.duration, 3, places=4)
        self.assertEqual((self.info.sample_rate, self.info.channels, self.info.bit_depth), (48000, 1, 16))
        self.assertEqual(self.info.tags["title"], "Audio Cut Test")
        self.assertEqual(core.normalize_format(".WAVE"), "wav")
        self.assertEqual(core.normalize_format("aif"), "aiff")

    def test_compatible_pcm_matches_device_without_changing_source(self):
        original = self.source.read_bytes()
        output = self.target("compatible.wav")
        core.render_playback(self.source, output, 96000, 2, "pcm_f32le")
        info = core.probe(output)
        self.assertEqual((info.sample_rate, info.channels, info.codec), (96000, 2, "pcm_f32le"))
        self.assertAlmostEqual(info.duration, 3, places=4)
        samples = array("f", core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-i", str(output), "-f", "f32le", "-"]))
        # FFmpeg's mono -> stereo pan law is -3 dB; verify both channels and no spikes.
        expected = 0.5 / math.sqrt(2)
        for sample in samples[1920:-1920]:
            self.assertAlmostEqual(sample, expected, delta=0.0001)
        self.assertEqual(original, self.source.read_bytes())

    def test_compatible_pcm_failure_cleanup_and_existing_target_protection(self):
        output = self.target("failed-compatible.wav")
        with patch.object(core, "_run", side_effect=RuntimeError("failure")), patch.object(core, "probe", return_value=self.info):
            with self.assertRaises(RuntimeError):
                core.render_playback(self.source, output, 96000, 2, "pcm_f32le")
        self.assertFalse(output.exists())
        output.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            core.render_playback(self.source, output, 96000, 2, "pcm_f32le")
        self.assertEqual(output.read_bytes(), b"keep")

    def test_default_sine_and_normalized_log_exponential(self):
        self.assertEqual((core.Edit(0, 1).curve_in, core.Edit(0, 1).curve_out), ("sine_in", "sine_out"))
        for suffix, base in (("3", 3), ("141", 1.41)):
            for t in (0, 0.1, 0.25, 0.5, 0.9, 1):
                self.assertAlmostEqual(core.gain_at(t, "log" + suffix), math.log(1 + (base - 1) * t, base))
                self.assertAlmostEqual(core.gain_at(t, "exp" + suffix), (base ** t - 1) / (base - 1))
                self.assertAlmostEqual(core.gain_at(core.gain_at(t, "exp" + suffix), "log" + suffix), t)

    def test_invalid_edits(self):
        for edit in [core.Edit(-1, 2), core.Edit(2, 1), core.Edit(1, 4), core.Edit(0, 1, 2),
                     core.Edit(0, 1, fade_out=-1), core.Edit(math.nan, 1), core.Edit(0, math.inf),
                     core.Edit(0, 1, curve_in="bad")]:
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                edit.validate(3)

    def test_crop_and_curves_match_real_ffmpeg_samples(self):
        for curve in core.CURVES.values():
            with self.subTest(curve=curve):
                dest = self.target(f"curve-{curve}.wav")
                core.export_audio(self.info, core.Edit(0.5, 2.5, 0.5, 0.5, curve, curve), dest, "wav")
                rate, samples = self.samples(dest)
                self.assertEqual(len(samples), 96000)
                for t in (0.125, 0.25, 0.375, 1, 1.625, 1.75, 1.875):
                    expected = core.gain_at(t / 0.5, curve) if t < 0.5 else 1 - core.gain_at((t - 1.5) / 0.5, curve) if t > 1.5 else 1
                    self.assertAlmostEqual(samples[round(t * rate)] / 16384,
                                           expected, delta=0.0003)

    def test_nine_distinct_curves_and_constant_power_pair(self):
        self.assertEqual(len(core.CURVES), 9)
        shapes = set()
        for curve in core.CURVES.values():
            points = [core.gain_at(i / 100, curve) for i in range(101)]
            self.assertAlmostEqual(points[0], 0)
            self.assertAlmostEqual(points[-1], 1)
            self.assertTrue(all(a <= b for a, b in zip(points, points[1:])))
            shapes.add(tuple(round(v, 5) for v in points))
        self.assertEqual(len(shapes), 9)
        for i in range(101):
            incoming = core.gain_at(i / 100, "sine_in")
            outgoing = 1 - core.gain_at(i / 100, "sine_out")
            self.assertAlmostEqual(incoming ** 2 + outgoing ** 2, 1, places=12)

    def test_overlapping_fades_preserve_stereo_channels(self):
        source = self.target("stereo-fades.wav")
        core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                   "aevalsrc=0.5|-0.25:s=48000:d=1", "-c:a", "pcm_s16le", str(source)])
        output = self.target("stereo-faded.wav")
        core.export_audio(core.probe(source), core.Edit(0, 1, 0.8, 0.8, "log141", "exp141"), output, "wav")
        rate, samples = self.samples(output)
        self.assertEqual(core.probe(output).channels, 2)
        for t in (0.1, 0.3, 0.5, 0.7, 0.9):
            gain = core.gain_at(t / 0.8, "log141") * (1 - core.gain_at((t - 0.2) / 0.8, "exp141"))
            index = round(t * rate) * 2
            self.assertAlmostEqual(samples[index] / 16384, gain, delta=0.0003)
            self.assertAlmostEqual(samples[index + 1] / -8192, gain, delta=0.0003)

    def test_all_output_formats(self):
        for fmt in core.FORMATS:
            with self.subTest(format=fmt):
                dest = self.target(f"format.{fmt}")
                core.export_audio(self.info, core.Edit(0.5, 1.5), dest, fmt)
                result = core.probe(dest)
                self.assertAlmostEqual(result.duration, 1, delta=0.08)
                self.assertEqual(result.channels, self.info.channels)
                self.assertEqual(result.sample_rate, self.info.sample_rate)

    def test_metadata_retention_and_removal(self):
        for fmt in core.FORMATS:
            for keep in (True, False):
                with self.subTest(format=fmt, keep=keep):
                    dest = self.target(f"metadata-{keep}.{fmt}")
                    core.export_audio(self.info, core.Edit(0, 1), dest, fmt, keep_metadata=keep)
                    tags = {k.lower(): v for k, v in core.probe(dest).tags.items()}
                    if keep:
                        self.assertEqual(tags["title"], "Audio Cut Test")
                        self.assertEqual(tags["artist"], "Test Artist")
                    else:
                        self.assertNotIn("title", tags)
                        self.assertNotIn("artist", tags)

    def test_audio_stream_tags_survive_cross_format_export(self):
        source = self.target("stream-tags.opus")
        core.export_audio(self.info, core.Edit(0, 1), source, "opus")
        dest = self.target("stream-tags.mp3")
        core.export_audio(core.probe(source), core.Edit(0, 0.8), dest, "mp3")
        tags = {k.lower(): v for k, v in core.probe(dest).tags.items()}
        self.assertEqual(tags["artist"], "Test Artist")
        self.assertEqual(tags["title"], "Audio Cut Test")

    def test_existing_file_requires_overwrite(self):
        dest = self.target("existing.wav")
        dest.write_bytes(b"keep this file")
        with self.assertRaises(FileExistsError):
            core.export_audio(self.info, core.Edit(0, 1), dest, "wav")
        self.assertEqual(dest.read_bytes(), b"keep this file")
        core.export_audio(self.info, core.Edit(0, 1), dest, "wav", overwrite=True)
        self.assertAlmostEqual(core.probe(dest).duration, 1, places=3)

    def test_failed_render_preserves_destination_and_removes_temporary(self):
        dest = self.target("safe.wav")
        dest.write_bytes(b"original")
        with patch.object(core, "_run", side_effect=RuntimeError("intentional failure")):
            with self.assertRaises(RuntimeError):
                core.export_audio(self.info, core.Edit(0, 1), dest, "wav", keep_metadata=False, overwrite=True)
        self.assertEqual(dest.read_bytes(), b"original")
        self.assertEqual(list(self.root.glob(".audio-cut-*")), [])

    def test_publish_race_does_not_overwrite(self):
        dest = self.target("race.wav")
        run = core._run
        def render_and_compete(*args, **kwargs):
            result = run(*args, **kwargs)
            dest.write_bytes(b"created concurrently")
            return result
        with patch.object(core, "_run", side_effect=render_and_compete):
            with self.assertRaises(RuntimeError):
                core.export_audio(self.info, core.Edit(0, 1), dest, "wav", keep_metadata=False)
        self.assertEqual(dest.read_bytes(), b"created concurrently")
        self.assertEqual(list(self.root.glob(".audio-cut-*")), [])

    def test_preview_matches_export(self):
        edit = core.Edit(0.3, 1.3, 0.2, 0.3, "log3", "exp3")
        preview, export = self.target("preview.wav"), self.target("saved.wav")
        core.render_preview(self.info, edit, preview)
        core.export_audio(self.info, edit, export, "wav", keep_metadata=False)
        self.assertEqual(self.samples(preview), self.samples(export))

    def test_waveform_and_antiphase_stereo(self):
        peaks = core.waveform(self.info, bins=37)
        self.assertEqual(len(peaks), 37)
        self.assertTrue(all(0.49 < p < 0.51 for p in peaks))
        stereo = self.target("antiphase.wav")
        core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                   "aevalsrc=0.5|-0.5:s=48000:d=0.1", str(stereo)])
        self.assertGreater(min(core.waveform(core.probe(stereo), bins=10)), 0.49)

    def test_waveform_retains_high_frequency_content(self):
        source = self.target("high-frequency.wav")
        core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                   "sine=frequency=10000:sample_rate=48000:duration=0.1", str(source)])
        self.assertGreater(min(core.waveform(core.probe(source), bins=10)), 0.12)

    def test_waveform_cancel_before_start(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(core.subprocess, "Popen") as popen:
            with self.assertRaises(CancelledError):
                core.waveform(self.info, 100, cancel)
            popen.assert_not_called()

    def test_waveform_cancel_stops_running_ffmpeg(self):
        cancel = threading.Event()
        popen = core.subprocess.Popen
        processes = []
        def start_realtime(args, **kwargs):
            args = list(args)
            args.insert(args.index("-i"), "-re")
            process = popen(args, **kwargs)
            processes.append(process)
            return process
        timer = threading.Timer(0.4, cancel.set)
        started = time.monotonic()
        timer.start()
        try:
            with patch.object(core.subprocess, "Popen", side_effect=start_realtime):
                with self.assertRaises(CancelledError):
                    core.waveform(self.info, 100, cancel)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)

    def chapter_source(self):
        source = self.target("chapters.m4a")
        if not source.exists():
            metadata = self.target("chapters.ffmetadata")
            metadata.write_text(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=4000\n"
                                "[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=8000\n", encoding="utf-8")
            core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                       "aevalsrc=0.5:s=48000:d=8", "-f", "ffmetadata", "-i", str(metadata),
                       "-map", "0:a:0", "-map_chapters", "1", "-metadata:c:0", "title=第一节=;#\\路径\n续行",
                       "-metadata:c:1", "title=第二节\\", "-c:a", "aac", str(source)])
        return source

    def test_chapters_are_clipped_and_rebased(self):
        source = self.chapter_source()
        original = core._probe_data(source)["chapters"]
        self.assertEqual(len(original), 2)
        for fmt in ("m4a", "mp3"):
            with self.subTest(format=fmt):
                dest = self.target(f"chapters-trimmed.{fmt}")
                core.export_audio(core.probe(source), core.Edit(2, 6), dest, fmt)
                chapters = core._probe_data(dest)["chapters"]
                self.assertEqual(len(chapters), 2)
                for index, (chapter, expected) in enumerate(zip(chapters, [(0, 2), (2, 4)])):
                    self.assertAlmostEqual(float(chapter["start_time"]), expected[0], places=3)
                    self.assertAlmostEqual(float(chapter["end_time"]), expected[1], places=3)
                    self.assertEqual(chapter["tags"]["title"], original[index]["tags"]["title"])
        self.assertEqual(list(self.root.glob(".audio-cut-*")), [])

    def test_chapters_outside_selection_and_metadata_removal(self):
        source = self.chapter_source()
        for keep in (True, False):
            dest = self.target(f"chapters-selection-{keep}.m4a")
            core.export_audio(core.probe(source), core.Edit(4.5, 6.5), dest, "m4a", keep_metadata=keep)
            chapters = core._probe_data(dest)["chapters"]
            self.assertEqual(len(chapters), 1 if keep else 0)
            if keep:
                self.assertAlmostEqual(float(chapters[0]["start_time"]), 0, places=3)
                self.assertAlmostEqual(float(chapters[0]["end_time"]), 2, places=3)

    def test_failed_chapter_export_cleans_metadata_file(self):
        source = self.chapter_source()
        info = core.probe(source)
        dest = self.target("chapters-failure.m4a")
        dest.write_bytes(b"keep original")
        run = core._run
        def fail_encoder(args, **kwargs):
            if args[0] == core.resolve_tool("ffmpeg"):
                raise RuntimeError("intentional encoding failure")
            return run(args, **kwargs)
        with patch.object(core, "_run", side_effect=fail_encoder):
            with self.assertRaises(RuntimeError):
                core.export_audio(info, core.Edit(2, 6), dest, "m4a", overwrite=True)
        self.assertEqual(dest.read_bytes(), b"keep original")
        self.assertEqual(list(self.root.glob(".audio-cut-*")), [])

    def test_cover_art_retention_and_removal(self):
        cover = self.target("cover.png")
        core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                   "color=c=blue:s=16x16", "-frames:v", "1", str(cover)])
        source = self.target("covered.flac")
        core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-i", str(self.source),
                   "-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:a", "flac", "-c:v",
                   "copy", "-disposition:v:0", "attached_pic", str(source)])
        for fmt in ("flac", "mp3", "m4a", "aiff"):
            for keep in (True, False):
                with self.subTest(format=fmt, keep=keep):
                    dest = self.target(f"cover-{keep}.{fmt}")
                    core.export_audio(core.probe(source), core.Edit(0, 1), dest, fmt, keep_metadata=keep)
                    streams = core._probe_data(dest)["streams"]
                    self.assertEqual(any(s.get("disposition", {}).get("attached_pic") for s in streams), keep)

    def test_alac_source_stays_alac(self):
        source = self.target("alac.m4a")
        core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-i", str(self.source), "-c:a", "alac", str(source)])
        dest = self.target("alac-saved.m4a")
        core.export_audio(core.probe(source), core.Edit(0, 1), dest, "source")
        self.assertEqual(core.probe(dest).codec, "alac")

    def test_24_bit_pcm_preservation(self):
        source = self.target("24bit.wav")
        core._run([core.resolve_tool("ffmpeg"), "-v", "error", "-i", str(self.source), "-c:a", "pcm_s24le", str(source)])
        dest = self.target("24bit-saved.wav")
        core.export_audio(core.probe(source), core.Edit(0, 1), dest, "same")
        self.assertEqual(core.probe(dest).bit_depth, 24)


if __name__ == "__main__":
    unittest.main()
