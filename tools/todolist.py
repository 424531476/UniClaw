from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from langchain_core.tools import tool


@dataclass
class TodoItem:
    id: int
    content: str
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TodoList:
    """单例 todolist，仅在内存中维护"""

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

    def update_status(self, index: int, status: str) -> str:
        if index < 0 or index >= len(self.items):
            return f"错误：索引 {index} 超出范围，当前共 {len(self.items)} 项"

        old_status = self.items[index].status
        self.items[index].status = status

        # 同一时间只允许一个 in_progress
        if status == "in_progress":
            for i, item in enumerate(self.items):
                if i != index and item.status == "in_progress":
                    item.status = "pending"

        # 完成时自动推进下一个 pending 项为 in_progress
        if status == "completed" and old_status != "completed":
            for item in self.items:
                if item.status == "pending":
                    item.status = "in_progress"
                    break

        return self.get_list()

    def clear(self):
        self.items.clear()

    def get_list(self) -> str:
        """返回 todolist 条目列表，用于工具返回值和 TUI 显示"""
        if not self.items:
            return ""
        lines = []
        for item in self.items:
            if item.status == "in_progress":
                marker = "[*]"
            elif item.status == "completed":
                marker = "[✓]"
            else:
                marker = "[ ]"
            lines.append(f"- {marker} {item.content} ({item.status})")
        return "\n".join(lines)

    def get_system_prompt(self) -> str:
        """返回含督促指令的完整内容，用于注入 system_prompt"""
        if not self.items:
            return "遇到复杂任务时，使用 todolist_create 将其拆解为多个步骤并逐步完成。"
        lines = ["# 当前任务进度", "你有一个未完成的任务清单，必须按照顺序逐步完成："]
        lines.append(self.get_list())
        lines.append("")
        lines.append("重要指令：")
        lines.append("- 你必须主动推进任务完成，不要等待用户催促")
        lines.append(
            f"- 每完成一步，立即调用 {todolist_update.name} 将状态更新为 completed"
        )
        lines.append("- 完成当前步骤后，自动开始下一步，不要停下来问用户")
        lines.append(f"- 全部完成后调用 {todolist_clear.name} 清空清单")
        lines.append("- 如果遇到阻塞，记录问题并继续推进其他步骤")
        return "\n".join(lines)

    def get_brief(self) -> str:
        """返回简短进度，如 '2/5'"""
        total = len(self.items)
        done = sum(1 for i in self.items if i.status == "completed")
        return f"{done}/{total}"


def get_list_system_prompt() -> str:
    """返回 todolist 内容用于注入 system_prompt，为空时返回空字符串"""
    return TodoList.get_instance().get_system_prompt()


@tool
def todolist_create(items: list[str]) -> str:
    """
    创建一个新的任务清单（todolist），替换现有内容。
    用于将复杂任务分解为多个步骤进行跟踪。第一个步骤自动标记为正在进行。

    Args:
        items: 任务步骤列表，每个元素是一个步骤的描述
    """
    todo = TodoList.get_instance()
    todo.clear()
    for content in items:
        todo.add(content)
    if todo.items:
        todo.items[0].status = "in_progress"
    return f"已创建任务清单，共 {len(todo.items)} 个步骤：\n{todo.get_list()}"


@tool
def todolist_update(index: int, status: str) -> str:
    """
    更新任务清单中指定步骤的状态。

    Args:
        index: 步骤的索引（从 0 开始）
        status: 新状态，可选值为 "pending"（未完成）、"in_progress"（正在进行）、"completed"（已完成）
    """
    if status not in ("pending", "in_progress", "completed"):
        return f"错误：无效状态 '{status}'，可选值为 pending、in_progress、completed"
    todo = TodoList.get_instance()
    if todo.is_empty():
        return "错误：当前没有任务清单，请先使用 todolist_create 创建"
    result = todo.update_status(index, status)
    return f"已更新步骤 {index} 状态为 {status}：\n{result}"


@tool
def todolist_clear() -> str:
    """清空当前任务清单。当所有步骤完成后调用此工具。"""
    todo = TodoList.get_instance()
    count = len(todo.items)
    todo.clear()
    return f"已清空任务清单（共 {count} 个步骤）"


@tool
def todolist_list() -> str:
    """列出当前任务清单的所有步骤及状态。"""
    todo = TodoList.get_instance()
    if todo.is_empty():
        return "当前没有任务清单"
    return todo.get_list()


def get_tools() -> list:
    return [todolist_create, todolist_update, todolist_clear, todolist_list]


def get_all_tools() -> list:
    """获取所有待办工具(无条件返回)"""
    return get_tools()
