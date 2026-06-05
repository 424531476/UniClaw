from uniclaw.agent import AgentTask
from uniclaw.console.ui import info, ok, warn, err

# 子命令列表
SUBCOMMANDS = ["list", "output", "stop", "matched"]


def cmd_task(args: str, task: AgentTask, config: dict) -> bool:
    """后台任务管理命令

    支持以下子命令:
    - list: 列出所有后台任务(默认命令)
    - output <id> [lines]: 获取任务输出(默认 50 行)
    - stop <id>: 停止指定任务
    - matched <id>: 获取监控匹配结果

    Args:
        args: 命令参数,格式为 "<子命令> [参数]"
        task: 当前代理任务对象
        config: 配置字典

    Returns:
        bool: 始终返回 True 表示命令执行完成
    """
    from uniclaw.tools.monitor.manager import MonitorManager

    manager = MonitorManager.get_instance()
    parts = args.strip().split(None, 1) if args else []
    subcmd = parts[0].lower() if parts else "list"
    subargs = parts[1] if len(parts) > 1 else ""

    if subcmd == "list" or not subcmd:
        _task_list(manager)
    elif subcmd == "output":
        _task_output(manager, subargs)
    elif subcmd == "stop":
        _task_stop(manager, subargs)
    elif subcmd == "matched":
        _task_matched(manager, subargs)
    else:
        err(f"未知子命令: {subcmd}")
        info("可用命令: list, output, stop, matched")
    return True


def _task_list(manager) -> bool:
    """列出所有后台任务

    显示每个任务的 ID、命令、状态、运行时间和输出行数。

    Args:
        manager: MonitorManager 实例

    Returns:
        bool: 始终返回 True
    """
    result = manager.list_monitors()
    info(f"\n{result}\n")
    return True


def _task_output(manager, args_str: str) -> bool:
    """获取任务输出

    用法: /task output <id> [lines]
    示例: /task output abc123 100

    Args:
        manager: MonitorManager 实例
        args_str: 参数字符串,包含任务 ID 和可选的行数

    Returns:
        bool: 始终返回 True
    """
    parts = args_str.strip().split(None, 1) if args_str else []
    if not parts:
        err("请指定任务 ID: /task output <id> [lines]")
        return True

    task_id = parts[0]
    lines = 50
    if len(parts) > 1:
        try:
            lines = int(parts[1])
        except ValueError:
            err(f"行数必须是数字: {parts[1]}")
            return True

    result = manager.get_output(task_id, lines)
    info(f"\n{result}\n")
    return True


def _task_stop(manager, task_id: str) -> bool:
    """停止指定任务

    Args:
        manager: MonitorManager 实例
        task_id: 任务 ID

    Returns:
        bool: 始终返回 True
    """
    task_id = task_id.strip()
    if not task_id:
        err("请指定任务 ID: /task stop <id>")
        return True

    result = manager.stop_monitor(task_id)
    if result.startswith("错误"):
        err(result)
    else:
        ok(f"✓ {result}")
    return True


def _task_matched(manager, task_id: str) -> bool:
    """获取监控匹配结果

    Args:
        manager: MonitorManager 实例
        task_id: 任务 ID

    Returns:
        bool: 始终返回 True
    """
    task_id = task_id.strip()
    if not task_id:
        err("请指定任务 ID: /task matched <id>")
        return True

    result = manager.get_matched(task_id)
    info(f"\n{result}\n")
    return True
