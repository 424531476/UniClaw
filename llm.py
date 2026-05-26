from enum import StrEnum
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


def _create_http_client():
    """创建带代理的 HTTP 客户端"""
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
    effort = Effort.LOW if thinking else Effort.NONE

    if compare_urls(
        os.environ.get("OPENAI_BASE_URL", ""),
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    ):
        extra_body = None
    else:
        extra_body = {
            "enable_thinking": enable_thinking,
            "thinking": {"type": thinking_type},
            "think": thinking,
            "reasoning": {"effort": effort},
        }
    model = ChatOpenAI(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stream_usage=True,
        request_timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=2,
        http_client=_create_http_client(),
        extra_body=extra_body,
    )
    if tools:
        model = model.bind_tools(tools)
    return model


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
    for chunk in model.stream(messages):
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
    if tools:
        model = model.bind_tools(tools)
    return model.invoke(messages)


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
    return await model.ainvoke(messages)
