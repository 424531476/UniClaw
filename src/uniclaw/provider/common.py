"""LLM 共享工具函数 — HTTP 客户端缓存、参数解析、消息转换等。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
from cachetools import TTLCache

from uniclaw.provider.types import Effort, Provider, Usage

REQUEST_TIMEOUT_SECONDS = 60 * 3


# ── URL 比较与检测 ─────────────────────────────────────────────


def compare_urls(url1, url2):
    p1 = urlparse(url1)
    p2 = urlparse(url2)
    return (
        p1.scheme == p2.scheme
        and p1.netloc.lower() == p2.netloc.lower()
        and p1.path.rstrip("/") == p2.path.rstrip("/")
    )


def is_google_api(openai_api_base):
    return compare_urls(
        openai_api_base,
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    )


def is_openrouter_api(openai_api_base):
    return compare_urls(
        openai_api_base,
        "https://openrouter.ai/api/v1/",
    )


def is_anthropic_api(base_url: str) -> bool:
    """判断是否为 Anthropic 官方 API。"""
    return compare_urls(base_url, "https://api.anthropic.com")


# ── HTTP 客户端缓存 ────────────────────────────────────────────

_http_client_cache: dict[str, httpx.Client] = TTLCache(maxsize=8, ttl=3600)
_async_http_client_cache: dict[str, httpx.AsyncClient] = TTLCache(maxsize=8, ttl=3600)


def create_http_client(
    base_url: str, proxy_url: str = ""
) -> httpx.Client | None:
    """创建带代理的同步 HTTP 客户端(带缓存)。"""
    if "://127.0.0.1" in base_url:
        return None
    if isinstance(proxy_url, str) and proxy_url.startswith("http"):
        cache_key = f"{base_url}:{proxy_url}"
        if cache_key not in _http_client_cache:
            _http_client_cache[cache_key] = httpx.Client(proxy=proxy_url)
        return _http_client_cache[cache_key]
    return None


def create_async_http_client(
    base_url: str, proxy_url: str = ""
) -> httpx.AsyncClient | None:
    """创建带代理的异步 HTTP 客户端(带缓存)。"""
    if "://127.0.0.1" in base_url:
        return None
    if isinstance(proxy_url, str) and proxy_url.startswith("http"):
        cache_key = f"{base_url}:{proxy_url}"
        if cache_key not in _async_http_client_cache:
            _async_http_client_cache[cache_key] = httpx.AsyncClient(proxy=proxy_url)
        return _async_http_client_cache[cache_key]
    return None


# ── 参数解析 ───────────────────────────────────────────────────


def resolve_params(config, **kwargs):
    """从 config 提取 LLM 参数作为默认值,kwargs 中的显式值优先。"""
    if config is not None:
        defaults = {
            "model_name": config.model_name,
            "openai_api_base": config.OPENAI_BASE_URL,
            "openai_api_key": config.OPENAI_API_KEY,
            "multimodal_model_name": config.multimodal_model_name,
            "proxy_url": config.proxy_url,
            "anthropic_api_key": config.ANTHROPIC_API_KEY,
            "anthropic_base_url": config.ANTHROPIC_BASE_URL,
            "provider": config.provider,
        }
        for key, val in defaults.items():
            if not kwargs.get(key):
                kwargs[key] = val
    return kwargs


def get_provider(config, **kwargs) -> Provider:
    """根据配置判断使用哪个 LLM 提供商。"""
    # 1. 显式指定 provider
    provider = kwargs.get("provider") or ""
    if not provider and config is not None:
        provider = config.provider or ""

    if provider:
        try:
            return Provider(provider)
        except ValueError:
            pass

    # 2. 只配了 Anthropic key、没配 OpenAI key → Anthropic
    if config is not None:
        if config.ANTHROPIC_API_KEY and not config.OPENAI_API_KEY:
            return Provider.ANTHROPIC

    # 3. 默认 OpenAI
    return Provider.OPENAI


# ── extra_body 构建 ────────────────────────────────────────────


def build_extra_body(
    openai_api_base: str, enable_thinking: bool, thinking: bool
) -> dict | None:
    """构建 thinking/reasoning 相关的 extra_body。"""
    if is_google_api(openai_api_base):
        return None
    thinking_type = "enabled" if thinking else "disabled"
    extra_body = {
        "enable_thinking": enable_thinking,
        "thinking": {"type": thinking_type},
    }
    if not thinking and is_openrouter_api(openai_api_base):
        extra_body["reasoning"] = {"effort": Effort.NONE}
    return extra_body


# ── 消息格式转换 ───────────────────────────────────────────────

def safe_parse_args(arguments: str) -> dict:
    """尝试解析工具参数 JSON,不完整时返回空 dict。"""
    if not arguments:
        return {}
    try:
        import json

        result = json.loads(arguments)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def is_multimodal_error(e: Exception) -> bool:
    """判断是否为多模态内容不支持的错误(HTTP 400/404 + 相关关键词)。"""
    status = getattr(e, "status_code", None) or getattr(e, "status", None)
    if status not in (400, 404):
        return False
    msg = str(e).lower()
    return any(
        kw in msg
        for kw in (
            "image",
            "audio",
            "video",
            "multimodal",
            "input_audio",
            "image_url",
            "video_url",
        )
    )



# ── 用量记录 ───────────────────────────────────────────────────


async def record_usage_async(model_name: str, usage: Usage | None):
    """记录 token 用量 (异步)。"""
    if not usage or (not usage.input_tokens and not usage.output_tokens):
        return
    from uniclaw.utils.usage import record_usage

    await record_usage(usage.input_tokens, usage.output_tokens, model=model_name)
