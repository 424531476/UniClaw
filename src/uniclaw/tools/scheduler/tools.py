from langchain_core.tools import tool
from typing import Literal


@tool
def schedule_create(
    name: str,
    schedule: str,
    action: str,
) -> str:
    """
    创建定时任务。

    Args:
        name: 任务名称(人类可读),如 "检查 Git 状态"、"每日报告"
        schedule: Cron 表达式(分 时 日 月 周),如:
                  - "0 * * * *" 每小时
                  - "*/5 * * * *" 每 5 分钟
                  - "0 9 * * *" 每天 9:00
                  - "0 9 * * 1-5" 工作日 9:00
                  最小粒度为 1 分钟,不支持秒级调度
        action: 执行动作,格式为 "类型: 内容",支持:
                - "shell: <命令>" 执行 shell 命令,如 "shell: git status"
                - "agent: <消息>" 发送给 AI 处理,如 "agent: 总结今天的代码变更"
                - "agent:<类型>: <消息>" 指定子代理类型,如 "agent:coder: 重构 utils.py"
                  可用类型: general-purpose(默认)、coder、reviewer、researcher、tester、project-init
                - "py: <Python代码>" 在当前 Python 环境执行代码,如 "py: print('ok')"

    Returns:
        str: 创建结果消息,包含任务 ID
    """
    from .scheduler import Scheduler

    scheduler = Scheduler.get_instance()
    try:
        task_id = scheduler.add_task(name, schedule, action)
    except ValueError as e:
        return f"创建失败: {e}"

    return f"已创建定时任务: {task_id} ({name}, {schedule})"


@tool
def schedule_list() -> str:
    """
    列出所有定时任务。

    Returns:
        str: 格式化的任务列表,包含任务 ID、名称、调度、动作、状态、上次执行时间
    """
    from .scheduler import Scheduler

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
    from .scheduler import Scheduler

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
        enabled: True 启用,False 禁用

    Returns:
        str: 操作结果消息
    """
    from .scheduler import Scheduler

    scheduler = Scheduler.get_instance()
    action = "启用" if enabled else "禁用"
    if scheduler.toggle_task(task_id, enabled):
        return f"已{action}定时任务: {task_id}"
    return f"任务 '{task_id}' 不存在"


def get_tools() -> list:
    """获取调度器工具列表"""
    return [schedule_create, schedule_list, schedule_remove, schedule_toggle]


def get_all_tools() -> list:
    """获取所有调度器工具(无条件返回)"""
    return get_tools()
