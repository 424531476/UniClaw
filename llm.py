from enum import Enum, StrEnum
import os
from typing import Any, Mapping
import httpx
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models import base as _openai_base
from langchain_core.messages import AIMessageChunk, AIMessage
from config import get_config

REQUEST_TIMEOUT_SECONDS = 60 * 3

from urllib.parse import urlparse


def compare_urls(url1, url2):
    p1 = urlparse(url1)
    p2 = urlparse(url2)

    # 对比核心组件：协议(scheme)、域名(netloc)、路径(path)
    # 注意：netloc（域名）在对比时通常需要转为小写
    return (
        p1.scheme == p2.scheme
        and p1.netloc.lower() == p2.netloc.lower()
        and p1.path.rstrip("/") == p2.path.rstrip("/")
    )


# ---- Monkey-patch: 让 langchain_openai 支持 reasoning_content ----

_orig_convert_delta = _openai_base._convert_delta_to_message_chunk


def _patched_convert_delta(_dict: Mapping[str, Any], default_class: type):
    chunk = _orig_convert_delta(_dict, default_class)
    if isinstance(chunk, AIMessageChunk):
        rc = _dict.get("reasoning_content")
        if not rc:
            rc = _dict.get("reasoning")
        if rc:
            chunk.additional_kwargs["reasoning_content"] = rc
    return chunk


_openai_base._convert_delta_to_message_chunk = _patched_convert_delta


_orig_convert_dict = _openai_base._convert_dict_to_message


def _patched_convert_dict(_dict: Mapping[str, Any]):
    msg = _orig_convert_dict(_dict)
    if isinstance(msg, AIMessage):
        rc = _dict.get("reasoning_content")
        if not rc:
            rc = _dict.get("reasoning")
        if rc:
            msg.additional_kwargs["reasoning_content"] = rc
    return msg


_openai_base._convert_dict_to_message = _patched_convert_dict


_orig_convert_message_to_dict = _openai_base._convert_message_to_dict


def _patched_convert_message_to_dict(message, api="chat/completions"):
    d = _orig_convert_message_to_dict(message, api)
    if isinstance(message, AIMessage):
        rc = message.additional_kwargs.get("reasoning_content")
        if rc:
            d["reasoning_content"] = rc
    return d


_openai_base._convert_message_to_dict = _patched_convert_message_to_dict

# ---- End monkey-patch ----


def _create_http_client(openai_api_base: str) -> httpx.Client | None:
    """创建带代理的 HTTP 客户端"""
    if "://127.0.0.1" in openai_api_base:
        return None
    proxy_url = get_config().proxy_url
    if isinstance(proxy_url, str) and proxy_url.startswith("http"):
        return httpx.Client(proxy=proxy_url)
    return None


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


def get_llm(
    model_name=None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
):
    if not model_name:
        model_name = get_config().model_name
    thinking_type = "enabled" if thinking else "disabled"
    openai_api_base = os.environ.get("OPENAI_BASE_URL", "")
    if is_google_api(openai_api_base):
        extra_body = None
    else:
        extra_body = {
            "enable_thinking": enable_thinking,
            "thinking": {"type": thinking_type},
        }
        if not thinking and is_openrouter_api(openai_api_base):
            extra_body["reasoning"] = {"effort": Effort.NONE}
    model = ChatOpenAI(
        openai_api_base=openai_api_base,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stream_usage=True,
        request_timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=2,
        http_client=_create_http_client(openai_api_base),
        extra_body=extra_body,
    )
    if tools:
        model = model.bind_tools(tools)
    return model


class ThoughtParser:
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


def stream(
    messages,
    model_name=None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
):
    model = get_llm(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        tools=tools,
        enable_thinking=enable_thinking,
        thinking=thinking,
    )
    parser = ThoughtParser()
    for chunk in model.stream(messages):
        if chunk.content:
            thinking, content = parser.process(chunk.content)
            chunk.content = content
            if not hasattr(chunk, "additional_kwargs"):
                chunk.additional_kwargs = dict()
            chunk.additional_kwargs["reasoning_content"] = thinking
        yield chunk


def chat(
    messages,
    model_name=None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
) -> AIMessage:
    model = get_llm(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        tools=tools,
        enable_thinking=enable_thinking,
        thinking=thinking,
    )
    if tools:
        model = model.bind_tools(tools)
    ai_message = model.invoke(messages)
    if ai_message.content:
        parser = ThoughtParser()
        thinking, ai_message.content = parser.process(ai_message.content)
        if hasattr(ai_message, "additional_kwargs"):
            ai_message.additional_kwargs["reasoning_content"] = thinking
    return ai_message


async def achat(
    messages,
    model_name=None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
):
    """异步版本的chat函数,支持协程调用"""
    model = get_llm(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        tools=tools,
        enable_thinking=enable_thinking,
        thinking=thinking,
    )
    if tools:
        model = model.bind_tools(tools)
    ai_message = await model.ainvoke(messages)
    if ai_message.content:
        parser = ThoughtParser()
        thinking, ai_message.content = parser.process(ai_message.content)
        if hasattr(ai_message, "additional_kwargs"):
            ai_message.additional_kwargs["reasoning_content"] = thinking
    return ai_message
