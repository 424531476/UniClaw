"""LLM 调用层 — 多提供商支持 (OpenAI / Anthropic)。"""

from uniclaw.provider.common import compare_urls
from uniclaw.provider.router import achat, astream, chat, stream
from uniclaw.provider.thought_parser import ThoughtParser
from uniclaw.provider.types import AIMessage, Effort, Provider, StreamChunk, UsageMeta

__all__ = [
    # 数据类型
    "UsageMeta",
    "StreamChunk",
    "AIMessage",
    "Effort",
    "Provider",
    # 核心 API (路由器 — 自动选择提供商)
    "stream",
    "astream",
    "chat",
    "achat",
    # 工具
    "ThoughtParser",
    "compare_urls",
]
