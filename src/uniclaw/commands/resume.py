"""会话恢复与管理命令"""

from uniclaw.agent import AgentTask
from uniclaw.config import AppConfig
from uniclaw.console.ui import err, info, warn
from uniclaw.tools.session.session import Session
from uniclaw.tools.session.session_manager import SessionManager
from uniclaw.utils.message import MessageRole

# 子命令列表
SUBCOMMANDS = ["list", "del", "search", "fork"]


def _format_item(index: int, item: dict) -> str:
    """格式化会话条目"""
    title = item.get("title") or "[无标题]"
    time = item.get("end_time") or item.get("start_time", "")
    msg_count = item.get("message_count", 0)
    sid = item.get("session_id", "")
    return f"  {index}. {title}  |  {time}  |  {msg_count} 条消息  |  {sid}"


async def cmd_resume(args: str, config: AppConfig) -> bool:
    """恢复和管理会话

    - 无参数:列出最近 10 个会话供选择
    - <session_id>:恢复指定会话
    - list:列出所有会话
    - del <session_id>:删除指定会话
    - search <keyword>:搜索会话内容
    """
    task = config.current_agent

    parts = args.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    # /resume list — 列出所有会话
    if subcmd == "list":
        items = SessionManager.list_sessions(limit=50)
        if not items:
            warn("没有可恢复的会话", config)
            return True
        info(f"\n可恢复的会话 (共 {len(items)} 个):\n", config)
        for idx, item in enumerate(items, 1):
            info(_format_item(idx, item), config)
        info("\n用法: /resume <session_id>", config)
        return True

    # /resume del <session_id> — 删除会话
    if subcmd in ("del", "delete", "rm"):
        session_id = rest.strip()
        if not session_id:
            err("用法: /resume del <session_id>", config)
            return True
        answer = ""
        try:
            from uniclaw.console.run import TUIApp

            tui = TUIApp.get_instance()
            if tui:
                answer = await tui.tui_input(
                    f"确定要删除会话 {session_id}?(y/n):", title="删除对话"
                )
            else:
                answer = input(f"确定要删除会话 {session_id}?(y/n): ")
        except Exception:
            answer = ""
        if answer.strip().lower() != "y":
            warn("已取消删除", config)
            return True
        if SessionManager.delete_session(session_id):
            warn(f"已删除会话: {session_id}", config)
        else:
            err(f"删除失败或未找到会话: {session_id}", config)
        return True

    # /resume search <keyword> — 搜索会话
    if subcmd == "search":
        keyword = rest.strip()
        if not keyword:
            err("用法: /resume search <keyword>", config)
            return True
        try:
            results = SessionManager.search_sessions(keyword)
        except Exception as exc:
            err(f"搜索失败: {exc}", config)
            return True
        if not results:
            warn(f"未找到包含 {keyword!r} 的对话", config)
            return True
        info(f"找到 {len(results)} 条包含 {keyword!r} 的对话:\n", config)
        for idx, item in enumerate(results, 1):
            info(_format_item(idx, item), config)
            info(
                "   匹配位置: " + "、".join(f"消息{i}" for i in item["matches"]), config
            )
        return True

    # /resume fork [session_id] [message_idx] — 会话分叉
    if subcmd == "fork":
        await _handle_fork(rest.strip(), task, config)
        return True

    # /resume <session_id> — 恢复指定会话
    if subcmd:
        session = SessionManager.load_session(subcmd)
        if not session:
            err(f"未找到会话: {subcmd}", config)
            return True
        _restore_session(session, task)
        return True

    # /resume — 无参数,列出最近会话供选择
    items = SessionManager.list_sessions(limit=10)
    if not items:
        warn("没有可恢复的会话", config)
        return True

    lines = ["最近会话:\n"]
    for idx, item in enumerate(items, 1):
        lines.append(_format_item(idx, item))
    lines.append("\n输入序号或 session_id 恢复(直接回车取消):")
    prompt_text = "\n".join(lines)

    try:
        from uniclaw.console.run import TUIApp

        tui = TUIApp.get_instance()
        if tui:
            choice = await tui.tui_input(prompt_text, title="恢复会话")
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
            session = SessionManager.load_session(session_id)
            if session:
                _restore_session(session, task)
                return True
        err(f"无效序号: {choice}", config)
        return True

    # 按 session_id 恢复
    session = SessionManager.load_session(choice)
    if not session:
        err(f"未找到会话: {choice}", config)
        return True
    _restore_session(session, task)
    return True


