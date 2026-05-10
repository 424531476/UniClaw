import os
from console.ui import info, ok, warn, err


def cmd_cwd(args: str, _state, _config) -> bool:
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


def cmd_status(_args: str, state, config) -> bool:
    """显示当前会话状态信息"""
    from compaction import estimate_tokens, get_context_limit
    
    # 获取模型信息
    model_name = config.get("model_name", "未设置")
    
    # 计算Token使用情况
    used_tokens = estimate_tokens(state.messages, model_name)
    context_limit = get_context_limit(model_name)
    usage_pct = (used_tokens / context_limit * 100) if context_limit else 0
    
    # 消息统计
    message_count = len(state.messages)
    user_messages = sum(1 for m in state.messages if m.get("role") == "user")
    assistant_messages = sum(1 for m in state.messages if m.get("role") == "assistant")
    tool_messages = sum(1 for m in state.messages if m.get("role") == "tool")
    
    # 权限模式
    permission_mode = config.get("permission_mode", "auto")
    
    # 工作目录
    cwd = os.getcwd()
    
    # 显示状态信息
    info("\n=== 当前会话状态 ===\n")
    
    print(f"📊 Token使用:")
    print(f"   已用: {used_tokens:,} / {context_limit:,}")
    print(f"   使用率: {usage_pct:.1f}%")
    
    # 根据使用率显示颜色提示
    if usage_pct < 40:
        status_icon = "🟢"
        status_text = "充足"
    elif usage_pct < 70:
        status_icon = "🟡"
        status_text = "中等"
    else:
        status_icon = "🔴"
        status_text = "紧张"
    print(f"   状态: {status_icon} {status_text}")
    print()
    
    print(f"💬 消息统计:")
    print(f"   总消息数: {message_count}")
    print(f"   用户消息: {user_messages}")
    print(f"   助手消息: {assistant_messages}")
    print(f"   工具消息: {tool_messages}")
    print()
    
    print(f"🤖 模型配置:")
    print(f"   当前模型: {model_name}")
    print(f"   迷你模型: {config.get('mini_model_name', '未设置')}")
    print()
    
    print(f"⚙️ 系统配置:")
    print(f"   权限模式: {permission_mode}")
    print(f"   工作目录: {cwd}")
    print(f"   Agent深度: {config.get('depth', 0)} / {config.get('max_agent_depth', 3)}")
    print()
    
    return True


def cmd_skills(_args: str, _state, config) -> bool:
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

        print(title)
        for skill in skill_list:
            triggers = ", ".join(skill.triggers[:3])
            if len(skill.triggers) > 3:
                triggers += f" (+{len(skill.triggers) - 3})"
            print(f"  • {skill.name}: {skill.description}")
            print(f"    触发器: {triggers}")
            if skill.when_to_use:
                print(f"    使用时机: {skill.when_to_use}")
            if skill.argument_hint:
                print(f"    参数提示: {skill.argument_hint}")
            print()

    return True


def cmd_exit(_args: str, _state, _config) -> bool:
    """退出程序"""
    ok("再见！")
    raise SystemExit(0)


def cmd_usage(_args: str, _state, _config) -> bool:
    """显示用量统计"""
    from utils.usage import format_stats
    info(format_stats())
    return True
