"""LLM 共享数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Protocol(StrEnum):
    """LLM API 协议类型。"""

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
class Usage:
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
    def from_dict(cls, data: dict[str, int]) -> "Usage":
        return cls(
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
        )
