import os
from agent import AgentTask
from console.ui import info, ok, warn, err


def cmd_cwd(args: str, task: AgentTask, config: dict) -> bool:
    """显示或更改当前工作目录"""
    if not args.strip():
        # 无参数时显示当前工作目录
        current_dir = os.getcwd()
        info(f"当前工作目录: {current_dir}")
    else:
        # 有参数时切换到指定目录
        import pathlib
        target_path = pathlib.Path(args.strip()).resolve()
        if not target_path.exists():
            err(f"目录不存在: {args.strip()}")
            return True
        if not target_path.is_dir():
            err(f"不是目录: {args.strip()}")
            return True
        try:
            os.chdir(str(target_path))
            ok(f"工作目录已切换到: {target_path}")
        except Exception as e:
            err(str(e))
    return True


def cmd_skills(_args: str, task: AgentTask, config: dict) -> bool:
    """列出所有可用的技能"""
    from tools.skill.loader import load_skills

    skills = load_skills()
    if not skills:
        warn("当前没有可用的技能")
        return True

    # 按来源分组
    groups = {
        "builtin": ("【内置技能】", []),
        "user": ("【用户技能】", []),
        "project": ("【项目技能】", [])
    }

    for skill in skills:
        if skill.source in groups:
            groups[skill.source][1].append(skill)

    info(f"\n可用技能 (共 {len(skills)} 个):\n")

    # 统一处理每个分组
    for source_key, (title, skill_list) in groups.items():
        if not skill_list:
            continue

        info(title)
        for skill in skill_list:
            triggers = ", ".join(skill.triggers[:3])
            if len(skill.triggers) > 3:
                triggers += f" (+{len(skill.triggers) - 3})"
            info(f"  • {skill.name}: {skill.description}")
            info(f"    触发器: {triggers}")
            if skill.when_to_use:
                info(f"    使用时机: {skill.when_to_use}")
            if skill.argument_hint:
                info(f"    参数提示: {skill.argument_hint}")
            info("")

    return True


def cmd_exit(_args: str, task: AgentTask, config: dict) -> bool:
    """退出程序"""
    ok("再见！")
    raise SystemExit(0)


def cmd_usage(_args: str, task: AgentTask, config: dict) -> bool:
    """显示用量统计"""
    from utils.usage import format_stats
    info(format_stats())
    return True
