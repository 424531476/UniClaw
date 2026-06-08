from enum import Enum, StrEnum
from typing import Any, Mapping
import httpx
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models import base as _openai_base
from langchain_core.messages import AIMessageChunk, AIMessage

REQUEST_TIMEOUT_SECONDS = 60 * 3

from urllib.parse import urlparse


def compare_urls(url1, url2):
    p1 = urlparse(url1)
    p2 = urlparse(url2)

    # 对比核心组件:协议(scheme)、域名(netloc)、路径(path)
    # 注意:netloc(域名)在对比时通常需要转为小写
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


def _create_http_client(openai_api_base: str, proxy_url: str = "") -> httpx.Client | None:
    """创建带代理的 HTTP 客户端"""
    if "://127.0.0.1" in openai_api_base:
        return None
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
    model_name: str,
    openai_api_base: str,
    openai_api_key: str,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
    proxy_url: str = "",
):
    if not model_name:
        raise ValueError("model_name 不能为空")
    thinking_type = "enabled" if thinking else "disabled"
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
        openai_api_key=openai_api_key,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stream_usage=True,
        request_timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=2,
        http_client=_create_http_client(openai_api_base, proxy_url),
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


_MULTIMODAL_TYPES = {"image_url", "input_audio", "video_url"}


def _is_multimodal_error(e: Exception) -> bool:
    """判断是否为多模态内容不支持的错误(HTTP 400/404 + 相关关键词)。"""
    status = getattr(e, "status_code", None) or getattr(e, "status", None)
    if status not in (400, 404):
        return False
    msg = str(e).lower()
    return any(kw in msg for kw in ("image", "audio", "video", "multimodal", "input_audio", "image_url", "video_url"))


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


def _describe_multimodal(messages, mm_model: str | None = None):
    """将消息中的多模态内容块替换为描述文本。

    mm_model 不为 None 时用多模态模型生成描述,否则用 [type] 占位符。
    """
    cleaned = []
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
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
                        desc = describe_media(media_url, media_type, mm_model)
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


def _record_usage_from_response(ai_message):
    """从 AI 响应中提取 token 用量和模型名并记录。
    - usage_metadata: input_tokens, output_tokens
    - response_metadata: model_name
    """
    from uniclaw.utils.usage import record_usage

    # 从 usage_metadata 获取 token 用量
    usage = getattr(ai_message, "usage_metadata", None) or {}
    in_tokens = getattr(usage, "input_tokens", 0) or 0
    out_tokens = getattr(usage, "output_tokens", 0) or 0

    # 从 response_metadata 获取模型名(以 API 实际返回为准)
    meta = getattr(ai_message, "response_metadata", {}) or {}
    model = meta.get("model_name", "") or ""

    if in_tokens or out_tokens:
        record_usage(in_tokens, out_tokens, model=model)


def stream(
    messages,
    model_name: str,
    openai_api_base: str,
    openai_api_key: str,
    multimodal_model_name: str | None = None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
    proxy_url: str = "",
):
    model = get_llm(
        model_name=model_name,
        openai_api_base=openai_api_base,
        openai_api_key=openai_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        tools=tools,
        enable_thinking=enable_thinking,
        thinking=thinking,
        proxy_url=proxy_url,
    )
    parser = ThoughtParser()
    try:
        for chunk in model.stream(messages):
            if chunk.content:
                thinking, content = parser.process(chunk.content)
                chunk.content = content
                if not hasattr(chunk, "additional_kwargs"):
                    chunk.additional_kwargs = dict()
                chunk.additional_kwargs["reasoning_content"] = thinking
            yield chunk
    except Exception as e:
        if _is_multimodal_error(e) and multimodal_model_name:
            for chunk in model.stream(_describe_multimodal(messages, multimodal_model_name)):
                if chunk.content:
                    thinking, content = parser.process(chunk.content)
                    chunk.content = content
                    if not hasattr(chunk, "additional_kwargs"):
                        chunk.additional_kwargs = dict()
                    chunk.additional_kwargs["reasoning_content"] = thinking
                yield chunk
        else:
            raise


def _post_process(ai_message):
    """解析 thinking 内容并记录用量。"""
    if ai_message.content:
        parser = ThoughtParser()
        thinking, ai_message.content = parser.process(ai_message.content)
        if hasattr(ai_message, "additional_kwargs"):
            ai_message.additional_kwargs["reasoning_content"] = thinking
    _record_usage_from_response(ai_message)
    return ai_message


def chat(
    messages,
    model_name: str,
    openai_api_base: str,
    openai_api_key: str,
    multimodal_model_name: str | None = None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
    proxy_url: str = "",
) -> AIMessage:
    model = get_llm(
        model_name=model_name,
        openai_api_base=openai_api_base,
        openai_api_key=openai_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        tools=tools,
        enable_thinking=enable_thinking,
        thinking=thinking,
        proxy_url=proxy_url,
    )
    try:
        ai_message = model.invoke(messages)
    except Exception as e:
        if _is_multimodal_error(e) and multimodal_model_name:
            ai_message = model.invoke(_describe_multimodal(messages, multimodal_model_name))
        else:
            raise
    return _post_process(ai_message)


async def achat(
    messages,
    model_name: str,
    openai_api_base: str,
    openai_api_key: str,
    multimodal_model_name: str | None = None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: list | None = None,
    enable_thinking=True,
    thinking=True,
    proxy_url: str = "",
):
    """异步版本的chat函数,支持协程调用"""
    model = get_llm(
        model_name=model_name,
        openai_api_base=openai_api_base,
        openai_api_key=openai_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        tools=tools,
        enable_thinking=enable_thinking,
        thinking=thinking,
        proxy_url=proxy_url,
    )
    try:
        ai_message = await model.ainvoke(messages)
    except Exception as e:
        if _is_multimodal_error(e) and multimodal_model_name:
            ai_message = await model.ainvoke(_describe_multimodal(messages, multimodal_model_name))
        else:
            raise
    return _post_process(ai_message)
