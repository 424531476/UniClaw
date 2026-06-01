"""会话恢复与管理命令"""

from agent import AgentTask
from console.ui import err, info, warn
from tools.persistence import ConversationPersistence


def _format_item(index: int, item: dict) -> str:
    """格式化会话条目"""
    title = item.get("title") or "[无标题]"
    time = item.get("end_time") or item.get("start_time", "")
    msg_count = item.get("message_count", 0)
    sid = item.get("session_id", "")
    return f"  {index}. {title}  |  {time}  |  {msg_count} 条消息  |  {sid}"


def cmd_resume(args: str, task: AgentTask, config: dict) -> bool:
    """恢复和管理会话

    - 无参数：列出最近 10 个会话供选择
    - <session_id>：恢复指定会话
    - list：列出所有会话
    - del <session_id>：删除指定会话
    - search <keyword>：搜索会话内容
    """
    persistence = ConversationPersistence()
    parts = args.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    # /resume list — 列出所有会话
    if subcmd == "list":
        items = persistence.list_conversations(limit=50)
        if not items:
            warn("没有可恢复的会话")
            return True
        info(f"\n可恢复的会话 (共 {len(items)} 个):\n")
        for idx, item in enumerate(items, 1):
            info(_format_item(idx, item))
        info("\n用法: /resume <session_id>")
        return True

    # /resume del <session_id> — 删除会话
    if subcmd in ("del", "delete", "rm"):
        session_id = rest.strip()
        if not session_id:
            err("用法: /resume del <session_id>")
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
            warn(f"已删除会话: {session_id}")
        else:
            err(f"删除失败或未找到会话: {session_id}")
        return True

    # /resume search <keyword> — 搜索会话
    if subcmd == "search":
        keyword = rest.strip()
        if not keyword:
            err("用法: /resume search <keyword>")
            return True
        try:
            results = persistence.search_conversations(keyword)
        except Exception as exc:
            err(f"搜索失败: {exc}")
            return True
        if not results:
            warn(f"未找到包含 {keyword!r} 的对话")
            return True
        info(f"找到 {len(results)} 条包含 {keyword!r} 的对话:\n")
        for idx, item in enumerate(results, 1):
            info(_format_item(idx, item))
            info("   匹配位置: " + "、".join(f"消息{i}" for i in item["matches"]))
        return True

    # /resume <session_id> — 恢复指定会话
    if subcmd:
        data = persistence.load_conversation(subcmd)
        if not data:
            err(f"未找到会话: {subcmd}")
            return True
        _restore_session(data, task)
        return True

    # /resume — 无参数，列出最近会话供选择
    items = persistence.list_conversations(limit=10)
    if not items:
        warn("没有可恢复的会话")
        return True

    lines = ["最近会话:\n"]
    for idx, item in enumerate(items, 1):
        lines.append(_format_item(idx, item))
    lines.append("\n输入序号或 session_id 恢复（直接回车取消）:")
    prompt_text = "\n".join(lines)

    try:
        from console.run import TUIApp

        tui = TUIApp.get_instance()
        if tui:
            choice = tui.tui_input(prompt_text, title="恢复会话")
        else:
            print(prompt_text)
            choice = input()
    except Exception:
        choice = ""

    choice = choice.strip()
    if not choice:
        return True

    # 按序号选择
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            session_id = items[idx]["session_id"]
            data = persistence.load_conversation(session_id)
            if data:
                _restore_session(data, task)
                return True
        err(f"无效序号: {choice}")
        return True

    # 按 session_id 恢复
    data = persistence.load_conversation(choice)
    if not data:
        err(f"未找到会话: {choice}")
        return True
    _restore_session(data, task)
    return True


def _restore_session(data: dict, task: AgentTask):
    """将已加载的会话数据恢复到当前 task，像正常对话一样继续"""
    task.messages = data.get("messages", [])
    task.name = data.get("task_name") or task.name
    session_id = data.get("session_id", "")
    setattr(task, "conversation_session_id", session_id)
    start_time = data.get("start_time")
    if start_time:
        setattr(task, "conversation_start_time", start_time)

    # 用 TUI 的事件渲染系统显示历史消息
    try:
        from console.run import TUIApp

        tui = TUIApp.get_instance()
        if tui:
            tui.clear()
            tui.replay_messages(task.messages)
    except Exception:
        pass
