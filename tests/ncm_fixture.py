"""Synthetic NCM encoder used only for tests; never needs downloaded music."""
import base64
import json
import struct

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def make_ncm(audio: bytes, metadata=None, cover=b"", padding=37) -> bytes:
    key = b"synthetic-test-audio-key"
    key_data = AES.new(b"hzHRAmso5kInbaxW", AES.MODE_ECB).encrypt(pad(b"neteasecloudmusic" + key, 16))
    key_data = bytes(v ^ 0x64 for v in key_data)
    meta_data = b""
    if metadata is not None:
        plain = b"music:" + json.dumps(metadata, ensure_ascii=False).encode()
        encrypted = AES.new(b"#14ljk_!\\]&0U<'(", AES.MODE_ECB).encrypt(pad(plain, 16))
        meta_data = bytes(v ^ 0x63 for v in b"163 key(Don't modify):" + base64.b64encode(encrypted))
    box = list(range(256))
    last = 0
    for index in range(256):
        last = (last + box[index] + key[index % len(key)]) % 256
        box[index], box[last] = box[last], box[index]
    payload = bytearray(audio)
    for index in range(len(payload)):
        j = (index + 1) % 256
        payload[index] ^= box[(box[j] + box[(box[j] + j) % 256]) % 256]
    pack = lambda data: struct.pack("<I", len(data)) + data
    return (b"CTENFDAM\x02\x00" + pack(key_data) + pack(meta_data) + bytes(5)
            + struct.pack("<II", len(cover) + padding, len(cover)) + cover + bytes(padding) + payload)
