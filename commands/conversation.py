from agent import AgentTask
from console.ui import clear, err, info, ok, warn
from tools.persistence import ConversationPersistence, print_conversation_history


def _format_item(index: int, item: dict) -> str:
    """格式化对话历史条目为可读字符串

    Args:
        index: 条目的序号(从1开始)
        item: 对话元数据字典,包含session_id、title、时间戳等信息

    Returns:
        str: 格式化的对话信息字符串,包含标题、时间、消息数和会话ID
    """
    title = item.get("title") or "[无标题]"
    return (
        f"{index}. [{item.get('session_id', '')}] {title}\n"
        f"   时间: {item.get('end_time') or item.get('start_time', '')} | "
        f"消息: {item.get('message_count', 0)} 条\n"
        f"   ID: {item.get('session_id', '')}"
    )


def cmd_conversation(args: str, task: AgentTask, config: dict) -> bool:
    """管理持久化对话历史

    支持以下子命令：
    - list/ls: 列出所有对话历史(默认命令),支持按任务ID过滤
    - load <session_id>: 加载指定会话到当前上下文
    - del/delete/rm <session_id>: 删除指定会话（需要确认）
    - search <keyword>: 搜索包含关键词的对话内容

    Args:
        args: 命令参数，格式为 "<子命令> [参数]"
        task: 当前代理任务对象，用于访问和修改消息历史
        config: 配置字典，包含系统配置信息

    Returns:
        bool: 始终返回 True 表示命令执行完成
    """
    parts = args.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""
    persistence = ConversationPersistence()

    if subcmd in {"list", "ls", ""}:
        # 列出对话历史
        items = persistence.list_conversations(limit=50)
        if not items:
            warn("没有找到对话历史")
            return True
        info(f"共 {len(items)} 条对话历史:")
        for idx, item in enumerate(items, 1):
            info(_format_item(idx, item))
        return True

    if subcmd == "load":
        # 加载指定会话到当前上下文
        session_id = rest.strip()
        if not session_id:
            err("用法: /conversation load <session_id>")
            return True
        data = persistence.load_conversation(session_id)
        if not data:
            err(f"未找到会话: {session_id}")
            return True
        task.messages = data.get("messages", [])
        task.name = data.get("task_name") or task.name
        setattr(task, "conversation_session_id", session_id)
        start_time = data.get("start_time")
        if start_time:
            setattr(task, "conversation_start_time", start_time)
        clear()
        ok(f"✓ 已加载对话: {data.get('title') or '[无标题]'}")
        info(f"消息数: {len(task.messages)}")
        info(
            f"Token: {data.get('total_input_tokens', 0)} → "
            f"{data.get('total_output_tokens', 0)}"
        )
        # 打印历史对话内容
        print_conversation_history(task.messages)
        return True

    if subcmd in {"del", "delete", "rm"}:
        # 删除指定会话
        session_id = rest.strip()
        if not session_id:
            err("用法: /conversation del <session_id>")
            return True
        answer = ""
        try:
            from console.run import TUIApp

            tui = TUIApp.get_instance()
            if tui:
                answer = tui.tui_input(
                    f"确定要删除会话 {session_id}?(y/n):", title="删除对话"
                )
            else:
                answer = input(f"确定要删除会话 {session_id}?(y/n): ")
        except Exception:
            answer = ""
        if answer.strip().lower() != "y":
            warn("已取消删除")
            return True
        if persistence.delete_conversation(session_id):
            ok(f"✓ 已删除会话: {session_id}")
        else:
            err(f"删除失败或未找到会话: {session_id}")
        return True

    if subcmd == "search":
        # 搜索包含关键词的对话内容
        keyword = rest.strip()
        if not keyword:
            err("用法: /conversation search <keyword-or-regex>")
            return True
        try:
            results = persistence.search_conversations(keyword)
        except Exception as exc:
            err(f"搜索失败: {exc}")
            return True
        if not results:
            warn(f"未找到包含 {keyword!r} 的对话")
            return True
        info(f"找到 {len(results)} 条包含 {keyword!r} 的对话:")
        for idx, item in enumerate(results, 1):
            info(_format_item(idx, item))
            info("   匹配位置: " + "、".join(f"消息{i}" for i in item["matches"]))
        return True

    err("用法: /conversation [list|load|del|search] ...")
    return True
