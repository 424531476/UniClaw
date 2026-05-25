from agent import AgentTask
from console.ui import info, ok, warn, err


def cmd_schedule(args: str, task: AgentTask, config: dict) -> bool:
    """定时任务管理命令
    
    支持以下子命令：
    - list: 列出所有定时任务及其状态（默认命令）
    - add <id> <调度> <动作>: 创建新的定时任务
    - remove <id>: 删除指定的定时任务
    - enable <id>: 启用指定的定时任务
    - disable <id>: 禁用指定的定时任务
    
    调度格式：
    - every Ns/m/h/d: 周期性执行，如 "every 1h"、"every 30m"、"every 1d"
    - at YYYY-MM-DD HH:MM: 一次性执行，如 "at 2026-05-10 14:00"
    
    动作类型：
    - shell: <命令>: 执行 Shell 命令
    - agent: <消息>: 发送给 AI 处理
    
    Args:
        args: 命令参数，格式为 "<子命令> [参数]"
        task: 当前代理任务对象
        config: 配置字典
        
    Returns:
        bool: 始终返回 True 表示命令执行完成
    """
    from tools.scheduler.scheduler import Scheduler

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
    """列出所有定时任务及其状态
    
    显示每个任务的 ID、名称、调度规则、动作、启用状态和上次执行时间。
    
    Args:
        scheduler: Scheduler 实例
        
    Returns:
        bool: 始终返回 True
    """
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
    
    Args:
        scheduler: Scheduler 实例
        args_str: 参数字符串，包含任务ID、调度规则和动作
        
    Returns:
        bool: 始终返回 True
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
    """删除指定的定时任务
    
    Args:
        scheduler: Scheduler 实例
        task_id: 要删除的任务 ID
        
    Returns:
        bool: 始终返回 True
    """
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
    """启用或禁用指定的定时任务
    
    Args:
        scheduler: Scheduler 实例
        task_id: 任务 ID
        enabled: True 表示启用，False 表示禁用
        
    Returns:
        bool: 始终返回 True
    """
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
    """解析带引号的参数，支持单引号和双引号
    
    能够正确处理包含空格的参数，例如：
    - 'arg with space'
    - "arg with space"
    
    Args:
        s: 待解析的参数字符串
        
    Returns:
        list[str]: 解析后的参数列表
    """
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
