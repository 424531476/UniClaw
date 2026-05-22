import os
from agent import AgentTask
from console.ui import info, ok, warn, err


# 命令别名映射：将别名指向主命令
COMMAND_ALIASES = {
    "cls": "clear",
    "cd": "cwd",
    "pwd": "cwd",
    "quit": "exit",
}

# 命令详细说明字典，用于 /help <command> 显示详细信息
# 只定义主命令，别名通过 COMMAND_ALIASES 自动映射
COMMAND_DETAILS = {
    # 会话管理命令
    "clear": {
        "name": "/clear, /cls",
        "category": "会话管理",
        "description": "清空当前对话历史并清屏",
        "usage": "/clear 或 /cls",
        "details": [
            "• 清空所有消息历史",
            "• 重置会话 ID 和开始时间",
            "• 清除终端屏幕内容",
            "• 开始全新的对话会话"
        ],
        "examples": [
            "/clear",
            "/cls"
        ]
    },
    "compact": {
        "name": "/compact",
        "category": "会话管理",
        "description": "压缩上下文，优化 Token 使用",
        "usage": "/compact [关键词]",
        "details": [
            "• 通过移除或摘要化旧消息来减少上下文长度",
            "• 可选的聚焦参数用于保留与特定主题相关的消息",
            "• 自动估算压缩前后的 Token 数量",
            "• 显示节省的 Token 数量"
        ],
        "examples": [
            "/compact",
            "/compact python编程"
        ]
    },
    "export": {
        "name": "/export",
        "category": "会话管理",
        "description": "导出当前会话到文件(Markdown/JSON)",
        "usage": "/export [路径]",
        "details": [
            "• 支持 Markdown (.md) 和 JSON (.json) 两种格式",
            "• 根据文件扩展名自动选择格式",
            "• 未指定路径时导出到用户目录的 exports 文件夹",
            "• 文件名包含时间戳，便于管理",
            "• 导出内容包括消息历史、Token 统计等完整信息"
        ],
        "examples": [
            "/export",
            "/export conversation.md",
            "/export D:/exports/my_chat.json"
        ]
    },
    "conversation": {
        "name": "/conversation",
        "category": "会话管理",
        "description": "管理持久化对话历史",
        "usage": "/conversation [list|load|del|search] [参数]",
        "details": [
            "• list: 列出所有对话历史(默认命令),支持按任务ID过滤",
            "• load <session_id>: 加载指定会话到当前上下文",
            "• del/delete/rm <session_id>: 删除指定会话（需要确认）",
            "• search <keyword>: 搜索包含关键词的对话内容",
            "• 对话数据持久化存储在 .UniClaw/conversations/ 目录",
            "• 支持完整的元数据索引和快速检索"
        ],
        "examples": [
            "/conversation list",
            "/conversation load 20260520_105455_a3f2b8c1",
            "/conversation del 20260520_105455_a3f2b8c1",
            "/conversation search python"
        ]
    },
    
    # 模型与系统命令
    "model": {
        "name": "/model",
        "category": "模型与系统",
        "description": "查看或切换当前使用的模型",
        "usage": "/model [名称]",
        "details": [
            "• 无参数时显示所有可用模型列表并交互式选择",
            "• 直接指定模型名称可快速切换",
            "• 支持模糊搜索匹配的模型",
            "• 从 API 动态获取可用模型列表",
            "• 显示当前正在使用的模型标记"
        ],
        "examples": [
            "/model",
            "/model gpt-4o",
            "/model gpt"
        ]
    },
    "cwd": {
        "name": "/cwd, /cd, /pwd",
        "category": "模型与系统",
        "description": "查看或切换工作目录",
        "usage": "/cwd [路径] 或 /cd [路径] 或 /pwd",
        "details": [
            "• 无参数时显示当前工作目录的完整路径",
            "• 指定路径时切换到该目录",
            "• 支持相对路径和绝对路径",
            "• 自动验证路径是否存在且为目录",
            "• /cd 和 /pwd 是 /cwd 的别名，符合 Unix 习惯"
        ],
        "examples": [
            "/cwd",
            "/cd D:/projects",
            "/pwd"
        ]
    },
    "usage": {
        "name": "/usage",
        "category": "模型与系统",
        "description": "查看 Token 使用统计",
        "usage": "/usage",
        "details": [
            "• 显示总输入 Token 数量",
            "• 显示总输出 Token 数量",
            "• 显示 API 调用次数",
            "• 显示工具调用统计",
            "• 帮助监控和管理 API 用量"
        ],
        "examples": ["/usage"]
    },
    "context": {
        "name": "/context",
        "category": "模型与系统",
        "description": "查看当前上下文窗口的 token 构成和占比",
        "usage": "/context",
        "details": [
            "• 显示 system prompt、工具 schema、skills、消息和预留压缩区的估算 token",
            "• 按工具包和单个工具列出主要 token 占用",
            "• 按 skill 来源和单个 skill 列出主要 token 占用",
            "• 这是本地估算值，实际 provider 侧工具 schema 开销可能略有差异"
        ],
        "examples": ["/context"]
    },
    "skills": {
        "name": "/skills",
        "category": "模型与系统",
        "description": "列出所有可用技能",
        "usage": "/skills",
        "details": [
            "• 从多个常见项目目录中自动加载技能文件",
            "• 支持 .claude/skills/、.codex/skills/、.agents/skills/、skills/",
            "• 按来源分组显示：内置技能、用户技能和项目技能",
            "• 显示每个技能的触发器、使用时机和参数提示",
            "• 帮助了解可用的自动化工作流"
        ],
        "examples": ["/skills"]
    },
    "help": {
        "name": "/help",
        "category": "模型与系统",
        "description": "显示所有可用的斜杠命令帮助信息",
        "usage": "/help [命令名称]",
        "details": [
            "• 无参数时显示所有命令的分类概览",
            "• 指定命令名称时显示该命令的详细说明",
            "• 包括用法、功能描述、使用示例等",
            "• 提供实用的快捷键提示",
            "• 帮助用户快速了解和使用命令系统"
        ],
        "examples": [
            "/help",
            "/help model",
            "/help conversation"
        ]
    },
    "exit": {
        "name": "/exit, /quit",
        "category": "模型与系统",
        "description": "退出程序",
        "usage": "/exit 或 /quit",
        "details": [
            "• 显示告别消息",
            "• 安全终止程序运行",
            "• 自动保存当前会话（如果启用）",
            "• /quit 是 /exit 的别名"
        ],
        "examples": [
            "/exit",
            "/quit"
        ]
    },
    
    # 记忆管理命令
    "memory": {
        "name": "/memory",
        "category": "记忆管理",
        "description": "记忆管理系统",
        "usage": "/memory [关键词|consolidate]",
        "details": [
            "• 无参数：列出所有记忆的详细信息",
            "• <关键词>：使用 AI 智能搜索相关记忆",
            "• consolidate:从当前对话中提取并保存记忆",
            "• 支持三种作用域：用户级、项目级、会话级",
            "• 记忆类型包括：用户偏好、项目信息、反馈等",
            "• 自动在对话中加载相关记忆以增强上下文理解"
        ],
        "examples": [
            "/memory",
            "/memory 代码风格",
            "/memory consolidate"
        ]
    },
    
    # MCP 管理命令
    "mcp": {
        "name": "/mcp",
        "category": "MCP 管理",
        "description": "MCP (Model Context Protocol) 服务器管理",
        "usage": "/mcp [list|add|remove|show|edit|enable|disable|tools|refresh] [参数]",
        "details": [
            "• list: 列出所有已配置的 MCP 服务器（默认命令）",
            "• add <名称> [JSON]: 添加新的 MCP 服务器，支持交互式或 JSON 配置",
            "• remove <名称>: 删除指定的 MCP 服务器",
            "• show <名称>: 显示指定服务器的详细配置信息",
            "• edit <名称> [JSON]: 编辑现有 MCP 服务器配置",
            "• enable/disable <名称>: 启用或禁用指定的 MCP 服务器",
            "• tools [服务器名]: 列出可用的 MCP 工具",
            "• refresh: 刷新并重新加载所有 MCP 工具",
            "• 支持 stdio、sse、streamable_http、websocket 四种协议"
        ],
        "examples": [
            "/mcp list",
            '/mcp add fs {"transport":"stdio","command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","D:/code"]}',
            "/mcp remove fs",
            "/mcp tools"
        ]
    },
    
    # 定时任务命令
    "schedule": {
        "name": "/schedule",
        "category": "定时任务",
        "description": "定时任务管理系统",
        "usage": "/schedule [list|add|remove|enable|disable] [参数]",
        "details": [
            "• list: 列出所有定时任务及其状态（默认命令）",
            "• add <id> <调度> <动作>: 创建新的定时任务",
            "• remove <id>: 删除指定的定时任务",
            "• enable/disable <id>: 启用或禁用指定的定时任务",
            "• 调度格式:every Ns/m/h/d(周期性)或 at YYYY-MM-DD HH:MM(一次性)",
            "• 动作类型:shell: <命令> 或 agent: <消息>",
            "• 可用于自动化运维、定期代码检查、定时报告生成等场景"
        ],
        "examples": [
            "/schedule list",
            '/schedule add check-git "every 1h" "shell: git status"',
            '/schedule add daily-report "at 2026-05-10 09:00" "agent: 总结昨天的代码变更"',
            "/schedule remove check-git",
            "/schedule disable check-git"
        ]
    },
    
    # 权限管理命令
    "permissions": {
        "name": "/permissions",
        "category": "权限管理",
        "description": "权限规则管理系统",
        "usage": "/permissions [list|remove] [参数]",
        "details": [
            "• list: 列出所有已保存的权限规则（默认命令）",
            "• remove <类型> <模式>: 删除指定的权限规则",
            "• 权限规则分为两种类型：",
            "  - bash: 基于命令前缀匹配的 Bash 命令规则(如 'git commit')",
            "  - tool: 基于工具名称精确匹配的工具规则(如 'Write')",
            "• 授权后同类操作将自动放行，避免重复确认",
            "• 规则存储在项目的 permission_rules.json 文件中",
            "• 仍会被危险操作符检测（如 ;、&&、||）拦截，确保安全"
        ],
        "examples": [
            "/permissions list",
            '/permissions add bash "git commit"',
            "/permissions add tool Write",
            '/permissions remove bash "git commit"'
        ]
    }
}


