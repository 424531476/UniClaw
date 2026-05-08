from langchain_core.tools import tool
from typing import Literal


@tool
def schedule_create(
    task_id: str,
    schedule: str,
    action: str,
    name: str = "",
) -> str:
    """
    创建定时任务。

    Args:
        task_id: 任务唯一标识，如 "check-git"、"daily-report"
        schedule: 调度格式，支持：
                  - "every Ns/m/h/d" 重复执行，如 "every 30m"、"every 1h"、"every 1d"
                  - "at YYYY-MM-DD HH:MM" 一次性执行，如 "at 2026-05-10 14:00"
        action: 执行动作，格式为 "类型: 内容"，支持：
                - "shell: <命令>" 执行 shell 命令，如 "shell: git status"
                - "agent: <消息>" 发送给 AI 处理，如 "agent: 总结今天的代码变更"
        name: 任务名称（可选，默认使用 task_id）

    Returns:
        str: 创建结果消息
    """
    from scheduler import Scheduler

    scheduler = Scheduler.get_instance()
    try:
        scheduler.add_task(task_id, name, schedule, action)
    except ValueError as e:
        return f"创建失败: {e}"

    return f"已创建定时任务: {task_id} ({schedule})"


@tool
def schedule_list() -> str:
    """
    列出所有定时任务。

    Returns:
        str: 格式化的任务列表，包含任务 ID、名称、调度、动作、状态、上次执行时间
    """
    from scheduler import Scheduler

    scheduler = Scheduler.get_instance()
    tasks = scheduler.list_tasks()
    if not tasks:
        return "暂无定时任务。"

    lines = [f"共 {len(tasks)} 个定时任务:"]
    for t in tasks:
        tid = t["id"]
        name = t.get("name", tid)
        schedule = t.get("schedule", "")
        action = t.get("action", "")
        enabled = t.get("enabled", True)
        last_run = t.get("last_run", "从未执行")

        status = "启用" if enabled else "禁用"
        lines.append(f"  [{status}] {tid}")
        lines.append(f"    名称: {name}")
        lines.append(f"    调度: {schedule}")
        lines.append(f"    动作: {action}")
        lines.append(f"    上次执行: {last_run}")
    return "\n".join(lines)


@tool
def schedule_remove(task_id: str) -> str:
    """
    删除定时任务。

    Args:
        task_id: 要删除的任务 ID

    Returns:
        str: 删除结果消息
    """
    from scheduler import Scheduler

    scheduler = Scheduler.get_instance()
    if scheduler.remove_task(task_id):
        return f"已删除定时任务: {task_id}"
    return f"任务 '{task_id}' 不存在"


@tool
def schedule_toggle(
    task_id: str,
    enabled: bool,
) -> str:
    """
    启用或禁用定时任务。

    Args:
        task_id: 任务 ID
        enabled: True 启用，False 禁用

    Returns:
        str: 操作结果消息
    """
    from scheduler import Scheduler

    scheduler = Scheduler.get_instance()
    action = "启用" if enabled else "禁用"
    if scheduler.toggle_task(task_id, enabled):
        return f"已{action}定时任务: {task_id}"
    return f"任务 '{task_id}' 不存在"


tools = [schedule_create, schedule_list, schedule_remove, schedule_toggle]
