from __future__ import annotations

import io
import struct
from typing import TYPE_CHECKING

import requests

from .crypto import decode_aes_key, decrypt_aes_ecb
from .models import MediaContent

if TYPE_CHECKING:
    from .client import IlinkBotClient

try:
    import pysilk

    _HAS_SILK = True
except ImportError:
    _HAS_SILK = False

_EXT_MAP = {"image": ".jpg", "voice": ".silk", "video": ".mp4", "file": ""}


def detect_ext(data: bytes, media_type: str) -> str:
    if not data:
        return _EXT_MAP.get(media_type, "")
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:4] == b"#!AMR":
        return ".amr"
    if data[:10] == b"#!SILK_V3 ":
        return ".silk"
    return _EXT_MAP.get(media_type, "")


def download_media(media: MediaContent, bot: IlinkBotClient | None = None) -> bytes:
    headers = bot._headers() if bot else {}
    resp = requests.get(media.url, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.content
    if media.aes_key:
        data = decrypt_aes_ecb(data, decode_aes_key(media.aes_key))
    return data


def media_filename(media: MediaContent, data: bytes) -> str:
    ext = detect_ext(data, media.type)
    return media.file_name or f"{media.type}_{media.md5 or 'unknown'}{ext}"


def silk_to_wav(data: bytes, sample_rate: int = 24000) -> bytes:
    out = io.BytesIO()
    pysilk.decode(io.BytesIO(data), out, sample_rate=sample_rate)
    pcm = out.getvalue()
    return _pcm_to_wav(pcm, sample_rate=sample_rate)


def _pcm_to_wav(
    pcm: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    bits: int = 16,
) -> bytes:
    data_size = len(pcm)
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    buf = io.BytesIO()
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(
        struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits)
    )
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm)
    return buf.getvalue()