def _restore_session(session: Session, task: AgentTask):
    """将已加载的会话恢复到当前 task,像正常对话一样继续。
    data 可以是 Session 对象或 dict。
    """
    task.session = session

    # 用 TUI 的事件渲染系统显示历史消息
    try:
        from uniclaw.console.run import TUIApp

        tui = TUIApp.get_instance()
        if tui:
            tui.clear()
            tui.replay_messages(task.session.to_openai_messages())
    except Exception:
        pass


async def _handle_fork(args: str, task: AgentTask, config: AppConfig):
    """处理 /resume fork 子命令

    用法:
        /resume fork                    — 分叉当前会话,选择分叉点
        /resume fork <idx>              — 分叉当前会话到第 idx 条消息
        /resume fork <session_id>       — 分叉历史会话,选择分叉点
        /resume fork <session_id> <idx> — 分叉历史会话到第 idx 条消息
    """
    parts = args.split() if args else []
    session_id = None
    message_idx = None

    if len(parts) == 0:
        # 无参数:当前会话,选分叉点
        session_id = task.session.id
    elif len(parts) == 1:
        arg = parts[0]
        if arg.isdigit():
            # 只有数字:当前会话 + 指定分叉点
            session_id = task.session.id
            message_idx = int(arg)
        else:
            # 只有 session_id:选分叉点
            session_id = arg
    else:
        # 两个参数:session_id + message_idx
        session_id = parts[0]
        if parts[1].isdigit():
            message_idx = int(parts[1])
        else:
            err(
                f"无效的消息序号: {parts[1]},用法: /resume fork <session_id> <序号>",
                config,
            )
            return

    # 加载会话
    session = SessionManager.load_session(session_id)
    if not session:
        err(f"未找到会话: {session_id}", config)
        return

    if len(session) == 0:
        err("会话没有消息,无法分叉", config)
        return

    # 如果没指定分叉点,显示消息选择器
    if message_idx is None:
        message_idx = await _pick_fork_point(session, config)
        if message_idx is None:
            return

    # 执行分叉
    forked = await SessionManager.fork_session(session_id, message_idx, config)
    if not forked:
        err(f"分叉失败: 无效的消息序号 {message_idx}(共 {len(session)} 条消息)", config)
        return

    _restore_session(forked, task)
    info(f"已从会话 {session_id} 的第 {message_idx + 1} 条消息处分叉", config)
    info(f"新会话: {forked.id}", config)


async def _pick_fork_point(session: Session, config: AppConfig) -> int | None:
    """显示消息列表,让用户选择分叉点"""
    lines = ["会话消息:\n"]
    for idx, msg in enumerate(session):
        role = msg.role
        # 简化内容显示
        text = msg.to_content().replace("\n", " ").strip()[:60]
        if not text:
            text = "(无文本内容)"
        lines.append(f"  {idx + 1}. [{role}] {text}")

    lines.append(f"\n输入分叉点序号 (1-{len(session)}),直接回车取消:")

    try:
        from uniclaw.console.run import TUIApp

        tui = TUIApp.get_instance()
        if tui:
            choice = await tui.tui_input("\n".join(lines), title="选择分叉点")
        else:
            print("\n".join(lines))
            choice = input()
    except Exception:
        choice = ""

    choice = choice.strip()
    if not choice:
        return None
    if not choice.isdigit():
        err(f"无效输入: {choice},请输入数字序号", config)
        return None

    idx = int(choice) - 1
    if idx < 0 or idx >= len(session):
        err(f"序号超出范围: {choice}(共 {len(session)} 条消息)", config)
        return None
    return idx
