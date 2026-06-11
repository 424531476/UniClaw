"""LLM 调用层 — 使用 OpenAI SDK,支持流式/同步/异步调用。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import OpenAI, AsyncOpenAI

REQUEST_TIMEOUT_SECONDS = 60 * 3


# ── 数据类型 ──────────────────────────────────────────────────


@dataclass
class UsageMeta:
    """Token 用量。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self):
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens


@dataclass
class StreamChunk:
    """流式 chunk,支持 += 累积。"""

    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    new_tool_call_name: str = ""
    new_tool_call_args: dict = field(default_factory=dict)
    model_name: str = ""
    usage: UsageMeta | None = None

    def __iadd__(self, other: StreamChunk) -> StreamChunk:
        self.content += other.content
        self.reasoning_content += other.reasoning_content
        self.tool_calls.extend(other.tool_calls)
        if other.model_name:
            self.model_name = other.model_name
        if other.usage:
            self.usage = other.usage
        return self


@dataclass
class AIMessage:
    """AI 响应消息(非流式)。"""

    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    model_name: str = ""
    usage: UsageMeta | None = None


# ── 工具格式转换 ──────────────────────────────────────────────


def tool_to_openai(tool) -> dict:
    """将 Tool 对象转换为 OpenAI function calling 格式。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


# ── 辅助函数 ──────────────────────────────────────────────────


def compare_urls(url1, url2):
    p1 = urlparse(url1)
    p2 = urlparse(url2)
    return (
        p1.scheme == p2.scheme
        and p1.netloc.lower() == p2.netloc.lower()
        and p1.path.rstrip("/") == p2.path.rstrip("/")
    )


def _create_http_client(
    openai_api_base: str, proxy_url: str = ""
) -> httpx.Client | None:
    """创建带代理的 HTTP 客户端。"""
    if "://127.0.0.1" in openai_api_base:
        return None
    if isinstance(proxy_url, str) and proxy_url.startswith("http"):
        return httpx.Client(proxy=proxy_url)
    return None


def _resolve_params(config, **kwargs):
    """从 config 提取 LLM 参数作为默认值,kwargs 中的显式值优先。"""
    if config is not None:
        defaults = {
            "model_name": config.model_name,
            "openai_api_base": config.OPENAI_BASE_URL,
            "openai_api_key": config.OPENAI_API_KEY,
            "multimodal_model_name": config.multimodal_model_name,
            "proxy_url": config.proxy_url,
        }
        for key, val in defaults.items():
            if not kwargs.get(key):
                kwargs[key] = val
    return kwargs


class Effort(StrEnum):
    XHIGH = "xhigh"
    HIGH = "high"
    MEDIUM = "medium"
    MINIMAL = "minimal"
    LOW = "low"
    NONE = "none"


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


def _build_extra_body(
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


def _build_openai_client(
    openai_api_base: str, openai_api_key: str, proxy_url: str = ""
) -> OpenAI:
    """创建 OpenAI 客户端。"""
    http_client = _create_http_client(openai_api_base, proxy_url)
    return OpenAI(
        api_key=openai_api_key,
        base_url=openai_api_base,
        http_client=http_client,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=2,
    )


def _build_async_openai_client(
    openai_api_base: str, openai_api_key: str, proxy_url: str = ""
) -> AsyncOpenAI:
    """创建异步 OpenAI 客户端。"""
    http_client = _create_http_client(openai_api_base, proxy_url)
    return AsyncOpenAI(
        api_key=openai_api_key,
        base_url=openai_api_base,
        http_client=http_client,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=2,
    )


# ── ThoughtParser ─────────────────────────────────────────────


class ThoughtParser:
    """流式解析 <thought>/<thinking> 标签。"""

    class Phase(Enum):
        SEEKING_OPEN = "seeking_open"
        IN_THOUGHT = "in_thought"
        TEXT = "text"

    def __init__(self):
        self.phase = self.Phase.SEEKING_OPEN
        self.buffer = ""
        self.close_tag = ""
        self.tags = ("<thought>", "</thought>"), ("<think>", "</think>")

    def process(self, text: str) -> tuple[str, str]:
        if self.phase == self.Phase.TEXT:
            return "", text
        text = self.buffer + text
        self.buffer = ""
        if self.phase == self.Phase.SEEKING_OPEN:
            return self._seeking_open(text)
        elif self.phase == self.Phase.IN_THOUGHT:
            return self._in_thought(text)

    def _seeking_open(self, text: str) -> tuple[str, str]:
        for open_tag, close_tag in self.tags:
            open_idx = text.find(open_tag)
            if open_idx < 0:
                continue
            self.phase = self.Phase.IN_THOUGHT
            self.close_tag = close_tag
            after = text[open_idx + len(open_tag) :]
            if after:
                return self.process(after)
        else:
            for open_tag, close_tag in self.tags:
                if open_tag.startswith(text):
                    self.buffer = text
                    return "", ""
            else:
                self.phase = self.Phase.TEXT
                return "", text

    def _in_thought(self, text: str) -> tuple[str, str]:
        close_tag = self.close_tag
        close_idx = text.find(close_tag)
        if close_idx >= 0:
            self.phase = self.Phase.TEXT
            thinking = text[:close_idx]
            context = text[close_idx + len(close_tag) :]
            return thinking, context
        else:
            for i in range(len(close_tag), 0, -1):
                if text.endswith(close_tag[:i]):
                    self.buffer = text
                    return
            else:
                return text, ""


# ── 多模态降级 ────────────────────────────────────────────────

_MULTIMODAL_TYPES = {"image_url", "input_audio", "video_url"}


def _is_multimodal_error(e: Exception) -> bool:
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


def _extract_media_url(block: dict) -> tuple[str, str]:
    """从多模态 content block 中提取 URL 和媒体类型。"""
    btype = block.get("type")
    if btype == "image_url":
        return block["image_url"]["url"], "image"
    if btype == "input_audio":
        return block["input_audio"]["data"], "audio"
    if btype == "video_url":
        return block["video_url"]["url"], "video"
    return "", ""


async def _describe_multimodal(messages, mm_model: str | None = None, config=None):
    """将消息中的多模态内容块替换为描述文本。"""
    cleaned = []
    for m in messages:
        content = (
            m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        )
        if not isinstance(content, list):
            cleaned.append(m)
            continue
        new_blocks = []
        for b in content:
            if isinstance(b, dict) and b.get("type") in _MULTIMODAL_TYPES:
                if mm_model:
                    media_url, media_type = _extract_media_url(b)
                    if media_url:
                        from uniclaw.utils.media_describer import describe_media

                        desc = await describe_media(
                            media_url, media_type, mm_model, config=config
                        )
                        new_blocks.append({"type": "text", "text": desc})
                        continue
                new_blocks.append({"type": "text", "text": f"[{b['type']}]"})
            else:
                new_blocks.append(b)
        if isinstance(m, dict):
            cleaned.append({**m, "content": new_blocks})
        else:
            m.content = new_blocks
            cleaned.append(m)
    return cleaned


# ── 用量记录 ──────────────────────────────────────────────────


async def _record_usage(model_name: str, usage: UsageMeta | None):
    """记录 token 用量。"""
    if not usage or (not usage.input_tokens and not usage.output_tokens):
        return
    from uniclaw.utils.usage import record_usage

    await record_usage(usage.input_tokens, usage.output_tokens, model=model_name)


# ── 消息格式转换 ──────────────────────────────────────────────

_OPENAI_MSG_KEYS = {"role", "content", "tool_calls", "tool_call_id", "name"}


def _messages_to_openai(messages) -> list[dict]:
    """将消息列表转换为 OpenAI API 格式。"""
    result = []
    for m in messages:
        if isinstance(m, dict):
            msg = m
        elif hasattr(m, "to_message"):
            msg = m.to_message()
        elif hasattr(m, "content"):
            role = getattr(m, "role", "user")
            msg = {"role": role, "content": m.content}
        else:
            msg = {"role": "user", "content": str(m)}
        # 清理非 OpenAI 标准字段
        clean = {
            k: v for k, v in msg.items() if k in _OPENAI_MSG_KEYS and v is not None
        }
        result.append(clean)
    return result


# ── 核心调用函数 ──────────────────────────────────────────────


def _in_event_loop() -> bool:
    """检测当前是否在 asyncio 事件循环中。"""
    import asyncio
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def stream(
    messages,
    model_name: str = "",
    openai_api_base: str = "",
    openai_api_key: str = "",
    multimodal_model_name: str | None = None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
    proxy_url: str = "",
    config=None,
):
    """流式调用 LLM,每次 yield StreamChunk (delta)。"""
    p = _resolve_params(
        config,
        model_name=model_name,
        openai_api_base=openai_api_base,
        openai_api_key=openai_api_key,
        multimodal_model_name=multimodal_model_name,
        proxy_url=proxy_url,
    )
    client = _build_openai_client(
        p["openai_api_base"], p["openai_api_key"], p["proxy_url"]
    )
    extra_body = _build_extra_body(p["openai_api_base"], enable_thinking, thinking)
    openai_tools = [tool_to_openai(t) for t in tools] if tools else None

    kwargs = dict(
        model=p["model_name"],
        messages=_messages_to_openai(messages),
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stream=True,
    )
    if openai_tools:
        kwargs["tools"] = openai_tools
    if extra_body:
        kwargs["extra_body"] = extra_body

    try:
        yield from _stream_inner(client, kwargs)
    except Exception as e:
        if _is_multimodal_error(e) and p["multimodal_model_name"]:
            import asyncio
            # 仅在无事件循环时才能用 asyncio.run
            if not _in_event_loop():
                kwargs["messages"] = _messages_to_openai(
                    asyncio.run(_describe_multimodal(
                        messages, p["multimodal_model_name"], config=config
                    ))
                )
                yield from _stream_inner(client, kwargs)
            else:
                raise
        else:
            raise


def _safe_parse_args(arguments: str) -> dict:
    """尝试解析工具参数 JSON,不完整时返回空 dict。"""
    if not arguments:
        return {}
    try:
        import json

        result = json.loads(arguments)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _stream_inner(client: OpenAI, kwargs: dict):
    """内部流式调用,处理 delta 累积。"""
    parser = ThoughtParser()
    # tool_calls 按 index 累积
    tc_accum: dict[int, dict] = {}

    response = client.chat.completions.create(**kwargs)
    for chunk in response:
        sc = StreamChunk()

        # content + reasoning + tool_calls
        if chunk.choices:
            delta = chunk.choices[0].delta

            raw_content = delta.content or ""
            if raw_content:
                reasoning, content = parser.process(raw_content)
                sc.content = content
                sc.reasoning_content = reasoning

            # reasoning_content (部分 API 直接返回)
            rc = getattr(delta, "reasoning_content", None) or getattr(
                delta, "reasoning", None
            )
            if rc:
                sc.reasoning_content += rc

            # tool_calls — 累积,首次获得 name 时标记通知
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    is_new = idx not in tc_accum
                    if is_new:
                        tc_accum[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    tc = tc_accum[idx]
                    if tc_delta.id:
                        tc["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc["function"]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc["function"]["arguments"] += tc_delta.function.arguments
                    if tc["function"]["name"] and (
                        is_new
                        or (tc_delta.function and tc_delta.function.arguments)
                    ):
                        sc.new_tool_call_name = tc["function"]["name"]
                        sc.new_tool_call_args = _safe_parse_args(
                            tc["function"]["arguments"]
                        )

        # usage
        if chunk.usage:
            sc.usage = UsageMeta(
                input_tokens=chunk.usage.prompt_tokens or 0,
                output_tokens=chunk.usage.completion_tokens or 0,
                total_tokens=chunk.usage.total_tokens or 0,
            )

        if hasattr(chunk, "model") and chunk.model:
            sc.model_name = chunk.model

        yield sc

    # 流结束 — yield 累积的 tool_calls
    if tc_accum:
        final = StreamChunk()
        final.tool_calls = [tc_accum[i] for i in sorted(tc_accum)]
        yield final


async def astream(
    messages,
    model_name: str = "",
    openai_api_base: str = "",
    openai_api_key: str = "",
    multimodal_model_name: str | None = None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
    proxy_url: str = "",
    config=None,
):
    """异步流式调用 LLM,每次 yield StreamChunk (delta)。"""
    p = _resolve_params(
        config,
        model_name=model_name,
        openai_api_base=openai_api_base,
        openai_api_key=openai_api_key,
        multimodal_model_name=multimodal_model_name,
        proxy_url=proxy_url,
    )
    client = _build_async_openai_client(
        p["openai_api_base"], p["openai_api_key"], p["proxy_url"]
    )
    extra_body = _build_extra_body(p["openai_api_base"], enable_thinking, thinking)
    openai_tools = [tool_to_openai(t) for t in tools] if tools else None

    kwargs = dict(
        model=p["model_name"],
        messages=_messages_to_openai(messages),
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stream=True,
    )
    if openai_tools:
        kwargs["tools"] = openai_tools
    if extra_body:
        kwargs["extra_body"] = extra_body

    try:
        async for chunk in _astream_inner(client, kwargs):
            yield chunk
    except Exception as e:
        if _is_multimodal_error(e) and p["multimodal_model_name"]:
            kwargs["messages"] = _messages_to_openai(
                await _describe_multimodal(
                    messages, p["multimodal_model_name"], config=config
                )
            )
            async for chunk in _astream_inner(client, kwargs):
                yield chunk
        else:
            raise


async def _astream_inner(client: AsyncOpenAI, kwargs: dict):
    """内部异步流式调用,处理 delta 累积。"""
    parser = ThoughtParser()
    tc_accum: dict[int, dict] = {}

    response = await client.chat.completions.create(**kwargs)
    async for chunk in response:
        sc = StreamChunk()

        if chunk.choices:
            delta = chunk.choices[0].delta

            raw_content = delta.content or ""
            if raw_content:
                reasoning, content = parser.process(raw_content)
                sc.content = content
                sc.reasoning_content = reasoning

            rc = getattr(delta, "reasoning_content", None) or getattr(
                delta, "reasoning", None
            )
            if rc:
                sc.reasoning_content += rc

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    is_new = idx not in tc_accum
                    if is_new:
                        tc_accum[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    tc = tc_accum[idx]
                    if tc_delta.id:
                        tc["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc["function"]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc["function"]["arguments"] += tc_delta.function.arguments
                    if tc["function"]["name"] and (
                        is_new
                        or (tc_delta.function and tc_delta.function.arguments)
                    ):
                        sc.new_tool_call_name = tc["function"]["name"]
                        sc.new_tool_call_args = _safe_parse_args(
                            tc["function"]["arguments"]
                        )

        if chunk.usage:
            sc.usage = UsageMeta(
                input_tokens=chunk.usage.prompt_tokens or 0,
                output_tokens=chunk.usage.completion_tokens or 0,
                total_tokens=chunk.usage.total_tokens or 0,
            )

        if hasattr(chunk, "model") and chunk.model:
            sc.model_name = chunk.model

        yield sc

    if tc_accum:
        final = StreamChunk()
        final.tool_calls = [tc_accum[i] for i in sorted(tc_accum)]
        yield final


def chat(
    messages,
    model_name: str = "",
    openai_api_base: str = "",
    openai_api_key: str = "",
    multimodal_model_name: str | None = None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
    proxy_url: str = "",
    config=None,
) -> AIMessage:
    """同步调用 LLM,返回 AIMessage。"""
    p = _resolve_params(
        config,
        model_name=model_name,
        openai_api_base=openai_api_base,
        openai_api_key=openai_api_key,
        multimodal_model_name=multimodal_model_name,
        proxy_url=proxy_url,
    )
    client = _build_openai_client(
        p["openai_api_base"], p["openai_api_key"], p["proxy_url"]
    )
    extra_body = _build_extra_body(p["openai_api_base"], enable_thinking, thinking)
    openai_tools = [tool_to_openai(t) for t in tools] if tools else None

    kwargs = dict(
        model=p["model_name"],
        messages=_messages_to_openai(messages),
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
    )
    if openai_tools:
        kwargs["tools"] = openai_tools
    if extra_body:
        kwargs["extra_body"] = extra_body

    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as e:
        if _is_multimodal_error(e) and p["multimodal_model_name"]:
            import asyncio
            if not _in_event_loop():
                kwargs["messages"] = _messages_to_openai(
                    asyncio.run(_describe_multimodal(
                        messages, p["multimodal_model_name"], config=config
                    ))
                )
                response = client.chat.completions.create(**kwargs)
            else:
                raise
        else:
            raise

    return _response_to_ai_message(response)


async def achat(
    messages,
    model_name: str = "",
    openai_api_base: str = "",
    openai_api_key: str = "",
    multimodal_model_name: str | None = None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
    proxy_url: str = "",
    config=None,
) -> AIMessage:
    """异步调用 LLM,返回 AIMessage。"""
    p = _resolve_params(
        config,
        model_name=model_name,
        openai_api_base=openai_api_base,
        openai_api_key=openai_api_key,
        multimodal_model_name=multimodal_model_name,
        proxy_url=proxy_url,
    )
    client = _build_async_openai_client(
        p["openai_api_base"], p["openai_api_key"], p["proxy_url"]
    )
    extra_body = _build_extra_body(p["openai_api_base"], enable_thinking, thinking)
    openai_tools = [tool_to_openai(t) for t in tools] if tools else None

    kwargs = dict(
        model=p["model_name"],
        messages=_messages_to_openai(messages),
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
    )
    if openai_tools:
        kwargs["tools"] = openai_tools
    if extra_body:
        kwargs["extra_body"] = extra_body

    try:
        response = await client.chat.completions.create(**kwargs)
    except Exception as e:
        if _is_multimodal_error(e) and p["multimodal_model_name"]:
            kwargs["messages"] = _messages_to_openai(
                await _describe_multimodal(
                    messages, p["multimodal_model_name"], config=config
                )
            )
            response = await client.chat.completions.create(**kwargs)
        else:
            raise

    return await _response_to_ai_message_async(response)


def _response_to_ai_message(response) -> AIMessage:
    """将 OpenAI 响应转换为 AIMessage。"""
    choice = response.choices[0]
    msg = choice.message

    # tool_calls — 直接保留 OpenAI 格式
    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            tool_calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "",
                    },
                }
            )

    # reasoning_content
    reasoning = (
        getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or ""
    )

    # usage
    usage = None
    if response.usage:
        usage = UsageMeta(
            input_tokens=response.usage.prompt_tokens or 0,
            output_tokens=response.usage.completion_tokens or 0,
            total_tokens=response.usage.total_tokens or 0,
        )

    # post-process: parse <thought> tags from content
    content = msg.content or ""
    if content:
        parser = ThoughtParser()
        thinking_text, content = parser.process(content)
        reasoning = thinking_text + reasoning

    ai_msg = AIMessage(
        content=content,
        reasoning_content=reasoning,
        tool_calls=tool_calls,
        model_name=response.model or "",
        usage=usage,
    )
    return ai_msg


async def _response_to_ai_message_async(response) -> AIMessage:
    """异步版本:转换响应并记录用量。"""
    ai_msg = _response_to_ai_message(response)
    await _record_usage(ai_msg.model_name, ai_msg.usage)
    return ai_msg
