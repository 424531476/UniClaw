from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TYPE_CHECKING
import uuid
from uniclaw.utils.message import MessageRole
from uniclaw.llm import achat

if TYPE_CHECKING:
    from uniclaw.config import AppConfig

# ── Token 估算工具 ─────────────────────────────────────────

_MODEL_ENCODINGS = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4.1": "o200k_base",
    "gpt-4.1-mini": "o200k_base",
    "gpt-4.1-nano": "o200k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
}
_encoder_cache: dict[str, Any] = {}


def _get_encoder(model: str = None):
    try:
        import tiktoken
    except ImportError:
        return None
    if not model:
        return tiktoken.get_encoding("cl100k_base")
    short_name = model.split("/")[-1] if "/" in model else model
    encoding_name = "cl100k_base"
    for key, enc in _MODEL_ENCODINGS.items():
        if short_name.startswith(key):
            encoding_name = enc
            break
    if encoding_name not in _encoder_cache:
        try:
            _encoder_cache[encoding_name] = tiktoken.get_encoding(encoding_name)
        except Exception:
            return None
    return _encoder_cache[encoding_name]


def _count_tokens(text: str, model: str = None) -> int:
    encoder = _get_encoder(model)
    if encoder is None:
        return int(len(text) / 2.8)
    try:
        return len(encoder.encode(text))
    except Exception:
        return int(len(text) / 2.8)


