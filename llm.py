from typing import Optional
import httpx
from langchain_openai import ChatOpenAI
from tools import tools
from config import get_config


def _create_http_client():
    """创建带代理的 HTTP 客户端"""
    proxy_url = get_config().proxy_url
    if isinstance(proxy_url, str) and proxy_url.startswith("http"):
        return httpx.Client(proxy=proxy_url)
    return None


def stream(
    messages,
    model_name=None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: Optional[list] = None,
):
    if not model_name:
        model_name = get_config().model_name
    model = ChatOpenAI(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stream_usage=True,
        request_timeout=60 * 10,
        http_client=_create_http_client(),
    )
    if tools:
        model = model.bind_tools(tools)
    for chunk in model.stream(messages):
        yield chunk


def chat(
    messages,
    model_name=None,
    temperature=0.7,
    max_tokens=5000,
    top_p=0.9,
    tools: Optional[list] = None,
):
    if not model_name:
        model_name = get_config().model_name
    model = ChatOpenAI(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stream_usage=True,
        request_timeout=60 * 10,
        http_client=_create_http_client(),
    )
    if tools:
        model = model.bind_tools(tools)
    return model.invoke(messages)
