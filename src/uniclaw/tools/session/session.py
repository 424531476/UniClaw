from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING
import uuid
from uniclaw.utils.message import MessageRole
from uniclaw.utils.tokens import get_encoder, count_tokens
from uniclaw.provider.types import Usage

if TYPE_CHECKING:
    from uniclaw.config import AppConfig


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

    def to_openai_message(self) -> dict[str, Any]:
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

    def to_anthropic_message(self) -> dict[str, Any]:
        if self.type == MultimodalType.text:
            return {"type": "text", "text": self.text or ""}
        if self.type == MultimodalType.image_url:
            url = self.image_url.get("url", "") if self.image_url else ""
            if url.startswith("data:"):
                parts = url.split(",", 1)
                media_type = parts[0].split(":")[1].split(";")[0]
                source = {
                    "type": "base64",
                    "media_type": media_type,
                    "data": parts[1] if len(parts) > 1 else "",
                }
            else:
                source = {"type": "url", "url": url}
            return {"type": "image", "source": source}
        # Anthropic 不原生支持 audio/video,降级为文本占位
        if self.type == MultimodalType.input_audio:
            return {"type": "text", "text": "[audio]"}
        if self.type == MultimodalType.video_url:
            return {"type": "text", "text": "[video]"}
        raise ValueError(f"Unsupported multimodal block type: {self.type}")

    def to_dict(self) -> dict[str, Any]:
        return self.to_openai_message()

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

    content: SupportedContent = ""

    @property
    def role(self) -> str:
        raise NotImplementedError

    def to_openai_message(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_anthropic_message(self) -> dict[str, Any]:
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
            total += count_tokens(content, model)
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
                        total += count_tokens(text, model)
        msg = self.to_openai_message()
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

    def to_openai_message(self) -> dict[str, Any]:

        if isinstance(self.content, list):
            content = [block.to_openai_message() for block in self.content]
        else:
            content = self.content
        return {
            "role": MessageRole.USER,
            "content": content,
        }

    def to_anthropic_message(self) -> dict[str, Any]:
        if isinstance(self.content, list):
            content = [block.to_anthropic_message() for block in self.content]
        else:
            content = self.content
        return {
            "role": MessageRole.USER,
            "content": content,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_openai_message()

    def to_str(self) -> str:
        return f"[user]:{self.to_content()}"

    def to_content(self) -> str:
        if isinstance(self.content, list):
            return "\n".join([block.to_str() for block in self.content])
        else:
            return self.content


@dataclass
class AIMessage(BaseMessage):
    model_name: str = ""
    usage: Usage | None = None
    reasoning_content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def role(self) -> str:
        return MessageRole.ASSISTANT

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AIMessage":
        content = data["content"]
        if isinstance(content, list):
            content = [MultimodalBlock.from_dict(block) for block in content]
        return cls(
            content=content,
            model_name=data.get("model_name", ""),
            usage=Usage.from_dict(data.get("usage", {})),
            reasoning_content=data.get("reasoning_content"),
            tool_calls=data.get("tool_calls"),
        )

    def to_openai_message(self) -> dict[str, Any]:
        msg = {
            "role": MessageRole.ASSISTANT,
            "content": (
                self.content.to_openai_message()
                if isinstance(self.content, list)
                else self.content
            ),
        }
        if self.reasoning_content:
            msg["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg

    def to_anthropic_message(self) -> dict[str, Any]:
        blocks = []
        if self.reasoning_content:
            blocks.append({"type": "thinking", "thinking": self.reasoning_content})
        content = self.content
        if isinstance(content, list):
            blocks.extend(b.to_anthropic_message() for b in content)
        elif content:
            blocks.append({"type": "text", "text": content})
        if self.tool_calls:
            for tc in self.tool_calls:
                func = tc.get("function", {})
                import json as _json

                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": (
                            _json.loads(func.get("arguments", "{}"))
                            if isinstance(func.get("arguments"), str)
                            else func.get("arguments", {})
                        ),
                    }
                )
        return {"role": MessageRole.ASSISTANT, "content": blocks}

    def to_dict(self) -> dict[str, Any]:
        data = self.to_openai_message()
        data["usage"] = self.usage.to_dict()
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
class StreamChunk(AIMessage):
    """流式 chunk,支持 += 累积。"""

    new_tool_call_name: str = ""
    new_tool_call_args: dict = field(default_factory=dict)

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
class ToolCallMessage(BaseMessage):
    name: str = ""
    tool_call_id: str = ""
    args: dict[str, Any] = field(default_factory=dict)

    @property
    def role(self) -> str:
        return MessageRole.TOOL

    def to_openai_message(self) -> dict[str, Any]:
        return {
            "role": MessageRole.TOOL,
            "name": self.name,
            "content": self.content,
            "tool_call_id": self.tool_call_id,
        }

    def to_anthropic_message(self) -> dict[str, Any]:
        return {
            "role": MessageRole.USER,
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": self.tool_call_id,
                    "content": self.content,
                }
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.to_openai_message()
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


