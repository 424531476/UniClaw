"""Token 估算工具 — 模型编码器映射与 token 计数。"""

from __future__ import annotations

from typing import Any

# 模型到 tiktoken 编码器的映射
MODEL_ENCODINGS: dict[str, str] = {
    # GPT-4o / GPT-4.1 系列使用 o200k_base
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4.1": "o200k_base",
    "gpt-4.1-mini": "o200k_base",
    "gpt-4.1-nano": "o200k_base",
    # 其他 GPT 系列使用 cl100k_base
    "gpt-3.5-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
}

_encoder_cache: dict[str, Any] = {}


def get_encoder(model: str = None):
    """获取 tiktoken 编码器(带缓存)。tiktoken 未安装时返回 None。"""
    try:
        import tiktoken
    except ImportError:
        return None
    if not model:
        return tiktoken.get_encoding("cl100k_base")
    short_name = model.split("/")[-1] if "/" in model else model
    encoding_name = "cl100k_base"
    for key, enc in MODEL_ENCODINGS.items():
        if short_name.startswith(key):
            encoding_name = enc
            break
    if encoding_name not in _encoder_cache:
        try:
            _encoder_cache[encoding_name] = tiktoken.get_encoding(encoding_name)
        except Exception:
            return None
    return _encoder_cache[encoding_name]


def count_tokens(text: str, model: str = None) -> int:
    """估算文本的 token 数量。tiktoken 未安装时按字符数近似。"""
    encoder = get_encoder(model)
    if encoder is None:
        return int(len(text) / 2.8)
    try:
        return len(encoder.encode(text))
    except Exception:
        return int(len(text) / 2.8)
