from agent import AgentTask
from console.ui import info, ok, warn, err


def cmd_schedule(args: str, task: AgentTask, config: dict) -> bool:
    """定时任务管理"""
    from scheduler import Scheduler

    scheduler = Scheduler.get_instance()
    parts = args.strip().split(None, 1) if args else []
    subcmd = parts[0].lower() if parts else "list"
    subargs = parts[1] if len(parts) > 1 else ""

    if subcmd == "list" or not subcmd:
        _schedule_list(scheduler)
    elif subcmd == "add":
        _schedule_add(scheduler, subargs)
    elif subcmd == "remove":
        _schedule_remove(scheduler, subargs)
    elif subcmd == "enable":
        _schedule_toggle(scheduler, subargs, True)
    elif subcmd == "disable":
        _schedule_toggle(scheduler, subargs, False)
    else:
        err(f"未知子命令: {subcmd}")
        info("可用命令: list, add, remove, enable, disable")
    return True


def _schedule_list(scheduler) -> bool:
    tasks = scheduler.list_tasks()
    if not tasks:
        warn("暂无定时任务")
        info('使用 /schedule add <id> <schedule> <action> 添加任务')
        info("示例: /schedule add check-git \"every 1h\" \"shell: git status\"")
        return True

    info(f"\n定时任务 (共 {len(tasks)} 个):\n")
    for t in tasks:
        tid = t["id"]
        name = t.get("name", tid)
        schedule = t.get("schedule", "")
        action = t.get("action", "")
        enabled = t.get("enabled", True)
        last_run = t.get("last_run", "从未执行")

        status = "✓ 启用" if enabled else "✗ 禁用"
        info(f"  [{status}] {tid}")
        info(f"    名称: {name}")
        info(f"    调度: {schedule}")
        info(f"    动作: {action}")
        info(f"    上次执行: {last_run}")
        info("")
    return True


def _schedule_add(scheduler, args_str: str) -> bool:
    """添加定时任务

    用法: /schedule add <id> <schedule> <action>
    示例: /schedule add check-git "every 1h" "shell: git status"
    """
    parts = _parse_quoted_args(args_str)
    if len(parts) < 3:
        err("参数不足: /schedule add <id> <schedule> <action>")
        info("示例: /schedule add check-git \"every 1h\" \"shell: git status\"")
        info("调度格式: every Ns/m/h/d 或 at YYYY-MM-DD HH:MM")
        info("动作类型: shell: <命令> 或 agent: <消息>")
        return True

    task_id, schedule, action = parts[0], parts[1], parts[2]
    name = parts[3] if len(parts) > 3 else ""

    try:
        scheduler.add_task(task_id, name, schedule, action)
    except ValueError as e:
        err(str(e))
        return True

    ok(f"✓ 已添加定时任务: {task_id} ({schedule})")
    return True


def _schedule_remove(scheduler, task_id: str) -> bool:
    task_id = task_id.strip()
    if not task_id:
        err("请指定任务 ID: /schedule remove <id>")
        return True

    if scheduler.remove_task(task_id):
        ok(f"✓ 已删除定时任务: {task_id}")
    else:
        err(f"任务 '{task_id}' 不存在")
    return True


def _schedule_toggle(scheduler, task_id: str, enabled: bool) -> bool:
    task_id = task_id.strip()
    if not task_id:
        cmd = "enable" if enabled else "disable"
        err(f"请指定任务 ID: /schedule {cmd} <id>")
        return True

    action = "启用" if enabled else "禁用"
    if scheduler.toggle_task(task_id, enabled):
        ok(f"✓ 已{action}定时任务: {task_id}")
    else:
        err(f"任务 '{task_id}' 不存在")
    return True


def _parse_quoted_args(s: str) -> list[str]:
    """解析带引号的参数，支持 'arg with space' 和 \"arg with space\""""
    args = []
    current = ""
    in_quote = None

    for ch in s:
        if in_quote:
            if ch == in_quote:
                in_quote = None
            else:
                current += ch
        elif ch in ('"', "'"):
            in_quote = ch
        elif ch == " ":
            if current:
                args.append(current)
                current = ""
        else:
            current += ch

    if current:
        args.append(current)
    return args