def _get_command_details(cmd_name: str) -> dict | None:
    """获取命令的详细信息，支持别名解析
    
    Args:
        cmd_name: 命令名称
        
    Returns:
        dict | None: 命令详细信息字典，如果未找到则返回 None
    """
    # 首先尝试精确匹配
    if cmd_name in COMMAND_DETAILS:
        return COMMAND_DETAILS[cmd_name]
    
    # 如果是别名，映射到主命令
    if cmd_name in COMMAND_ALIASES:
        main_cmd = COMMAND_ALIASES[cmd_name]
        return COMMAND_DETAILS.get(main_cmd)
    
    # 尝试部分匹配（在命令名中查找）
    for key, details in COMMAND_DETAILS.items():
        if cmd_name in key or cmd_name in details["name"].lower():
            return details
    
    return None


def cmd_cwd(args: str, task: AgentTask, config: dict) -> bool:
    """显示或更改当前工作目录
    
    支持以下功能：
    - 无参数：显示当前工作目录的完整路径
    - <路径>: 切换到指定的目录（支持相对路径和绝对路径）
    
    Args:
        args: 目标目录路径（可选），为空时显示当前目录
        task: 当前代理任务对象
        config: 配置字典
        
    Returns:
        bool: 始终返回 True 表示命令执行完成
    """
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
    """列出所有可用的技能
    
    从多个常见项目目录中自动加载技能文件，包括：
    - .claude/skills/ - Claude 技能目录
    - .codex/skills/ - Codex 技能目录
    - .agents/skills/ - Agents 技能目录
    - skills/ - 通用技能目录
    
    技能按来源分组显示：内置技能、用户技能和项目技能。
    
    Args:
        _args: 未使用的参数
        task: 当前代理任务对象
        config: 配置字典
        
    Returns:
        bool: 始终返回 True 表示命令执行完成
    """
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
    """退出程序
    
    显示告别消息并终止程序运行。
    
    Args:
        _args: 未使用的参数
        task: 当前代理任务对象
        config: 配置字典
        
    Returns:
        bool: 此函数不会正常返回（会抛出 SystemExit 异常）
    """
    ok("再见！")
    raise SystemExit(0)


