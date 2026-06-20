from uniclaw.config import AppConfig
from uniclaw.console.ui import info, ok, warn

# 子命令列表
SUBCOMMANDS = ["clear", "status"]


async def cmd_goal(args: str, config: AppConfig) -> bool:
    """设置或查看目标停止条件

    设置目标后,当 agent 试图停止时会用独立 judge 模型评估是否达成目标:
    - 目标达成 → 允许退出
    - 目标未达标 → 注入原因让 agent 继续工作
    - 超过最大重入次数(默认3次) → 允许退出,防止无限循环

    用法:
      /goal <目标描述>  - 设置目标(自动开始生效)
      /goal clear       - 清除目标
      /goal status      - 查看当前目标和重入计数
      /goal             - 查看当前状态
    """
    task = config.current_agent
    goal_mgr = task.goal_manager if task else None
    if goal_mgr is None:
        warn("当前任务没有 GoalManager(仅 root 任务支持)", config)
        return True

    arg = args.strip()

    # /goal clear
    if arg.lower() == "clear":
        if not goal_mgr.active:
            warn("当前没有设置目标", config)
        else:
            goal_mgr.clear_goal()
            ok("目标已清除", config)
        return True

    # /goal status
    if arg.lower() == "status":
        info(goal_mgr.get_status(), config)
        return True

    # /goal <描述> — 设置目标
    if arg:
        goal_mgr.set_goal(arg)
        ok(f"目标已设置: {arg}", config)
        info("agent 将在每次尝试停止时评估目标是否达成", config)
        info(f"最大重入次数: {goal_mgr.max_reentry}", config)
        return True

    # 无参数: 显示状态
    info(goal_mgr.get_status(), config)
    if not goal_mgr.active:
        info("  使用 /goal <目标描述> 设置目标", config)
    return True
