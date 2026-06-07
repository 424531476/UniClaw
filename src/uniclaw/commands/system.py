import os
from uniclaw.agent import AgentTask
from uniclaw.console.ui import info, ok, warn, err


def cmd_cwd(args: str, task: AgentTask, config: dict) -> bool:
    """显示或更改当前工作目录

    - 无参数：显示当前工作目录的完整路径
    - <路径>：切换到指定的目录(支持相对路径和绝对路径)
    """
    if not args.strip():
        info(f"当前工作目录: {task.session.cwd}")
    else:
        import pathlib
        target_path = pathlib.Path(args.strip()).resolve()
        if not target_path.exists():
            err(f"目录不存在: {args.strip()}")
            return True
        if not target_path.is_dir():
            err(f"不是目录: {args.strip()}")
            return True
        try:
            task.session.cwd = target_path
            ok(f"工作目录已切换到: {target_path}")
        except Exception as e:
            err(str(e))
    return True


def cmd_skills(_args: str, task: AgentTask, config: dict) -> bool:
    """列出所有可用的技能

    从多个常见项目目录中自动加载技能文件,按来源分组显示：
    内置技能、用户技能和项目技能。
    """
    from uniclaw.tools.skill.loader import load_skills

    skills = load_skills()
    if not skills:
        warn("当前没有可用的技能")
        return True

    groups = {
        "builtin": ("【内置技能】", []),
        "user": ("【用户技能】", []),
        "project": ("【项目技能】", [])
    }
    for skill in skills:
        if skill.source in groups:
            groups[skill.source][1].append(skill)

    info(f"\n可用技能 (共 {len(skills)} 个):\n")
    for source_key, (title, skill_list) in groups.items():
        if not skill_list:
            continue
        info(title)
        for skill in skill_list:
            triggers = ", ".join(skill.triggers[:3])
            if len(skill.triggers) > 3:
                triggers += f" (+{len(skill.triggers) - 3})"
            info(f"  - {skill.name}: {skill.description}")
            info(f"    触发器: {triggers}")
            if skill.when_to_use:
                info(f"    使用时机: {skill.when_to_use}")
            if skill.argument_hint:
                info(f"    参数提示: {skill.argument_hint}")
            info("")
    return True


def cmd_exit(_args: str, task: AgentTask, config: dict) -> bool:
    """退出程序,显示告别消息并终止运行。"""
    ok("再见！")
    raise SystemExit(0)


def cmd_usage(_args: str, task: AgentTask, config: dict) -> bool:
    """显示 Token 使用统计,包括输入/输出 token 数和 API 调用次数。"""
    from uniclaw.utils.usage import format_stats
    info(format_stats())
    return True


def cmd_help(_args: str, task: AgentTask, config: dict) -> bool:
    """显示所有可用的斜杠命令帮助信息,按分类列出命令和快捷键提示。"""
    info("\n📖 UniClaw 斜杠命令帮助\n")

    info("【会话管理】")
    info("  /btw <问题>            - 侧问题:不打断当前对话提问")
    info("  /name [名称]          - 为会话命名(无参数自动生成)")
    info("  /clear, /cls          - 清空当前对话历史并清屏")
    info("  /compact [关键词]      - 压缩上下文,优化 Token 使用")
    info("  /export [路径]         - 导出当前会话到文件(Markdown/JSON)")
    info("  /resume [ID]           - 恢复会话(无参数交互式选择)")
    info("  /resume list           - 列出所有历史对话")
    info("  /resume del <ID>       - 删除指定会话")
    info("  /resume search <关键词> - 搜索对话内容")
    info("")

    info("【Git 检查点】")
    info("  /undo                 - 撤销 AI 最近的文件编辑")
    info("  /undo <序号>          - 恢复到指定检查点")
    info("  /checkpoint           - 列出所有检查点")
    info("  /checkpoint diff      - 查看当前未提交的变更")
    info("  /checkpoint diff <序号> - 当前修改 vs 指定检查点")
    info("  /checkpoint diff <a> <b> - 比较两个检查点")
    info("  /checkpoint restore   - 恢复最近的检查点")
    info("  /checkpoint <序号>    - 恢复指定检查点")
    info("")

    info("【监工模式】")
    info("  /overseer start        - 启动监工模式(TodoList完成需审核)")
    info("  /overseer stop         - 退出监工模式")
    info("  /overseer              - 查看监工模式状态")
    info("")

    info("【模型与系统】")
    info("  /model [名称]          - 查看或切换当前使用的模型")
    info("  /config [get|set|reset] - 运行时配置管理")
    info("  /cwd, /cd, /pwd [路径] - 查看或切换工作目录")
    info("  /add-dir <路径>        - 添加额外工作空间目录(仅当前会话有效)")
    info("  /usage                 - 查看 Token 使用统计")
    info("  /cost                  - 查看费用统计(按模型计费,价格来自 OpenRouter)")
    info("  /context               - 查看当前上下文 token 构成")
    info("  /skills                - 列出所有可用技能")
    info("  /init                  - 扫描项目并生成/更新 CLAUDE.md")
    info("  /doctor                - 环境诊断(检查依赖和配置状态)")
    info("  /help                  - 显示本帮助信息")
    info("  /exit, /quit           - 退出程序")
    info("")

    info("【记忆管理】")
    info("  /memory                - 列出所有记忆")
    info("  /memory <关键词>       - 搜索相关记忆")
    info("  /memory consolidate    - 从当前对话提取记忆")
    info("")

    info("【MCP 管理】")
    info("  /mcp list              - 列出 MCP 服务器")
    info("  /mcp add <名称> [JSON] - 添加 MCP 服务器")
    info("  /mcp remove <名称>     - 删除 MCP 服务器")
    info("  /mcp show <名称>       - 查看服务器详情")
    info("  /mcp edit <名称> [JSON] - 编辑服务器配置")
    info("  /mcp enable/disable <名称> - 启用/禁用服务器")
    info("  /mcp tools [名称]      - 列出 MCP 工具")
    info("  /mcp refresh           - 刷新 MCP 工具")
    info("")

    info("【定时任务】")
    info("  /schedule list         - 列出所有定时任务")
    info('  /schedule add <id> <调度> <动作> - 创建定时任务')
    info("  /schedule remove <id>  - 删除定时任务")
    info("  /schedule enable <id>  - 启用定时任务")
    info("  /schedule disable <id> - 禁用定时任务")
    info("")

    info("【后台任务】")
    info("  /task                  - 列出所有后台任务")
    info("  /task list             - 列出所有后台任务")
    info("  /task output <id> [N]  - 获取任务输出(默认 50 行)")
    info("  /task stop <id>        - 停止指定任务")
    info("  /task matched <id>     - 获取监控匹配结果")
    info("")

    info("【权限管理】")
    info("  /permissions list      - 查看所有权限规则")
    info("  /permissions remove <类型> <模式> - 删除权限规则")
    info("")

    info("💡 提示:")
    info("  - 输入 /<命令> help 可查看该命令的详细说明(如 /memory help)")
    info("  - 输入 ! 开头的命令可直接执行 Shell 命令(如 !ls -la)")
    info("  - 按 F2 键可切换详细/简洁显示模式")
    info("  - 按 ESC 键可中断正在运行的任务")
    info("  - 按 Ctrl+K 可聚焦对话侧边栏")
    info("")

    return True
