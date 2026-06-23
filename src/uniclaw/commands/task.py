from uniclaw.config import AppConfig
from uniclaw.console.ui import info, ok, warn, err

# 子命令列表
SUBCOMMANDS = ["list", "output", "stop", "matched"]


async def cmd_task(args: str, config: AppConfig) -> bool:
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
        await _task_list(manager, config=config)
    elif subcmd == "output":
        await _task_output(manager, subargs, config=config)
    elif subcmd == "stop":
        await _task_stop(manager, subargs, config=config)
    elif subcmd == "matched":
        await _task_matched(manager, subargs, config=config)
    else:
        await err(f"未知子命令: {subcmd}", config)
        await info("可用命令: list, output, stop, matched", config)
    return True


async def _task_list(manager, config: AppConfig) -> bool:
    """列出所有后台任务

    显示每个任务的 ID、命令、状态、运行时间和输出行数。

    Args:
        manager: MonitorManager 实例

    Returns:
        bool: 始终返回 True
    """
    result = await manager.list_monitors()
    await info(f"\n{result}\n", config)
    return True


async def _task_output(manager, args_str: str, config: AppConfig) -> bool:
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
        await err("请指定任务 ID: /task output <id> [lines]", config)
        return True

    task_id = parts[0]
    lines = 50
    if len(parts) > 1:
        try:
            lines = int(parts[1])
        except ValueError:
            await err(f"行数必须是数字: {parts[1]}", config)
            return True

    result = await manager.get_output(task_id, lines)
    await info(f"\n{result}\n", config)
    return True


async def _task_stop(manager, task_id: str, config: AppConfig) -> bool:
    """停止指定任务

    Args:
        manager: MonitorManager 实例
        task_id: 任务 ID

    Returns:
        bool: 始终返回 True
    """
    task_id = task_id.strip()
    if not task_id:
        await err("请指定任务 ID: /task stop <id>", config)
        return True

    result = await manager.stop_monitor(task_id)
    if result.startswith("错误"):
        await err(result, config)
    else:
        await ok(f"✓ {result}", config)
    return True


async def _task_matched(manager, task_id: str, config: AppConfig) -> bool:
    """获取监控匹配结果

    Args:
        manager: MonitorManager 实例
        task_id: 任务 ID

    Returns:
        bool: 始终返回 True
    """
    task_id = task_id.strip()
    if not task_id:
        await err("请指定任务 ID: /task matched <id>", config)
        return True

    result = await manager.get_matched(task_id)
    await info(f"\n{result}\n", config)
    return True
