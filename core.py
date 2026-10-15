"""Audio inspection and lossless edit rendering through local FFmpeg tools."""

from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time


CURVES = {
    "对数（底数 3）": "log3",
    "正弦（恒功率淡入）": "sine_in",
    "对数（底数 1.41）": "log141",
    "反 S 形曲线": "ihsin",
    "线性": "tri",
    "S 形曲线": "hsin",
    "指数（底数 1.41）": "exp141",
    "正弦（恒功率淡出）": "sine_out",
    "指数（底数 3）": "exp3",
}
_CURVE_BASES = {"log3": 3, "log141": 1.41, "exp141": 1.41, "exp3": 3}
FORMATS = {
    "wav": "WAV · 无损", "mp3": "MP3 · 通用", "flac": "FLAC · 无损压缩",
    "m4a": "M4A · AAC / ALAC", "aac": "AAC · 裸音频", "ogg": "OGG · Vorbis",
    "opus": "Opus · 高效压缩", "aiff": "AIFF · 无损",
}
_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


@dataclass(frozen=True)
class AudioInfo:
    path: Path
    duration: float
    sample_rate: int
    channels: int
    codec: str
    bit_depth: int
    tags: dict
    source_path: Path | None = None

    @property
    def original_path(self) -> Path:
        return self.source_path or self.path


@dataclass(frozen=True)
class Edit:
    start: float
    end: float
    fade_in: float = 0
    fade_out: float = 0
    curve_in: str = "sine_in"
    curve_out: str = "sine_out"

    @property
    def duration(self) -> float:
        return self.end - self.start

    def validate(self, duration: float) -> None:
        values = (duration, self.start, self.end, self.fade_in, self.fade_out)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError("时间必须是有效数字。")
        if duration <= 0 or self.start < 0 or self.end > duration + 0.000001 or self.end <= self.start:
            raise ValueError("裁剪范围必须位于音频内，且结束时间大于开始时间。")
        if self.fade_in < 0 or self.fade_out < 0 or max(self.fade_in, self.fade_out) > self.duration + 0.000001:
            raise ValueError("淡入、淡出时长须介于 0 和裁剪后时长之间。")
        if self.curve_in not in CURVES.values() or self.curve_out not in CURVES.values():
            raise ValueError("不支持此淡入淡出曲线。")


def normalize_format(value: str) -> str:
    value = value.lower().strip().lstrip(".")
    return {"wave": "wav", "aif": "aiff", "aifc": "aiff", "oga": "ogg"}.get(value, value)


def resolve_tool(name: str) -> str:
    # Packaged copies take precedence, so installing the app does not change PATH.
    suffix = ".exe" if os.name == "nt" else ""
    bases = [Path(__file__).resolve().parent, Path(sys.executable).resolve().parent]
    if getattr(sys, "_MEIPASS", None):
        bases.insert(0, Path(sys._MEIPASS))
    for base in bases:
        for directory in (base, base / "bin", base / "ffmpeg" / "bin"):
            candidate = directory / (name + suffix)
            if candidate.is_file():
                return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f"未找到 {name}。请安装 FFmpeg，或将工具放入程序的 bin 文件夹。")


