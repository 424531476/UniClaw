from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TodoStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class TodoItem:
    id: int
    content: str
    status: TodoStatus = TodoStatus.PENDING


class TodoList:
    """单例 todolist,仅在内存中维护"""

    _instance: TodoList | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.items = []
        return cls._instance

    @classmethod
    def get_instance(cls) -> TodoList:
        return cls()

    def is_empty(self) -> bool:
        return len(self.items) == 0

    def add(self, content: str) -> TodoItem:
        item = TodoItem(id=len(self.items), content=content)
        self.items.append(item)
        return item

    def update_status(self, index: int, status: TodoStatus | str) -> str:
        if index < 0 or index >= len(self.items):
            return f"错误:索引 {index} 超出范围,当前共 {len(self.items)} 项"

        status = TodoStatus(status)
        old_status = self.items[index].status
        self.items[index].status = status

        # 同一时间只允许一个 in_progress
        if status == TodoStatus.IN_PROGRESS:
            for i, item in enumerate(self.items):
                if i != index and item.status == TodoStatus.IN_PROGRESS:
                    item.status = TodoStatus.PENDING

        # 完成时自动推进下一个 pending 项为 in_progress
        if status == TodoStatus.COMPLETED and old_status != TodoStatus.COMPLETED:
            for item in self.items:
                if item.status == TodoStatus.PENDING:
                    item.status = TodoStatus.IN_PROGRESS
                    break

        return self.get_list()

    def clear(self):
        self.items.clear()

    def get_list(self) -> str:
        """返回 todolist 条目列表,用于工具返回值和 TUI 显示"""
        if not self.items:
            return ""
        lines = []
        for item in self.items:
            if item.status == TodoStatus.IN_PROGRESS:
                marker = "[*]"
            elif item.status == TodoStatus.COMPLETED:
                marker = "[✓]"
            else:
                marker = "[ ]"
            lines.append(f"- {marker} {item.content} ({item.status})")
        return "\n".join(lines)

    def get_brief(self) -> str:
        """返回简短进度,如 '2/5'"""
        total = len(self.items)
        done = sum(1 for i in self.items if i.status == TodoStatus.COMPLETED)
        return f"{done}/{total}"

    def get_incomplete(self) -> list[str]:
        """返回未完成的任务列表,每项包含任务内容和状态"""
        return [
            f"{item.content} ({item.status})"
            for item in self.items
            if item.status != TodoStatus.COMPLETED
        ]