# 结构化 checkpoint 模板 — 替代自由文本摘要
CHECKPOINT_TEMPLATE = """请将以下对话历史整理为结构化摘要,严格按以下格式输出：

## 当前意图
{用户最终想完成什么}

## 下一步动作
{agent 正在做什么,做到哪一步了}

## 涉及文件
{文件路径 + 做了什么修改/操作}

## 已完成
{已完成的子任务,简要列出}

## 待完成
{未完成的子任务}

## 关键决策
{做出的设计决策及原因}

## 错误与修复
{遇到的问题、原因、解决方案}

注意：
- 每个 section 如果没有对应内容就写"无"
- 文件路径、URL、端口号、变量名、命令等关键信息必须完整保留,一字不改
- 错误信息和堆栈可以精简但不能省略关键行
- 保持简洁,总长度控制在 800 字以内"""


@dataclass
class Session:
    root_dir: Path | None = None
    id: str = ""
    start_time: datetime = field(default_factory=datetime.now)
    title: str | None = None
    _messages: list[UserMessage | AIMessage | ToolCallMessage] = field(
        default_factory=list
    )
    dedup_cache: set = field(default_factory=set, repr=False)  # 只读工具结果去重缓存
    from uniclaw.tools.fs import Glob, Read
    from uniclaw.tools.search import platform_search
    from uniclaw.tools.shell import Grep
    from uniclaw.tools.web import webFetch, webSearch

    # 只读工具去重集合
    _DEDUP_TOOLS = frozenset(
        {
            Read.name,
            Glob.name,
            Grep.name,
            webFetch.name,
            webSearch.name,
            platform_search.name,
        }
    )
    _DEDUP_MIN_CHARS = 500

    # 可再生工具 — 结果可以重新执行获取,压缩时直接清空
    COMPACTABLE_TOOLS = frozenset(
        {
            Read.name,
            Grep.name,
            Glob.name,
            webFetch.name,
            webSearch.name,
        }
    )

    def __post_init__(self) -> None:
        if not self.id:
            now = datetime.now()
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            self.id = f"{timestamp}_{uuid.uuid4().hex[:12]}"
            self.start_time = now

    def check_dedup(self, tool_name: str, args: dict, result: str | list) -> str | None:
        """检查只读工具结果是否重复。重复时返回去重提示,否则返回 None。"""
        if (
            tool_name not in self._DEDUP_TOOLS
            or not isinstance(result, str)
            or len(result) <= self._DEDUP_MIN_CHARS
        ):
            return None
        try:
            args_key = json.dumps(args, sort_keys=True, ensure_ascii=False)
            dedup_key = hash(tool_name + args_key + result)
            if dedup_key in self.dedup_cache:
                from uniclaw.utils.format import format_args_for_display

                args_short = format_args_for_display(args, max_length=200)
                return (
                    f"[deduped] {tool_name}({args_short}) "
                    f"的结果与之前调用完全相同,已省略。"
                )
            self.dedup_cache.add(dedup_key)
        except (TypeError, ValueError):
            pass
        return None

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
                    usage=message.get("usage", {}),
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

    def to_openai_messages(self) -> list[dict[str, str | list[dict[str, Any]]]]:
        messages = []
        for message in self._messages:
            messages.append(message.to_openai_message())
        return messages

    def to_anthropic_messages(self) -> list[dict[str, str | list[dict[str, Any]]]]:
        messages = []
        for message in self._messages:
            messages.append(message.to_anthropic_message())
        return messages

    def get_recent_text(self, max_chars: int = 8000) -> str:
        """提取最近的对话文本(从后往前截取),用于 judge 评估等场景。"""
        parts: list[str] = []
        total = 0
        for message in reversed(self._messages):
            text = message.to_str()
            if not text:
                continue
            if total + len(text) > max_chars:
                # 截取剩余空间
                remaining = max_chars - total
                if remaining > 0:
                    parts.append(text[-remaining:])
                break
            parts.append(text)
            total += len(text)
        parts.reverse()
        return "\n\n".join(parts)

    async def to_dict(self, config: AppConfig) -> dict | None:
        if len(self._messages) == 0:
            return None
        if self.title is None or not self.title.strip():
            self.title = await self.generate_title(config=config)
        now = datetime.now()
        duration = max(0, int((now - self.start_time).total_seconds()))
        total_input_tokens = sum(
            [
                message.usage.input_tokens
                for message in self._messages
                if isinstance(message, AIMessage)
            ]
        )
        total_output_tokens = sum(
            [
                message.usage.output_tokens
                for message in self._messages
                if isinstance(message, AIMessage)
            ]
        )
        api_calls = sum(
            1 for message in self._messages if isinstance(message, AIMessage)
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
        usage: dict[str, Any],
        reasoning_content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        assistant_message = AIMessage(
            content=content,
            model_name=model_name,
            usage=Usage.from_dict(usage),
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
        system_prompt = (
            "你为对话生成标题。只输出一个简洁标题,不要解释,不要引号,10个中文字符以内。"
        )
        title_session = Session()
        title_session.add_user_message(content=prompt)

        try:
            from uniclaw.provider import achat

            resp = await achat(
                system_prompt,
                title_session,
                model_name=config.mini_model_name,
                enable_thinking=False,
                thinking=False,
                config=config,
            )
            title = resp.content.strip()
        except Exception:
            title = self._fallback_title()

        return title

    def _fallback_title(self) -> str:
        for message in self._messages:
            if isinstance(message, UserMessage):
                content = message.to_content()
                return content[:20]
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
                usage=kwargs.get("usage", {}),
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
        self.dedup_cache.clear()

    def replace_messages(self, messages: list[dict[str, Any]]) -> None:
        """用原始 dict 列表整体替换消息。"""
        self._messages.clear()
        self.dedup_cache.clear()
        for msg in messages:
            role = msg.get("role", "")
            if role == MessageRole.USER:
                self.add_user_message(content=msg.get("content", ""))
            elif role == MessageRole.ASSISTANT:
                self.add_assistant_message(
                    content=msg.get("content", ""),
                    model_name=msg.get("model_name", ""),
                    usage=msg.get("usage", {}),
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

    async def compact(
        self, config: AppConfig, focus: str = "", keep_ratio: float = 0.3
    ) -> None:
        """通过 LLM 将旧消息压缩为结构化摘要。"""
        split = self._find_split_point(keep_ratio=keep_ratio)
        if split <= 0:
            return

        old = self._messages[:split]
        recent = self._messages[split:]

        # 构建旧消息文本
        old_text = ""
        for m in old:
            if isinstance(m, UserMessage):
                role = MessageRole.USER
            elif isinstance(m, AIMessage):
                role = MessageRole.ASSISTANT
            else:
                role = MessageRole.TOOL
            content = m.to_content()
            old_text += f"[{role}]: {content}\n"

        summary_prompt = CHECKPOINT_TEMPLATE
        if focus:
            summary_prompt += f"\n\n特别关注:{focus}"
        summary_prompt += "\n\n" + old_text

        wait_id = config.spinner.start("压缩对话...")
        try:
            from uniclaw.provider import achat

            compact_session = Session()
            compact_session.add_user_message(content=summary_prompt)
            resp = await achat(
                "你是一个简洁的摘要生成器。",
                compact_session,
                config=config,
            )
        finally:
            config.spinner.stop(wait_id=wait_id)

        self._messages.clear()
        self.dedup_cache.clear()
        self.add_user_message(content=f"[之前的对话摘要]\n{resp.content}")
        self.add_assistant_message(
            content="明白了。我已经了解了之前对话的上下文。让我们继续。",
            model_name="",
            usage={},
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
        """压缩旧工具结果：可再生工具清空,不可再生工具截断。"""
        cutoff = max(0, len(self._messages) - preserve_last_n_turns)
        for i in range(cutoff):
            msg = self._messages[i]
            if not isinstance(msg, ToolCallMessage):
                continue
            content = msg.content if isinstance(msg.content, str) else ""
            if not content or len(content) <= 200:
                continue
            if msg.name in self.COMPACTABLE_TOOLS:
                # 可再生工具：清空结果,保留工具名和参数信息
                msg.content = f"[{msg.name} 结果已清除,可重新执行获取]"
            elif len(content) > max_chars:
                # 不可再生工具：截断(保留头尾)
                half = max_chars // 2
                quarter = max_chars // 4
                snipped = len(content) - half - quarter
                msg.content = f"{content[:half]}\n[... {snipped} 个字符已省略 ...]\n{content[-quarter:]}"
        self.dedup_cache.clear()

    async def maybe_compact(self, config: AppConfig) -> bool:
        """根据上下文长度阈值判断是否需要执行消息压缩。

        三级压缩策略:
        - level 0 (50%): 仅微压缩(清空旧工具结果)
        - level 1 (70%): 微压缩 + LLM 结构化摘要
        - level 2 (85%): 微压缩 + 更激进的 LLM 摘要
        """
        from uniclaw.compaction import get_context_limit, get_pressure_level

        model = config.model_name
        limit = get_context_limit(model)
        current_tokens = self.estimate_tokens(model)
        level = get_pressure_level(current_tokens, model)

        if level < 0:
            return False

        # level 0+: 微压缩 — 清空可再生工具结果
        self.snip_old_tool_results()
        if self.estimate_tokens(model) <= limit * 0.50:
            return True

        # level 1+: LLM 结构化摘要 (keep_ratio=0.3)
        await self.compact(config, keep_ratio=0.3)
        if self.estimate_tokens(model) <= limit * 0.70:
            return True

        # level 2: 更激进的摘要 (keep_ratio=0.15)
        await self.compact(config, keep_ratio=0.15)
        return True

    def build_context_summary(
        self,
        max_messages: int = 0,
        max_chars: int = 0,
        roles: tuple = (MessageRole.USER, MessageRole.ASSISTANT),
    ) -> str:
        """从对话消息中提取最近消息作为上下文摘要。"""
        role_map = {
            UserMessage: MessageRole.USER,
            AIMessage: MessageRole.ASSISTANT,
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
            if isinstance(message, AIMessage) and message.content
        ]
        if separator is None:
            return parts
        return separator.join(parts)
