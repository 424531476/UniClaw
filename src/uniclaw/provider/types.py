"""LLM 共享数据类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Provider(StrEnum):
    """LLM 提供商。"""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Effort(StrEnum):
    """推理努力级别 (OpenRouter)。"""

    XHIGH = "xhigh"
    HIGH = "high"
    MEDIUM = "medium"
    MINIMAL = "minimal"
    LOW = "low"
    NONE = "none"


@dataclass
class UsageMeta:
    """Token 用量。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self):
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "UsageMeta":
        return cls(
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
        )


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
