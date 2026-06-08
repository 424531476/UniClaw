from uniclaw.agent import AgentTask
from uniclaw.console.ui import info, ok, err, clr, C, _get_tui, tui_clr
from uniclaw.console.dialog import DialogManager
from uniclaw.utils.checkpoint import list_checkpoints, pop_checkpoint, apply_checkpoint, delete_checkpoint, diff_checkpoint, diff_current, diff_between

# 子命令列表
SUBCOMMANDS = ["create", "pop", "apply", "delete", "diff"]


def cmd_checkpoint(args: str, task: AgentTask, config: dict) -> bool:
    """管理检查点

    /checkpoint           — 列出所有检查点
    /checkpoint diff      — 查看当前未提交的变更
    /checkpoint diff <序号> — 当前修改 vs 指定检查点
    /checkpoint diff <a> <b> — 比较两个检查点
    /checkpoint pop       — 恢复最近的检查点并删除
    /checkpoint pop <序号> — 恢复指定检查点并删除
    /checkpoint apply     — 恢复最近的检查点(保留)
    /checkpoint apply <序号> — 恢复指定检查点(保留)
    /checkpoint delete <序号> — 删除指定检查点
    /checkpoint <序号>     — 恢复指定检查点(保留)
    """
    parts = args.strip().lower().split() if args else []
    root_dir = task.session.root_dir
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
            diff = diff_between(root_dir, int(arg), int(arg2))
            _print_diff(f"📸 检查点[{arg}] vs 检查点[{arg2}]:", diff)
        elif arg.isdigit():
            diff = diff_checkpoint(root_dir, int(arg))
            _print_diff(f"📸 当前 vs 检查点[{arg}]:", diff)
        else:
            diff = diff_current(root_dir)
            _print_diff("📸 当前变更:", diff)
        return True

    # /checkpoint delete <序号>
    if cmd == "delete":
        if not arg.isdigit():
            err("用法: /checkpoint delete <序号>")
            return True
        success, message = delete_checkpoint(root_dir, index=int(arg))
        if success:
            ok(f"✓ {message}")
        else:
            err(f"✗ {message}")
        return True

    # /checkpoint pop <序号>
    if cmd == "pop":
        idx = int(arg) if arg.isdigit() else 0
        success, message = pop_checkpoint(root_dir, index=idx)
        if success:
            ok(f"✓ {message}")
        else:
            err(f"✗ {message}")
        return True

    # /checkpoint apply 或 /checkpoint <序号>
    if cmd == "apply" or cmd.isdigit():
        idx = 0 if cmd == "apply" else int(cmd)
        if arg.isdigit():
            idx = int(arg)
        success, message = apply_checkpoint(root_dir, index=idx)
        if success:
            ok(f"✓ {message}")
        else:
            err(f"✗ {message}")
        return True

    # 默认行为:列出检查点
    if not cmd:
        output = list_checkpoints(root_dir)
        info(f"📸 检查点列表:\n{output}")
        return True

    err(f"未知命令: {cmd}")
    return True
