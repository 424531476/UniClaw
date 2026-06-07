from pathlib import Path
from uniclaw.agent import AgentTask
from uniclaw.console.ui import info, ok, warn, err


def cmd_add_dir(args: str, task: AgentTask, config: dict) -> bool:
    """将目录添加到当前工作空间

    支持以下功能：
    - 无参数：列出额外工作空间目录
    - <路径>: 添加额外工作空间目录
    - rm/remove <路径>: 移除额外工作空间目录

    Args:
        args: 目录路径或 rm/remove 子命令
        task: 当前代理任务对象
        config: 配置字典

    Returns:
        bool: 始终返回 True
    """
    if "workspace" not in config:
        config["workspace"] = []

    args = args.strip()

    # 无参数：列出已添加的目录
    if not args:
        dirs = config["workspace"]
        if not dirs:
            info("没有额外工作空间目录")
        else:
            info(f"\n额外工作空间目录 ({len(dirs)} 个):")
            for i, d in enumerate(dirs, 1):
                info(f"  {i}. {d}")
            info("")
        return True

    # rm/remove 子命令：移除目录
    if args.lower().startswith(("rm ", "remove ")):
        _, _, path = args.partition(maxsplit=1)
        path = path.strip()
        if not path:
            err("请指定要移除的目录路径")
            return True
        try:
            abs_path = str(Path(path).resolve())
        except Exception:
            err(f"无效路径: {path}")
            return True
        extra = config["workspace"]
        found = False
        for i, d in enumerate(extra):
            try:
                if str(Path(d).resolve()) == abs_path:
                    extra.pop(i)
                    found = True
                    break
            except Exception:
                continue
        if found:
            ok(f"已移除额外工作空间目录: {abs_path}")
        else:
            warn(f"该目录不是额外工作空间目录: {abs_path}")
        return True

    # 添加目录
    try:
        abs_path = Path(args).resolve()
    except Exception:
        err(f"无效路径: {args}")
        return True

    if not abs_path.exists():
        err(f"路径不存在: {args}")
        return True
    if not abs_path.is_dir():
        err(f"不是目录: {args}")
        return True

    abs_str = str(abs_path)

    # 检查是否与当前工作目录重复
    session_cwd = task.session.cwd
    if session_cwd:
        try:
            if str(Path(session_cwd).resolve()) == abs_str:
                warn(f"该目录已是当前工作目录: {abs_str}")
                return True
        except Exception:
            pass

    # 去重检查
    for d in config["workspace"]:
        try:
            if str(Path(d).resolve()) == abs_str:
                warn(f"该目录已是工作空间: {abs_str}")
                return True
        except Exception:
            continue

    config["workspace"].append(abs_str)
    ok(f"已添加额外工作空间: {abs_str}")
    return True