def _estimate_visual_tokens(block: dict) -> int:
    btype = block.get("type")
    url = ""
    if btype == "image_url":
        url = block.get("image_url", {}).get("url", "")
    elif btype == "video_url":
        url = block.get("video_url", {}).get("url", "")
    else:
        return 0
    try:
        import base64
        from io import BytesIO
        from PIL import Image

        if not url.startswith("data:"):
            return 85
        _, data = url.split(",", 1)
        img = Image.open(BytesIO(base64.b64decode(data)))
        w, h = img.size
        tiles = ((w + 511) // 512) * ((h + 511) // 512)
        return 85 + tiles * 170
    except Exception:
        return 500


def _estimate_audio_tokens(block: dict) -> int:
    if block.get("type") != "input_audio":
        return 0
    try:
        data = block.get("input_audio", {}).get("data", "")
        if not data:
            return 100
        audio_bytes = len(data) * 3 / 4
        duration_seconds = audio_bytes / 16000
        return max(50, int(duration_seconds * 10))
    except Exception:
        return 500


def _count_str_chars(obj) -> int:
    if isinstance(obj, str):
        return len(obj)
    if isinstance(obj, dict):
        return sum(_count_str_chars(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_str_chars(item) for item in obj)
    return 0


class MultimodalType(StrEnum):
    text = "text"
    image_url = "image_url"
    input_audio = "input_audio"
    video_url = "video_url"


@dataclass
class UsageMeta:
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
class MultimodalBlock:
    type: MultimodalType
    text: str | None = None
    image_url: dict[str, str] | None = None
    input_audio: dict[str, str] | None = None
    video_url: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MultimodalBlock":
        block_type = MultimodalType(data.get("type", "text"))
        return cls(
            type=block_type,
            text=(
                data.get(MultimodalType.text)
                if block_type == MultimodalType.text
                else None
            ),
            image_url=(
                data.get(MultimodalType.image_url)
                if block_type == MultimodalType.image_url
                else None
            ),
            input_audio=(
                data.get(MultimodalType.input_audio)
                if block_type == MultimodalType.input_audio
                else None
            ),
            video_url=(
                data.get(MultimodalType.video_url)
                if block_type == MultimodalType.video_url
                else None
            ),
        )

    def to_message(self) -> dict[str, Any]:
        if self.type == MultimodalType.text:
            return {"type": MultimodalType.text, "text": self.text or ""}
        if self.type == MultimodalType.image_url:
            return {"type": MultimodalType.image_url, "image_url": self.image_url}
        if self.type == MultimodalType.input_audio:
            return {
                "type": MultimodalType.input_audio,
                "input_audio": self.input_audio,
            }
        if self.type == MultimodalType.video_url:
            return {"type": MultimodalType.video_url, "video_url": self.video_url}
        raise ValueError(f"Unsupported multimodal block type: {self.type}")

    def to_dict(self) -> dict[str, Any]:
        return self.to_message()

    def to_str(self) -> str:
        if self.type == MultimodalType.text:
            content = self.text
        else:
            content = f"[{self.type}]"
        return content


MultimodalContent = list[MultimodalBlock]
SupportedContent = str | MultimodalContent


@dataclass
class BaseMessage:
    """消息基类提供 content 和 token 估算。"""

    content: SupportedContent

    @property
    def role(self) -> str:
        raise NotImplementedError

    def to_message(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_str(self) -> str:
        raise NotImplementedError

    def to_content(self) -> str:
        raise NotImplementedError

    def estimate_tokens(self, model: str = None) -> int:
        """估算本条消息的 token 数量。"""
        total = 0
        content = self.content
        if isinstance(content, str):
            total += _count_tokens(content, model)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, MultimodalBlock):
                    block = block.to_dict()
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "text")
                if btype in ("image_url", "video_url"):
                    total += _estimate_visual_tokens(block)
                elif btype == "input_audio":
                    total += _estimate_audio_tokens(block)
                else:
                    text = block.get("text", "")
                    if text:
                        total += _count_tokens(text, model)
        msg = self.to_message()
        for tc in msg.get("tool_calls") or []:
            total += _count_str_chars(tc)
        # 框架开销: 每条消息 4 tokens + 5% 缓冲
        return int((total + 4) * 1.05)


@dataclass
class UserMessage(BaseMessage):

    @property
    def role(self) -> str:
        return MessageRole.USER

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserMessage":
        content = data["content"]
        if isinstance(content, list):
            content = [MultimodalBlock.from_dict(block) for block in content]
        return cls(content=content)

    def to_message(self) -> dict[str, Any]:

        if isinstance(self.content, list):
            content = [block.to_message() for block in self.content]
        else:
            content = self.content
        return {
            "role": MessageRole.USER,
            "content": content,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_message()

    def to_str(self) -> str:
        return f"[user]:{self.to_content()}"

    def to_content(self) -> str:
        if isinstance(self.content, list):
            return "\n".join([block.to_str() for block in self.content])
        else:
            return self.content


@dataclass
class AssistantMessage(BaseMessage):
    model_name: str
    usage_meta: UsageMeta
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    @property
    def role(self) -> str:
        return MessageRole.ASSISTANT

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssistantMessage":
        content = data["content"]
        if isinstance(content, list):
            content = [MultimodalBlock.from_dict(block) for block in content]
        return cls(
            content=content,
            model_name=data.get("model_name", ""),
            usage_meta=UsageMeta.from_dict(data.get("usage_meta", {})),
            reasoning_content=data.get("reasoning_content"),
            tool_calls=data.get("tool_calls"),
        )

    def to_message(self) -> dict[str, Any]:
        return {
            "role": MessageRole.ASSISTANT,
            "content": (
                self.content.to_message()
                if isinstance(self.content, list)
                else self.content
            ),
            "reasoning_content": self.reasoning_content,
            "tool_calls": self.tool_calls,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.to_message()
        data["usage_meta"] = self.usage_meta.to_dict()
        data["model_name"] = self.model_name
        return data

    def to_content(self) -> str:
        if isinstance(self.content, list):
            return "\n".join([block.to_str() for block in self.content])
        else:
            return self.content

    def to_str(self) -> str:
        return f"[assistant]:{self.to_content()}"


@dataclass
class ToolCallMessage(BaseMessage):
    name: str
    tool_call_id: str
    args: dict[str, Any]

    @property
    def role(self) -> str:
        return MessageRole.TOOL

    def to_message(self) -> dict[str, Any]:
        return {
            "role": MessageRole.TOOL,
            "name": self.name,
            "content": self.content,
            "tool_call_id": self.tool_call_id,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.to_message()
        data["args"] = self.args
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallMessage":
        return cls(
            name=data.get("name", ""),
            tool_call_id=data.get("tool_call_id", ""),
            content=data.get("content", ""),
            args=data.get("args", {}),
        )

    def to_content(self) -> str:
        from uniclaw.utils.format import format_args_for_display

        args_str = (
            format_args_for_display(self.args, max_length=1000) if self.args else ""
        )
        call = f"{self.name}({args_str})"
        if isinstance(self.content, list):
            text = "\n".join([block.to_str() for block in self.content])
        else:
            text = self.content or ""
        return f"{call}\n{text}" if text else call

    def to_str(self) -> str:
        content = self.to_content()
        if not content:
            return ""
        return f"[tool]: {content}"


@dataclass
class Session:
    root_dir: Path
    id: str = ""
    start_time: datetime = field(default_factory=datetime.now)
    title: str | None = None
    _messages: list[UserMessage | AssistantMessage | ToolCallMessage] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        if not self.id:
            now = datetime.now()
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            self.id = f"{timestamp}_{uuid.uuid4().hex[:12]}"
            self.start_time = now

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "Session":
        start_time = data.get("start_time")
        if isinstance(start_time, str):
            try:
                start_time = datetime.fromisoformat(start_time)
            except ValueError:
                start_time = datetime.now()
        elif not isinstance(start_time, datetime):
            start_time = datetime.now()
        session = cls(
            id=data.get("session_id", ""),
            root_dir=Path(data.get("root_dir", "")),
            title=data.get("title", ""),
            start_time=start_time,
        )
        for message in data.get("messages", []):
            role = message.get("role")
            if role == MessageRole.USER:
                session.add_user_message(content=message.get("content", ""))
            elif role == MessageRole.ASSISTANT:
                session.add_assistant_message(
                    content=message.get("content", ""),
                    model_name=message.get("model_name", ""),
                    usage_meta=message.get("usage_meta", {}),
                    reasoning_content=message.get("reasoning_content"),
                    tool_calls=message.get("tool_calls"),
                )
            elif role == MessageRole.TOOL:
                session.add_tool_call_message(
                    content=message.get("content", ""),
                    tool_call={
                        "name": message.get("name", ""),
                        "tool_call_id": message.get("tool_call_id", ""),
                        "args": message.get("args", {}),
                    },
                )
        return session

    def to_messages(self) -> list[dict[str, str | list[dict[str, Any]]]]:
        messages = []
        for message in self._messages:
            messages.append(message.to_message())
        return messages

    async def to_dict(self, config: AppConfig) -> dict | None:
        if len(self._messages) == 0:
            return None
        if self.title is None or not self.title.strip():
            self.title = await self.generate_title(config=config)
        now = datetime.now()
        duration = max(0, int((now - self.start_time).total_seconds()))
        total_input_tokens = sum(
            [
                message.usage_meta.input_tokens
                for message in self._messages
                if isinstance(message, AssistantMessage)
            ]
        )
        total_output_tokens = sum(
            [
                message.usage_meta.output_tokens
                for message in self._messages
                if isinstance(message, AssistantMessage)
            ]
        )
        api_calls = sum(
            1 for message in self._messages if isinstance(message, AssistantMessage)
        )
        data = {
            "session_id": self.id,
            "title": self.title,
            "root_dir": str(self.root_dir),
            "start_time": self.start_time.isoformat(),
            "end_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": duration,
            "message_count": len(self._messages),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "api_calls": api_calls,
            "messages": [message.to_dict() for message in self._messages],
        }
        return data

    def to_str(self, include_tools: bool = False) -> str:
        parts = []
        for message in self._messages:
            if not include_tools and isinstance(message, ToolCallMessage):
                continue
            s = message.to_str()
            if s:
                parts.append(s)
        return "\n".join(parts)

    def add_user_message(self, content: str | list[dict[str, Any]]) -> None:
        if isinstance(content, list) and content and isinstance(content[0], dict):
            content = [MultimodalBlock.from_dict(block) for block in content]
        user_message = UserMessage(content=content)
        self._messages.append(user_message)

    def add_assistant_message(
        self,
        content: SupportedContent,
        model_name: str,
        usage_meta: dict[str, Any],
        reasoning_content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        assistant_message = AssistantMessage(
            content=content,
            model_name=model_name,
            usage_meta=UsageMeta.from_dict(usage_meta),
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
        )
        self._messages.append(assistant_message)

    def add_tool_call_message(
        self,
        content: SupportedContent,
        tool_call: dict[str, Any],
    ) -> None:
        tool_call_message = ToolCallMessage(
            name=tool_call.get("name", ""),
            tool_call_id=tool_call.get("tool_call_id", ""),
            content=content,
            args=tool_call.get("args", {}),
        )
        self._messages.append(tool_call_message)

    async def generate_title(self, config: AppConfig) -> str:
        prompt = self.to_str()
        title_messages = [
            {
                "role": MessageRole.SYSTEM,
                "content": "你为对话生成标题。只输出一个简洁标题,不要解释,不要引号,10个中文字符以内。",
            },
            {"role": MessageRole.USER, "content": prompt},
        ]

        wait_id = config.spinner.start("生成标题...")
        try:
            resp = await achat(
                title_messages,
                model_name=config.mini_model_name,
                enable_thinking=False,
                thinking=False,
                config=config,
            )
            title = resp.content.strip()
        except Exception:
            title = self._fallback_title()
        finally:
            config.spinner.stop(wait_id=wait_id)

        return title

    def _fallback_title(self) -> str:
        for message in self._messages:
            if isinstance(message, UserMessage):
                content = message.to_content()
                return content[:10]
        return ""

    # ── 消息管理兼容方法 ─────────────────────────────────────

    def add_message(
        self, role: MessageRole, content: str | list[dict[str, Any]], **kwargs
    ) -> None:
        """添加消息,内部转为结构化对象。"""
        if role == MessageRole.USER:
            self.add_user_message(content=content)
        elif role == MessageRole.ASSISTANT:
            self.add_assistant_message(
                content=content,
                model_name=kwargs.get("model_name", ""),
                usage_meta=kwargs.get("usage_meta", {}),
                reasoning_content=kwargs.get("reasoning_content"),
                tool_calls=kwargs.get("tool_calls"),
            )
        elif role == MessageRole.TOOL:
            self.add_tool_call_message(
                content=content,
                tool_call={
                    "name": kwargs.get("name", ""),
                    "tool_call_id": kwargs.get("tool_call_id", ""),
                    "args": kwargs.get("args", {}),
                },
            )
        else:
            raise ValueError(f"不支持的消息角色: {role}")

    def clear(self) -> None:
        """清空所有消息。"""
        self._messages.clear()

    def replace_messages(self, messages: list[dict[str, Any]]) -> None:
        """用原始 dict 列表整体替换消息。"""
        self._messages.clear()
        for msg in messages:
            role = msg.get("role", "")
            if role == MessageRole.USER:
                self.add_user_message(content=msg.get("content", ""))
            elif role == MessageRole.ASSISTANT:
                self.add_assistant_message(
                    content=msg.get("content", ""),
                    model_name=msg.get("model_name", ""),
                    usage_meta=msg.get("usage_meta", {}),
                    reasoning_content=msg.get("reasoning_content"),
                    tool_calls=msg.get("tool_calls"),
                )
            elif role == MessageRole.TOOL:
                self.add_tool_call_message(
                    content=msg.get("content", ""),
                    tool_call={
                        "name": msg.get("name", ""),
                        "tool_call_id": msg.get("tool_call_id", ""),
                        "args": msg.get("args", {}),
                    },
                )
            else:
                raise ValueError(f"不支持的消息角色: {role}")

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self):
        return iter(self._messages)

    def __reversed__(self):
        return reversed(self._messages)

    def __getitem__(self, key):
        return self._messages[key]

    # ── Token 估算与压缩 ────────────────────────────────────

    def estimate_tokens(self, model: str = None) -> int:
        """估算当前消息的 token 数量。"""
        if not self._messages:
            return 0
        return sum(m.estimate_tokens(model) for m in self._messages)

    async def compact(self, config: AppConfig, focus: str = "") -> None:
        """通过 LLM 将旧消息压缩为摘要。"""
        split = self._find_split_point()
        if split <= 0:
            return

        old = self._messages[:split]
        recent = self._messages[split:]

        # 构建旧消息文本
        old_text = ""
        for m in old:
            if isinstance(m, UserMessage):
                role = MessageRole.USER
            elif isinstance(m, AssistantMessage):
                role = MessageRole.ASSISTANT
            else:
                role = MessageRole.TOOL
            content = m.to_content()
            old_text += f"[{role}]: {content}\n"

        summary_prompt = "请简洁地总结以下对话历史。保留关键决策、文件路径、工具结果以及继续对话所需的上下文信息。"
        if focus:
            summary_prompt += f"\n\n特别关注:{focus}"
        summary_prompt += "\n\n" + old_text

        wait_id = config.spinner.start("压缩对话...")
        try:
            resp = await achat(
                [
                    {"role": MessageRole.SYSTEM, "content": "你是一个简洁的摘要生成器。"},
                    {"role": MessageRole.USER, "content": summary_prompt},
                ],
                config=config,
            )
        finally:
            config.spinner.stop(wait_id=wait_id)

        self._messages.clear()
        self.add_user_message(content=f"[之前的对话摘要]\n{resp.content}")
        self.add_assistant_message(
            content="明白了。我已经了解了之前对话的上下文。让我们继续。",
            model_name="",
            usage_meta={},
        )
        self._messages.extend(recent)

    def _find_split_point(self, keep_ratio: float = 0.3) -> int:
        """查找分割点使最近部分约占总 token 的 keep_ratio。"""
        if not self._messages:
            return 0
        keep_ratio = max(0.0, min(1.0, keep_ratio))
        total = self.estimate_tokens()
        target = int(total * keep_ratio)
        running = 0
        for i in range(len(self._messages) - 1, -1, -1):
            running += self._messages[i].estimate_tokens()
            if running >= target:
                return i
        return 0

    def snip_old_tool_results(
        self, max_chars: int = 2000, preserve_last_n_turns: int = 6
    ) -> None:
        """截断旧的过长工具消息直接操作内部对象不丢失结构化信息。"""
        cutoff = max(0, len(self._messages) - preserve_last_n_turns)
        for i in range(cutoff):
            msg = self._messages[i]
            if not isinstance(msg, ToolCallMessage):
                continue
            content = msg.content if isinstance(msg.content, str) else ""
            if len(content) <= max_chars:
                continue
            half = max_chars // 2
            quarter = max_chars // 4
            snipped = len(content) - half - quarter
            msg.content = f"{content[:half]}\n[... {snipped} 个字符已省略 ...]\n{content[-quarter:]}"

    def build_context_summary(
        self,
        max_messages: int = 0,
        max_chars: int = 0,
        roles: tuple = (MessageRole.USER, MessageRole.ASSISTANT),
    ) -> str:
        """从对话消息中提取最近消息作为上下文摘要。"""
        role_map = {
            UserMessage: MessageRole.USER,
            AssistantMessage: MessageRole.ASSISTANT,
        }
        filtered = [m for m in self._messages if role_map.get(type(m)) in roles]
        if max_messages > 0:
            filtered = filtered[-max_messages:]
        text = "\n".join([message.to_str() for message in filtered])
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text

    def get_assistant_messages(self, separator: str | None = "\n") -> str | list[str]:
        """提取所有助手消息内容。

        Args:
            separator: 拼接分隔符。None 返回 list,否则用分隔符拼接。
        """
        parts = [
            message.to_content()
            for message in self._messages
            if isinstance(message, AssistantMessage) and message.content
        ]
        if separator is None:
            return parts
        return separator.join(parts)
