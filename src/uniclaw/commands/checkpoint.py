from uniclaw.agent import AgentTask
from uniclaw.console.ui import info, ok, err, clr, C, _get_tui, tui_clr
from uniclaw.console.dialog import DialogManager
from uniclaw.utils.git import list_checkpoints, restore_checkpoint, diff_current, diff_between, diff_with_checkpoint

# 子命令列表
SUBCOMMANDS = ["list", "create", "restore", "diff"]


def cmd_checkpoint(args: str, task: AgentTask, config: dict) -> bool:
    """管理 Git 检查点

    /checkpoint           — 列出所有检查点
    /checkpoint diff      — 查看当前未提交的变更
    /checkpoint diff <序号> — 当前修改 vs 指定检查点
    /checkpoint diff <a> <b> — 比较两个检查点
    /checkpoint restore   — 恢复最近的检查点
    /checkpoint <序号>     — 恢复指定检查点
    """
    parts = args.strip().lower().split() if args else []
    cwd = task.session.cwd
    cmd = parts[0] if parts else ""
    arg = parts[1] if len(parts) > 1 else ""
    arg2 = parts[2] if len(parts) > 2 else ""

    def _print_diff(header: str, diff: str):
        tui = _get_tui()
        if tui:
            tui.print(tui_clr(header, C.CYAN))
            tui.print(DialogManager.diff_fragments(diff))
        else:
            print(clr(header, C.CYAN))
            print(diff)

    # /checkpoint diff [序号] [序号]
    if cmd == "diff":
        if arg.isdigit() and arg2.isdigit():
            diff = diff_between(cwd, int(arg), int(arg2))
            _print_diff(f"📸 stash@{{{arg}}} vs stash@{{{arg2}}}:", diff)
        elif arg.isdigit():
            diff = diff_with_checkpoint(cwd, int(arg))
            _print_diff(f"📸 当前 vs stash@{{{arg}}}:", diff)
        else:
            diff = diff_current(cwd)
            _print_diff("📸 当前变更:", diff)
        return True

    # /checkpoint restore 或 /checkpoint <序号>
    if cmd == "restore" or cmd.isdigit():
        idx = 0 if cmd == "restore" else int(cmd)
        success, message = restore_checkpoint(cwd, index=idx)
        if success:
            ok(f"✓ {message}")
        else:
            err(f"✗ {message}")
        return True

    # 默认行为:列出检查点
    if not cmd:
        output = list_checkpoints(cwd)
        info(f"📸 检查点列表:\n{output}")
        return True

    err(f"未知命令: {cmd}")
    return True
