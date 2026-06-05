from agent import AgentTask
from console.ui import info, ok, err
from utils.git import list_checkpoints, restore_checkpoint


def cmd_checkpoint(args: str, task: AgentTask, config: dict) -> bool:
    """管理 Git 检查点

    /checkpoint           — 列出所有检查点
    /checkpoint restore   — 恢复最近的检查点
    /checkpoint <序号>     — 恢复指定检查点
    """
    subcmd = args.strip().lower() if args else ""
    cwd = config.get("cwd", ".")

    # /checkpoint restore 或 /checkpoint <序号>
    if subcmd:
        idx = 0 if subcmd == "restore" else int(subcmd) if subcmd.isdigit() else None
        if idx is None:
            err(f"未知命令: {subcmd}")
            return True
        success, message = restore_checkpoint(cwd, index=idx)
        if success:
            ok(f"✓ {message}")
        else:
            err(f"✗ {message}")
        return True

    # 默认行为：列出检查点
    output = list_checkpoints(cwd)
    info(f"📸 检查点列表:\n{output}")
    return True
