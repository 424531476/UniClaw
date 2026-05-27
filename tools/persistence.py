import json
import re
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
from context import Scope, get_app_dir
from llm import chat, achat
from utils.logger import get_logger
from utils.usage import TOTAL, UsageField, get_stats
from utils.format import format_conversation_history
from console.ui import err, info, ok, warn

if TYPE_CHECKING:
    from agent import AgentTask
logger = get_logger("persistence")


def print_conversation_history(messages):
    """打印对话历史内容到屏幕

    Args:
        messages: 消息列表,每个消息包含role和content字段
    """
    if not messages:
        return

    lines = format_conversation_history(messages)
    if not lines:
        return

    # 打印头部
    info(f"\n{lines[0]}")

    # 打印消息内容，根据行内容确定颜色
    for line in lines[1:-1]:
        if "USER:" in line:
            info(line)
        elif "ASSISTANT:" in line or "TOOL_" in line:
            ok(line)
        else:
            info(line)

    # 打印尾部
    info(f"{lines[-1]}\n")


def _json_safe(value: Any) -> Any:
    """
    将任意值转换为JSON可序列化的安全副本。

    该函数递归地处理各种数据类型,确保返回值可以被json.dumps()序列化。
    对于已可序列化的值，返回其深拷贝；对于不可序列化的对象，尝试转换为其字典表示或字符串形式。

    Args:
        value: 需要转换的任意类型值，可以是基本类型、容器类型或自定义对象

    Returns:
        JSON可序列化的值:
        - 如果原值已可序列化，返回其深拷贝
        - 字典：键转换为字符串，值递归处理
        - 列表/元组/集合：转换为列表，元素递归处理
        - 具有model_dump方法的对象(如Pydantic模型):转换为JSON模式的字典
        - 具有dict方法的对象:转换为字典
        - 其他不可序列化对象：转换为字符串

    Examples:
        >>> _json_safe({"key": "value"})  # 返回深拷贝的字典
        >>> _json_safe([1, 2, 3])  # 返回列表
        >>> _json_safe(datetime.now())  # 返回字符串表示
    """
    # 首先尝试直接序列化，如果成功则返回深拷贝以保持原始结构
    try:
        json.dumps(value, ensure_ascii=False)
        return deepcopy(value)
    except TypeError:
        pass

    # 处理字典类型：将键转换为字符串，递归处理所有值
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}

    # 处理序列类型（列表、元组、集合）：统一转换为列表并递归处理元素
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]

    # 处理Pydantic V2模型：使用model_dump方法获取JSON兼容的字典
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))

    # 处理Pydantic V1或其他具有dict方法的对象
    if hasattr(value, "dict"):
        return _json_safe(value.dict())

    # 兜底策略：将所有其他类型转换为字符串
    return str(value)


def _message_text(value: Any, *, max_chars: int = 1200) -> str:
    if isinstance(value, str):
        return value[:max_chars]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif item.get("type") in {"image_url", "input_audio", "video_url"}:
                parts.append(f"[{item.get('type')}]")
        return "\n".join(parts)[:max_chars]
    return str(value)[:max_chars]


def message2str(messages: list[dict]):
    lines = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role", "?")
        content = message.get("content", "")
        lines.append(f"[{role.upper()}]: {content}")
    return "\n".join(lines)


