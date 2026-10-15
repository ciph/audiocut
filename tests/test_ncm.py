import base64
from pathlib import Path
import shutil
import struct
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Edit, _probe_data, _run, export_audio, open_audio, probe, resolve_tool, waveform
from ncm import decode_ncm
from ncm_fixture import make_ncm


class NcmTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / ("audio-cut-test-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.source = self.root / "测试歌曲.NCM"

    def tearDown(self):
        if self.root.resolve().parent == Path(__file__).resolve().parent and self.root.name.startswith("audio-cut-test-"):
            shutil.rmtree(self.root)

    def encoded_audio(self, fmt):
        path = self.root / ("source." + fmt)
        _run([resolve_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
              "sine=frequency=440:sample_rate=48000:duration=3", str(path)])
        return path.read_bytes()

    def test_streaming_decoder_keeps_exact_payload_and_skips_cover_padding(self):
        payload = b"fLaC" + bytes(range(256)) * 1100
        self.source.write_bytes(make_ncm(payload, {"format": "../../wrong.mp3"}, padding=7341))
        audio, tags, cover = decode_ncm(self.source, self.cache)
        self.assertEqual(audio.suffix, ".flac")
        self.assertEqual(audio.read_bytes(), payload)
        self.assertEqual(tags, {})
        self.assertIsNone(cover)

    def test_mp3_flac_open_edit_export_metadata_and_source_protection(self):
        # Small valid PNG, generated test artwork only.
        cover = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        for fmt in ("mp3", "flac"):
            with self.subTest(fmt=fmt):
                self.source.write_bytes(make_ncm(self.encoded_audio(fmt),
                    {"musicName": "合成测试", "album": "测试专辑", "artist": [["测试作者", 1]]}, cover))
                original = self.source.read_bytes()
                info = open_audio(self.source, self.cache)
                self.assertEqual(info.original_path, self.source.resolve())
                self.assertEqual(info.path.suffix, "." + fmt)
                self.assertEqual(info.tags["title"], "合成测试")
                self.assertEqual(info.tags["artist"], "测试作者")
                self.assertEqual(info.tags["album"], "测试专辑")
                self.assertTrue(waveform(info, 50))
                edit = Edit(0.5, 2.5, 0.2, 0.3)
                for keep in (True, False):
                    output = self.root / f"out-{keep}.{fmt}"
                    export_audio(info, edit, output, "source", keep)
                    data = _probe_data(output)
                    self.assertAlmostEqual(probe(output).duration, 2, delta=0.1)
                    self.assertEqual(probe(output).tags.get("title"), "合成测试" if keep else None)
                    self.assertEqual(any(s.get("disposition", {}).get("attached_pic") for s in data["streams"]), keep)
                with self.assertRaisesRegex(ValueError, "不能覆盖"):
                    export_audio(info, edit, self.source, "source", overwrite=True)
                self.assertEqual(self.source.read_bytes(), original)

    def test_missing_metadata_is_playable(self):
        self.source.write_bytes(make_ncm(self.encoded_audio("flac")))
        self.assertAlmostEqual(open_audio(self.source, self.cache).duration, 3, places=3)

    def test_invalid_containers_leave_no_temporary_files(self):
        valid = make_ncm(b"fLaC" + bytes(64))
        # Header, key block, metadata block, cover bounds, payload and empty payload.
        cases = [b"not-ncm", valid[:11], valid[:10] + struct.pack("<I", 2**32-1),
                 valid[:-65], make_ncm(b""), make_ncm(b"wrong-audio")]
        bad_key = bytearray(valid)
        bad_key[14:62] = bytes(48)
        cases.append(bytes(bad_key))
        for data in cases:
            with self.subTest(length=len(data)):
                self.source.write_bytes(data)
                with self.assertRaises(ValueError):
                    decode_ncm(self.source, self.cache)
                self.assertEqual(list(self.cache.iterdir()), [])

    def test_probe_failure_cleans_decoded_audio(self):
        self.source.write_bytes(make_ncm(b"fLaC" + bytes(64)))
        with self.assertRaises((ValueError, RuntimeError)):
            open_audio(self.source, self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])