def cmd_usage(_args: str, task: AgentTask, config: dict) -> bool:
    """显示用量统计
    
    展示 Token 使用情况、API 调用次数等统计信息。
    
    Args:
        _args: 未使用的参数
        task: 当前代理任务对象
        config: 配置字典
        
    Returns:
        bool: 始终返回 True 表示命令执行完成
    """
    from utils.usage import format_stats
    info(format_stats())
    return True


def cmd_help(args: str, task: AgentTask, config: dict) -> bool:
    """显示所有可用的斜杠命令帮助信息
    
    支持以下功能：
    - 无参数：显示所有命令的分类概览
    - <命令名称>: 显示指定命令的详细说明，包括用法、功能描述、示例等
    
    Args:
        args: 可选的命令名称，用于查看特定命令的详细信息
        task: 当前代理任务对象
        config: 配置字典
        
    Returns:
        bool: 始终返回 True 表示命令执行完成
    """
    # 如果提供了命令名称，显示该命令的详细信息
    if args.strip():
        cmd_name = args.strip().lower()
        matched_command = _get_command_details(cmd_name)
        
        if matched_command:
            # 显示命令的详细信息
            info(f"\n📖 命令详情: {matched_command['name']}\n")
            info(f"分类: {matched_command['category']}")
            info(f"说明: {matched_command['description']}")
            info(f"用法: {matched_command['usage']}")
            info("")
            info("功能说明:")
            for detail in matched_command["details"]:
                info(f"  {detail}")
            info("")
            info("使用示例:")
            for example in matched_command["examples"]:
                info(f"  {example}")
            info("")
        else:
            warn(f"未找到命令: {args.strip()}")
            info("提示: 输入 /help 查看所有可用命令列表")
            info(f"提示: 输入 /help <命令名> 查看详细说明（如 /help model）")
            info("")
        return True
    
    # 无参数时显示所有命令的概览
    info("\n📖 UniClaw 斜杠命令帮助\n")
    
    info("【会话管理】")
    info("  /clear, /cls          - 清空当前对话历史并清屏")
    info("  /compact [关键词]      - 压缩上下文，优化 Token 使用")
    info("  /export [路径]         - 导出当前会话到文件（Markdown/JSON）")
    info("  /conversation list     - 列出所有历史对话")
    info("  /conversation load <ID> - 加载指定会话")
    info("  /conversation del <ID>  - 删除指定会话")
    info("  /conversation search <关键词> - 搜索对话内容")
    info("")
    
    info("【模型与系统】")
    info("  /model [名称]          - 查看或切换当前使用的模型")
    info("  /cwd, /cd, /pwd [路径] - 查看或切换工作目录")
    info("  /usage                 - 查看 Token 使用统计")
    info("  /context               - 查看当前上下文 token 构成")
    info("  /skills                - 列出所有可用技能")
    info("  /help [命令名]         - 显示帮助信息（可指定命令名查看详情）")
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
    info("  /schedule add <id> <调度> <动作> - 创建定时任务")
    info("  /schedule remove <id>  - 删除定时任务")
    info("  /schedule enable <id>  - 启用定时任务")
    info("  /schedule disable <id> - 禁用定时任务")
    info("")
    
    info("【权限管理】")
    info("  /permissions list      - 查看所有权限规则")
    info("  /permissions remove <类型> <模式> - 删除权限规则")
    info("")
    
    info("💡 提示:")
    info("  - 输入 /help <命令名> 可查看命令的详细说明（如 /help model）")
    info("  - 输入 ! 开头的命令可直接执行 Shell 命令（如 !ls -la）")
    info("  - 按 F2 键可切换详细/简洁显示模式")
    info("  - 按 ESC 键可中断正在运行的任务")
    info("  - 按 Ctrl+K 可聚焦对话侧边栏")
    info("")
    
    return True