class ConversationPersistence:
    """File-system backed conversation persistence."""

    def __init__(self):
        self.storage_dir = self._default_dir()
        self.metadata_file = self.storage_dir / "metadata.json"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _default_dir() -> Path:
        return get_app_dir(Scope.USER) / "conversations"

    async def save_conversation(self, task: AgentTask, config: dict) -> str:
        if not task.messages:
            return ""

        now = datetime.now()
        session_id = getattr(task, "conversation_session_id", None)
        started_at = getattr(task, "conversation_start_time", None)
        if not session_id:
            started_at = now
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            session_id = f"{timestamp}_{uuid.uuid4()}"
            setattr(task, "conversation_session_id", session_id)
            setattr(task, "conversation_start_time", started_at)

        metadata = self._load_metadata()
        existing_meta = metadata.get(session_id, {})
        if existing_meta.get("file_path"):
            file_path = Path(existing_meta["file_path"])
            file_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            task_dir = self.storage_dir / task.id
            task_dir.mkdir(parents=True, exist_ok=True)
            file_name = f"{session_id}.json"
            file_path = task_dir / file_name

        existing = self.load_conversation(session_id) if file_path.exists() else {}
        title = existing.get("title") if isinstance(existing, dict) else None
        if not title:
            title = await self.generate_title(task.messages, config)

        stats = get_stats()
        total = stats.get(TOTAL, {})
        if isinstance(started_at, str):
            try:
                started_at_dt = datetime.fromisoformat(started_at)
            except ValueError:
                started_at_dt = now
        else:
            started_at_dt = started_at if hasattr(started_at, "isoformat") else now
        start_iso = started_at_dt.strftime("%Y-%m-%d %H:%M:%S")
        duration = max(0, int((now - started_at_dt).total_seconds()))
        data = {
            "session_id": session_id,
            "task_id": task.id,
            "task_name": task.name,
            "title": title,
            "start_time": start_iso,
            "end_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": duration,
            "message_count": len(task.messages),
            "total_input_tokens": total.get(UsageField.INPUT_TOKENS, 0),
            "total_output_tokens": total.get(UsageField.OUTPUT_TOKENS, 0),
            "api_calls": total.get(UsageField.API_CALLS, 0),
            "messages": _json_safe(task.messages),
            "metadata": {
                "worktree_path": task.worktree_path,
                "worktree_branch": task.worktree_branch,
                "permission_mode": config.get("permission_mode"),
                "verbose": config.get("verbose", False),
                "cwd": config.get("cwd"),
            },
        }

        file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._upsert_metadata(data, file_path)
        return str(file_path)

    async def generate_title(self, messages: list, config: dict) -> str:
        snippets: list[str] = []
        for msg in messages[-12:]:
            role = msg.get("role", "unknown")
            if role == "tool":
                continue
            text = _message_text(msg.get("content", ""))
            if text.strip():
                snippets.append(f"{role}: {text.strip()}")
        if not snippets:
            return ""

        prompt = "\n\n".join(snippets)[-6000:]
        title_messages = [
            {
                "role": "system",
                "content": "你为对话生成标题。只输出一个简洁标题,不要解释,不要引号,10个中文字符以内。",
            },
            {"role": "user", "content": prompt},
        ]
        try:
            resp = await achat(
                title_messages,
                config.get("mini_model_name") or config.get("model_name"),
                enable_thinking=False,
                thinking=False,
            )
            title = getattr(resp, "content", str(resp)).strip()
        except Exception as exc:
            logger.warning("generate title failed: %s", exc)
            title = self._fallback_title(messages)
        return title.strip().strip('"').strip("'")[:10]

    def _fallback_title(self, messages: list) -> str:
        for msg in messages:
            if msg.get("role") == "user":
                text = re.sub(
                    r"\s+", " ", _message_text(msg.get("content", ""))
                ).strip()
                if text:
                    return text[:30]
        return ""

    def load_conversation(self, session_id: str) -> Optional[dict]:
        meta = self._load_metadata().get(session_id)
        if not meta:
            return None
        path = Path(meta.get("file_path", ""))
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def list_conversations(self, limit: int = 20) -> list:
        items = list(self._load_metadata().values())
        items.sort(
            key=lambda item: item.get("end_time") or item.get("start_time") or "",
            reverse=True,
        )
        return items[:limit]

    def delete_conversation(self, session_id: str) -> bool:
        metadata = self._load_metadata()
        meta = metadata.pop(session_id, None)
        if not meta:
            return False
        path = Path(meta.get("file_path", ""))
        try:
            if path.exists():
                path.unlink()
            self._save_metadata(metadata)
            return True
        except OSError:
            return False

    def search_conversations(self, keyword: str) -> list:
        pattern = re.compile(keyword, re.IGNORECASE)
        results = []
        for meta in self.list_conversations(limit=10000):
            data = self.load_conversation(meta["session_id"])
            if not data:
                continue
            matches: list[int] = []
            for idx, msg in enumerate(data.get("messages", []), 1):
                text = json.dumps(msg, ensure_ascii=False, default=str)
                if pattern.search(text):
                    matches.append(idx)
            if matches:
                item = dict(meta)
                item["matches"] = matches
                results.append(item)
        return results

    def update_title(self, session_id: str, title: str) -> bool:
        data = self.load_conversation(session_id)
        if not data:
            return False
        data["title"] = title
        meta = self._load_metadata().get(session_id)
        if not meta:
            return False
        path = Path(meta["file_path"])
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        meta["title"] = title
        metadata = self._load_metadata()
        metadata[session_id] = meta
        self._save_metadata(metadata)
        return True

    def _load_metadata(self) -> dict:
        if not self.metadata_file.exists():
            return {}
        try:
            return json.loads(self.metadata_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_metadata(self, metadata: dict):
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_file.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _upsert_metadata(self, data: dict, file_path: Path):
        metadata = self._load_metadata()
        metadata[data["session_id"]] = {
            "session_id": data["session_id"],
            "task_id": data["task_id"],
            "task_name": data["task_name"],
            "title": data.get("title"),
            "start_time": data.get("start_time"),
            "end_time": data.get("end_time"),
            "message_count": data.get("message_count", 0),
            "model_name": data.get("model_name", ""),
            "file_path": str(file_path.resolve()),
        }
        self._save_metadata(metadata)
