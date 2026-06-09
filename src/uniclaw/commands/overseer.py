from uniclaw.config import AppConfig
from uniclaw.console.ui import info, ok, warn

# 子命令列表
SUBCOMMANDS = ["start", "stop"]


def cmd_overseer(args: str, config: AppConfig) -> bool:
    """启动或退出监工模式

    监工模式下:
    - TodoList 每完成一项必须通过子代理审核验收
    - Agent 试图休息时,如有未完成任务会被督促继续

    用法:
      /overseer start  - 启动监工模式
      /overseer stop   - 退出监工模式
      /overseer        - 查看当前状态
    """
    todo = config.current_agent.todolist
    if todo is None:
        warn("当前任务没有 TodoList(仅 root 任务支持)")
        return True

    manager = todo.overseer
    arg = args.strip().lower()

    if arg == "start":
        if manager.active:
            warn("监工模式已在运行中")
        else:
            manager.start()
            ok("监工模式已启动: TodoList 完成需审核验收,未完成任务会被督促")
        return True

    if arg == "stop":
        if not manager.active:
            warn("监工模式未在运行")
        else:
            manager.stop()
            ok("监工模式已退出")
        return True

    # 无参数:显示状态
    if manager.active:
        info("监工模式: 运行中")
        info("  - TodoList 完成需审核验收")
        info("  - 未完成任务会被督促继续")
    else:
        info("监工模式: 未运行")
        info("  使用 /overseer start 启动")
    return True
