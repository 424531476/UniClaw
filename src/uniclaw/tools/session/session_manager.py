from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from uniclaw.context import Scope, get_app_dir
from uniclaw.tools.session.session import Session

if TYPE_CHECKING:
    from uniclaw.agent import AgentTask


class SessionManager:
    @staticmethod
    def _default_dir() -> Path:
        return get_app_dir(Scope.USER) / "sessions"

    @classmethod
    def metadata_file(cls) -> Path:
        return cls._default_dir() / "metadata.json"

    @classmethod
    def load_session(cls, session_id: str) -> Session | None:
        """加载会话,返回 Session 对象。"""
        meta = cls._load_metadata().get(session_id)
        if not meta:
            return None
        path = Path(meta.get("file_path", ""))
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Session.from_data(data)
        except (OSError, json.JSONDecodeError):
            return None

    @classmethod
    def list_sessions(cls, limit: int = 0, cwd: str | None = None) -> list[dict]:
        items = list(cls._load_metadata().values())
        if cwd:
            items = [item for item in items if item.get("cwd") == cwd]
        items.sort(
            key=lambda item: item.get("end_time") or item.get("start_time") or "",
            reverse=True,
        )
        if limit > 0:
            return items[:limit]
        return items

    @classmethod
    def delete_session(cls, session_id: str) -> bool:
        metadata = cls._load_metadata()
        meta = metadata.pop(session_id, None)
        if not meta:
            return False
        path = Path(meta.get("file_path", ""))
        try:
            if path.exists():
                path.unlink()
            cls._save_metadata(metadata)
            return True
        except OSError:
            return False

    @classmethod
    def search_sessions(cls, keyword: str) -> list:
        pattern = re.compile(keyword, re.IGNORECASE)
        results = []
        for meta in cls.list_sessions(limit=0):
            session = cls.load_session(meta["session_id"])
            if not session:
                continue
            matches: list[int] = []
            for idx, msg in enumerate(session.to_messages(), 1):
                text = json.dumps(msg, ensure_ascii=False, default=str)
                if pattern.search(text):
                    matches.append(idx)
            if matches:
                item = dict(meta)
                item["matches"] = matches
                results.append(item)
        return results

    @classmethod
    def update_title(cls, session_id: str, title: str) -> bool:
        meta = cls._load_metadata().get(session_id)
        if not meta:
            return False
        path = Path(meta.get("file_path", ""))
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        data["title"] = title
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        meta["title"] = title
        metadata = cls._load_metadata()
        metadata[session_id] = meta
        cls._save_metadata(metadata)
        return True

    @classmethod
    async def fork_session(cls, session_id: str, message_idx: int, config: dict) -> Session | None:
        """从指定会话的消息处分叉,创建新会话。

        Args:
            session_id: 原会话 ID
            message_idx: 分叉点消息索引(0-based),包含该消息及之前的消息
            config: 配置字典

        Returns:
            新会话 Session,失败返回 None
        """
        meta = cls._load_metadata().get(session_id)
        if not meta:
            return None
        path = Path(meta.get("file_path", ""))
        if not path.exists():
            return None
        try:
            original = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        messages = original.get("messages", [])
        if message_idx < 0 or message_idx >= len(messages):
            return None

        title = (original.get("title") or "") + "分叉"

        cwd_str = original.get("cwd", "")
        if not cwd_str:
            raise ValueError(f"会话 {session_id} 的 cwd 为空，无法分叉")
        forked = Session(title=title, cwd=Path(cwd_str))
        for msg in messages[: message_idx + 1]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            extra = {k: v for k, v in msg.items() if k not in ("role", "content")}
            forked.add_message(role, content, **extra)

        data = await forked.to_dict(config)
        if data is None:
            return None
        data["metadata"] = original.get("metadata", {})

        task_dir = cls._default_dir()
        task_dir.mkdir(parents=True, exist_ok=True)
        file_path = task_dir / f"{forked.id}.json"
        file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        cls._upsert_metadata(data, file_path)
        return forked

    @classmethod
    async def save_session(cls, task: AgentTask, config: dict) -> str:
        data = await task.to_dict(config)
        if data is None:
            return ""
        metadata = cls._load_metadata()
        existing_meta = metadata.get(task.id, None)
        if existing_meta:
            file_path = Path(existing_meta["file_path"])
        else:
            file_path = cls._default_dir() / f"{task.id}.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        cls._upsert_metadata(data, file_path)
        return str(file_path)

    @classmethod
    def _load_metadata(cls) -> dict:
        if not cls.metadata_file().exists():
            return {}
        try:
            return json.loads(cls.metadata_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @classmethod
    def _save_metadata(cls, metadata: dict):
        cls.metadata_file().parent.mkdir(parents=True, exist_ok=True)
        cls.metadata_file().write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def _upsert_metadata(cls, data: dict, file_path: Path):
        metadata = cls._load_metadata()
        metadata[data["session_id"]] = {
            "session_id": data["session_id"],
            "title": data.get("title"),
            "start_time": data.get("start_time"),
            "end_time": data.get("end_time"),
            "message_count": data.get("message_count", 0),
            "cwd": data.get("cwd", ""),
            "file_path": str(file_path.resolve()),
        }
        cls._save_metadata(metadata)
