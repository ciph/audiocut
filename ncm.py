"""Local streaming reader for the standard CTENFDAM NCM container."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import struct
import uuid

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from Crypto.Util.strxor import strxor

_CORE_KEY = bytes.fromhex("687A4852416D736F356B496E62617857")
_META_KEY = bytes.fromhex("2331346C6A6B5F215C5D2630553C2728")


def _metadata(data: bytes) -> dict:
    if not data:
        return {}
    try:
        data = bytes(x ^ 0x63 for x in data)
        prefix = b"163 key(Don't modify):"
        if not data.startswith(prefix):
            return {}
        encrypted = base64.b64decode(data[len(prefix):], validate=True)
        plain = unpad(AES.new(_META_KEY, AES.MODE_ECB).decrypt(encrypted), 16)
        kind, body = plain.split(b":", 1)
        meta = json.loads(body)
        if kind == b"dj" and isinstance(meta, dict):
            meta = meta.get("mainMusic", {})
        return meta if isinstance(meta, dict) else {}
    except (ValueError, UnicodeError, TypeError):
        # Optional tags must not prevent playback of intact audio.
        return {}


def decode_ncm(source: Path, directory: Path) -> tuple[Path, dict, Path | None]:
    """Return owned temporary audio/cover paths; remove partial files on failure."""
    created: list[Path] = []
    try:
        with source.open("rb") as stream:
            size = source.stat().st_size

            def read(count: int) -> bytes:
                if count < 0 or count > size - stream.tell():
                    raise ValueError("NCM 文件不完整或区块长度无效。")
                data = stream.read(count)
                if len(data) != count:
                    raise ValueError("NCM 文件读取不完整。")
                return data

            def integer() -> int:
                return struct.unpack("<I", read(4))[0]

            def block(limit: int) -> bytes:
                count = integer()
                if count > limit:
                    raise ValueError("NCM 信息区块过大或已损坏。")
                return read(count)

            if read(8) != b"CTENFDAM":
                raise ValueError("不是有效的 NCM 文件（文件头不匹配）。")
            read(2)
            encrypted = bytes(x ^ 0x64 for x in block(65536))
            try:
                key = unpad(AES.new(_CORE_KEY, AES.MODE_ECB).decrypt(encrypted), 16)
            except ValueError as exc:
                raise ValueError("NCM 密钥区块损坏或此版本不受支持。") from exc
            prefix = b"neteasecloudmusic"
            if not key.startswith(prefix) or len(key) == len(prefix):
                raise ValueError("NCM 音频密钥无效。")
            key = key[len(prefix):]
            box = list(range(256))
            cursor = 0
            for i in range(256):
                cursor = (cursor + box[i] + key[i % len(key)]) & 255
                box[i], box[cursor] = box[cursor], box[i]
            mask = bytes(box[(box[j] + box[(box[j] + j) & 255]) & 255]
                         for j in [i & 255 for i in range(1, 257)])
            meta = _metadata(block(16 * 1024 * 1024))
            read(5)  # Reserved CRC32 and image-version fields.
            frame_size, cover_size = integer(), integer()
            if cover_size > frame_size or frame_size > size - stream.tell() or cover_size > 32 * 1024 * 1024:
                raise ValueError("NCM 封面区块长度无效。")
            cover_data = read(cover_size)
            stream.seek(frame_size - cover_size, 1)
            stem = "ncm-" + uuid.uuid4().hex
            audio_path = None
            offset = 0
            output = None
            try:
                while chunk := stream.read(65536):
                    pattern = (mask * (len(chunk) // 256 + 2))[offset:offset + len(chunk)]
                    decoded = strxor(chunk, pattern)
                    offset = (offset + len(chunk)) & 255
                    if output is None:
                        if decoded.startswith(b"fLaC"):
                            extension = ".flac"
                        elif decoded.startswith(b"ID3") or (len(decoded) >= 2 and decoded[0] == 255
                                                           and decoded[1] & 0xE0 == 0xE0 and decoded[1] & 6):
                            extension = ".mp3"
                        else:
                            raise ValueError("NCM 内部音频不是受支持的 MP3 或 FLAC，或文件已损坏。")
                        audio_path = directory / (stem + extension)
                        created.append(audio_path)
                        output = audio_path.open("xb")
                    output.write(decoded)
            finally:
                if output is not None:
                    output.close()
            if audio_path is None:
                raise ValueError("NCM 文件没有音频数据。")
            cover_path = None
            extension = ".png" if cover_data.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg" if cover_data.startswith(b"\xff\xd8\xff") else None
            if extension:
                cover_path = directory / (stem + extension)
                created.append(cover_path)
                cover_path.write_bytes(cover_data)
            tags = {}
            for field, tag in (("musicName", "title"), ("album", "album")):
                if isinstance(meta.get(field), str):
                    tags[tag] = meta[field].replace("\0", "")
            artists = meta.get("artist", [])
            if isinstance(artists, list):
                names = [item[0] for item in artists if isinstance(item, list) and item and isinstance(item[0], str)]
                if names:
                    tags["artist"] = "; ".join(names).replace("\0", "")
            return audio_path, tags, cover_path
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