def _run(args: list[str], timeout: float = 60) -> bytes:
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                creationflags=_CREATE_FLAGS, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("音频处理超时，请尝试较短的文件。") from exc
    except OSError as exc:
        raise RuntimeError(f"无法启动音频处理工具：{exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-1600:]
        raise RuntimeError(f"音频处理失败：{detail or '文件可能已损坏或格式不受支持。'}")
    return result.stdout


def _probe_data(path: Path) -> dict:
    try:
        return json.loads(_run([resolve_tool("ffprobe"), "-v", "error", "-show_format",
                                "-show_streams", "-show_chapters", "-of", "json", str(path)]))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RuntimeError("无法读取音频文件信息。") from exc


def probe(path: str | Path) -> AudioInfo:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("音频文件不存在。")
    data = _probe_data(path)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise ValueError("此文件中没有可播放的音轨。")
    try:
        duration = float(audio.get("duration") or data.get("format", {}).get("duration", 0))
        rate, channels = int(audio.get("sample_rate", 0)), int(audio.get("channels", 0))
        depth = int(audio.get("bits_per_raw_sample", 0) or audio.get("bits_per_sample", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("文件中的音频参数无效。") from exc
    if not math.isfinite(duration) or duration <= 0 or rate <= 0 or channels <= 0:
        raise ValueError("无法确定此音频的有效时长、采样率或声道数。")
    tags = dict(data.get("format", {}).get("tags", {}))
    tags.update(audio.get("tags", {}))
    return AudioInfo(path, duration, rate, channels, audio.get("codec_name", "unknown"), depth, tags)


def open_audio(path: str | Path, temporary_directory: Path) -> AudioInfo:
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != ".ncm":
        return probe(path)
    from ncm import decode_ncm

    audio, tags, cover = decode_ncm(path, temporary_directory)
    remuxed = audio.with_name(audio.stem + "-tagged" + audio.suffix)
    try:
        info = probe(audio)
        if tags or cover:
            args = [resolve_tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-i", str(audio)]
            if cover:
                args += ["-i", str(cover)]
            args += ["-map", "0:a:0", "-map", "1:v:0" if cover else "0:v?", "-c", "copy", "-map_metadata", "0"]
            if cover:
                args += ["-disposition:v:0", "attached_pic"]
            for key, value in tags.items():
                args += ["-metadata", f"{key}={value}"]
            _run([*args, str(remuxed)], timeout=max(300, min(7200, info.duration)))
            info = probe(remuxed)
            audio.unlink()
        return replace(info, source_path=path)
    except BaseException:
        audio.unlink(missing_ok=True)
        remuxed.unlink(missing_ok=True)
        raise
    finally:
        if cover:
            cover.unlink(missing_ok=True)


def gain_at(progress: float, curve: str) -> float:
    """Normalized rising segment. A descending segment uses 1 - gain_at(t)."""
    if curve not in CURVES.values() or not math.isfinite(progress):
        raise ValueError("无效的音量曲线参数。")
    x = max(0.0, min(1.0, progress))
    if x in (0, 1):
        return x
    if curve in _CURVE_BASES:
        base = _CURVE_BASES[curve]
        return math.log1p((base - 1) * x) / math.log(base) if curve.startswith("log") else math.expm1(x * math.log(base)) / (base - 1)
    if curve == "sine_in":
        return math.sin(math.pi * x / 2)
    if curve == "sine_out":
        return 1 - math.cos(math.pi * x / 2)
    if curve == "hsin":
        return (1 - math.cos(math.pi * x)) / 2
    if curve == "ihsin":
        return math.acos(1 - 2 * x) / math.pi
    return x


def _gain_expression(progress: str, curve: str) -> str:
    x = f"clip({progress},0,1)"
    if curve in _CURVE_BASES:
        base = _CURVE_BASES[curve]
        return f"(log(1+({base}-1)*{x})/log({base}))" if curve.startswith("log") else f"((pow({base},{x})-1)/({base}-1))"
    return {
        "tri": x,
        "sine_in": f"sin(PI*{x}/2)",
        "sine_out": f"(1-cos(PI*{x}/2))",
        "hsin": f"((1-cos(PI*{x}))/2)",
        "ihsin": f"(acos(1-2*{x})/PI)",
    }[curve]


def waveform(info: AudioInfo, bins: int = 1200, cancel: threading.Event | None = None) -> list[float]:
    """Reduce decoded audio to channel peaks in FFmpeg, with bounded Python memory."""
    if not isinstance(bins, int) or not 1 <= bins <= 100_000:
        raise ValueError("波形分段数须介于 1 和 100000 之间。")
    if cancel is not None and cancel.is_set():
        raise CancelledError("波形生成已取消。")
    total_samples = max(1, round(info.duration * info.sample_rate))
    frame_samples = max(1, min(8192, total_samples // bins))
    peaks = [0.0] * bins
    # Peak reduction keeps high frequencies and opposing stereo channels visible.
    filters = (f"asetnsamples=n={frame_samples}:p=0,"
               "astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=Peak_level,"
               "ametadata=mode=print:key=lavfi.astats.Overall.Peak_level:file=-")
    args = [resolve_tool("ffmpeg"), "-v", "error", "-nostdin", "-i", str(info.path),
            "-map", "0:a:0", "-vn", "-af", filters, "-f", "null", "-"]
    timed_out = threading.Event()
    watcher_done = threading.Event()
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=errors, creationflags=_CREATE_FLAGS)
        except OSError as exc:
            raise RuntimeError(f"无法生成波形：{exc}") from exc

        deadline = time.monotonic() + max(60, min(1800, info.duration * 2))

        def watch_process() -> None:
            while not watcher_done.wait(0.1):
                if process.poll() is not None:
                    return
                if time.monotonic() >= deadline:
                    timed_out.set()
                if timed_out.is_set() or (cancel is not None and cancel.is_set()):
                    try:
                        process.kill()
                    except OSError:
                        pass  # The process may have exited between poll and kill.
                    return

        watcher = threading.Thread(target=watch_process, daemon=True, name="audio-cut-waveform-watch")
        watcher.start()
        try:
            position = 0
            previous_index = -1
            for line in process.stdout:
                if line.startswith(b"lavfi.astats.Overall.Peak_level="):
                    decibels = float(line.partition(b"=")[2])
                    gain = 10 ** (decibels / 20) if math.isfinite(decibels) else 0
                    index = min(bins - 1, position * frame_samples * bins // total_samples)
                    peaks[index] = max(peaks[index], min(1.0, gain))
                    for skipped in range(previous_index + 1, index):
                        peaks[skipped] = peaks[index]
                    previous_index = index
                    position += 1
            process.wait()
            if cancel is not None and cancel.is_set():
                raise CancelledError("波形生成已取消。")
            if timed_out.is_set():
                raise RuntimeError("波形生成超时。")
            if process.returncode:
                errors.seek(0)
                detail = errors.read(1600).decode("utf-8", errors="replace")
                raise RuntimeError(f"无法生成波形：{detail}")
            if previous_index >= 0:
                for trailing in range(previous_index + 1, bins):
                    peaks[trailing] = peaks[previous_index]
        finally:
            watcher_done.set()
            watcher.join()
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
    return peaks


def _filters(edit: Edit) -> str:
    filters = [f"atrim=start={edit.start:.9f}:end={edit.end:.9f}", "asetpts=PTS-STARTPTS"]
    gains = []
    if edit.fade_in:
        gains.append(_gain_expression(f"t/{edit.fade_in:.9f}", edit.curve_in))
    if edit.fade_out:
        rising = _gain_expression(f"(t-{edit.duration - edit.fade_out:.9f})/{edit.fade_out:.9f}", edit.curve_out)
        gains.append(f"(1-{rising})")
    if gains:
        filters.append("aeval=exprs='val(ch)*" + "*".join(gains) + "':c=same")
    return ",".join(filters)


def _encoding(info: AudioInfo, fmt: str) -> list[str]:
    depth = info.bit_depth or 16
    if fmt in {"wav", "aiff"}:
        endian = "le" if fmt == "wav" else "be"
        if info.codec.startswith("pcm_f"):
            codec = f"pcm_f{64 if depth > 32 else 32}{endian}"
        else:
            bits = 16 if depth <= 16 else 24 if depth <= 24 else 32
            codec = f"pcm_s{bits}{endian}"
        return ["-c:a", codec]
    if fmt == "flac":
        return ["-c:a", "flac", "-sample_fmt", "s16" if depth <= 16 else "s32", "-compression_level", "5"]
    if fmt == "mp3":
        if info.channels > 2:
            raise ValueError("MP3 仅支持单声道或立体声。请改选 WAV、FLAC 等格式以保留声道。")
        return ["-c:a", "libmp3lame", "-q:a", "2"]
    if fmt == "m4a" and info.codec == "alac":
        return ["-c:a", "alac"]
    if fmt in {"m4a", "aac"}:
        return ["-c:a", "aac", "-b:a", f"{min(512, max(192, info.channels * 96))}k"]
    if fmt == "ogg":
        return ["-c:a", "libvorbis", "-q:a", "5"]
    if fmt == "opus":
        return ["-c:a", "libopus", "-b:a", f"{min(512, max(128, info.channels * 64))}k"]
    raise ValueError("不支持此保存格式。")


def _chapter_metadata(chapters: list[dict], edit: Edit) -> tuple[str | None, list[str]]:
    sections = []
    tags = []
    for chapter in chapters:
        try:
            start, end = float(chapter["start_time"]), float(chapter["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        start = round((max(start, edit.start) - edit.start) * 1_000_000)
        end = round((min(end, edit.end) - edit.start) * 1_000_000)
        if end <= start:
            continue
        lines = ["[CHAPTER]", "TIMEBASE=1/1000000", f"START={start}", f"END={end}"]
        # Passing tags as argv avoids ffmetadata's trailing-backslash/newline ambiguity.
        for key, value in chapter.get("tags", {}).items():
            tags += [f"-metadata:c:{len(sections)}", f"{key}={value}"]
        sections.append("\n".join(lines))
    return (";FFMETADATA1\n" + "\n".join(sections) + "\n" if sections else None), tags


def export_audio(info: AudioInfo, edit: Edit, destination: str | Path, format_key: str,
                 keep_metadata: bool = True, overwrite: bool = False) -> Path:
    edit.validate(info.duration)
    fmt = normalize_format(format_key)
    if fmt in {"source", "same"}:
        fmt = normalize_format(info.path.suffix)
    if fmt not in FORMATS:
        raise ValueError("源格式不支持导出，请选择 WAV、MP3、FLAC 等格式。")
    encoding = _encoding(info, fmt)
    destination = Path(destination).expanduser().absolute()
    if info.source_path is not None and destination.resolve() == info.original_path.resolve():
        raise ValueError("不能覆盖原 NCM 文件，请保存为 MP3、FLAC 等音频格式。")
    if not destination.parent.is_dir():
        raise ValueError("保存文件夹不存在。")
    if destination.exists() and not overwrite:
        raise FileExistsError("目标文件已存在，请更名或确认覆盖。")
    if destination.is_dir():
        raise ValueError("保存目标不能是文件夹。")
    inputs = [resolve_tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-i", str(info.path)]
    args = ["-map", "0:a:0"]
    chapter_text = None
    if keep_metadata:
        data = _probe_data(info.path)
        chapter_text, chapter_tags = _chapter_metadata(data.get("chapters", []), edit)
        args += ["-map_metadata", "0", "-map_metadata:s:a:0", "0:s:a:0", "-map_chapters", "1" if chapter_text else "-1", *chapter_tags]
        # Ogg/Opus tags live on the audio stream; other muxers read global tags.
        for key, value in info.tags.items():
            if key.lower() not in {"encoder", "duration", "major_brand", "minor_version", "compatible_brands"}:
                args += ["-metadata", f"{key}={value}", "-metadata:s:a:0", f"{key}={value}"]
        if fmt in {"aiff", "aac"}:
            args += ["-write_id3v2", "1"]
        if fmt == "wav" and any(k in info.tags for k in ("description", "originator", "origination_date", "time_reference")):
            args += ["-write_bext", "1"]
        if fmt in {"mp3", "flac", "m4a", "aiff"}:
            cover = next((s for s in data.get("streams", [])
                          if s.get("disposition", {}).get("attached_pic")
                          and s.get("codec_name") in {"mjpeg", "png"}), None)
            if cover is not None:
                args += ["-map", f"0:{cover['index']}", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    else:
        args += ["-map_metadata", "-1", "-map_metadata:s:a:0", "-1", "-map_chapters", "-1",
                 "-fflags", "+bitexact", "-flags:a", "+bitexact"]
    # Opus has fixed supported input rates; MP3/AAC likewise cannot represent all PCM rates.
    rate = info.sample_rate
    if fmt == "opus" and rate not in {8000, 12000, 16000, 24000, 48000}:
        rate = 48000
    if fmt == "mp3" and rate not in {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}:
        rate = 48000
    if fmt in {"m4a", "aac"} and info.codec != "alac" and rate not in {7350, 8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000}:
        rate = 48000
    args += ["-af", _filters(edit), "-ar", str(rate), "-ac", str(info.channels), *encoding]
    if fmt == "m4a":
        args += ["-movflags", "+faststart"]
    muxer = {"m4a": "ipod", "aac": "adts", "opus": "opus"}.get(fmt, fmt)
    temporary: Path | None = None
    chapter_file: Path | None = None
    try:
        if chapter_text:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=".audio-cut-",
                                             suffix=".ffmetadata", dir=destination.parent, delete=False) as handle:
                chapter_file = Path(handle.name)
                handle.write(chapter_text)
            inputs += ["-f", "ffmetadata", "-i", str(chapter_file)]
        with tempfile.NamedTemporaryFile(prefix=".audio-cut-", suffix="." + fmt, dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
        _run([*inputs, *args, "-f", muxer, str(temporary)], timeout=max(300, min(7200, info.duration * 10)))
        if temporary.stat().st_size == 0:
            raise RuntimeError("音频导出未产生有效文件。")
        if overwrite:
            os.replace(temporary, destination)
        elif os.name == "nt":
            os.rename(temporary, destination)
        else:
            os.link(temporary, destination)
            temporary.unlink()
        return destination
    except OSError as exc:
        raise RuntimeError(f"无法保存音频：{exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if chapter_file is not None:
            chapter_file.unlink(missing_ok=True)


def render_preview(info: AudioInfo, edit: Edit, destination: str | Path) -> Path:
    return export_audio(info, edit, destination, "wav", keep_metadata=False, overwrite=True)
