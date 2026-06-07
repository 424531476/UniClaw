from uniclaw.agent import AgentTask
from uniclaw.console.ui import ok, err, info
from uniclaw.utils.git import restore_checkpoint

# 子命令列表
SUBCOMMANDS = ["list", "restore"]


def cmd_undo(args: str, task: AgentTask, config: dict) -> bool:
    """撤销 AI 的文件编辑,恢复到检查点

    /undo        — 恢复到最近的检查点
    /undo <序号>  — 恢复到指定检查点
    """
    cwd = task.session.cwd
    idx = int(args.strip()) if args.strip().isdigit() else 0
    success, message = restore_checkpoint(cwd, index=idx)
    if success:
        ok(f"✓ {message}")
    else:
        err(f"✗ {message}")
    return True
