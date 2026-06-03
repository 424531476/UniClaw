"""
会话管理工具

提供 AI 可直接调用的会话管理功能,包括查看会话列表、查看会话详情、删除会话等。
"""

from langchain_core.tools import tool
from tools.persistence import SessionPersistence, message2str, print_session_history
from console.ui import info, ok, err, warn


@tool
def session_list(
    limit: int = 20,
) -> str:
    """
    列出保存的会话历史,显示会话ID、标题、时间和消息数量等信息。

    Args:
        task_id: 可选,按任务ID筛选会话
        limit: 返回的最大会话数量,默认20

    Returns:
        str: 格式化的会话列表信息

    Examples:
        # 列出最近20个会话
        session_list()

        # 列出最近50个会话
        session_list(limit=50)
    """
    persistence = SessionPersistence()
    sessions = persistence.list_sessions(limit=limit)

    if not sessions:
        return "没有找到任何会话历史"

    lines = []
    lines.append(f"📋 会话列表（共 {len(sessions)} 个）：")
    lines.append("=" * 60)

    for idx, s in enumerate(sessions, 1):
        session_id = s.get("session_id", "unknown")
        title = s.get("title", "无标题")
        message_count = s.get("message_count", 0)
        start_time = s.get("start_time", "")
        end_time = s.get("end_time", "")

        lines.append(f"\n[{idx}] {title}")
        lines.append(f"    会话ID: {session_id}")
        lines.append(f"    消息数: {message_count}")
        if start_time:
            lines.append(f"    开始时间: {start_time}")
        if end_time:
            lines.append(f"    结束时间: {end_time}")

    lines.append("\n" + "=" * 60)
    lines.append("💡 使用 session_detail 查看详情,使用 session_delete 删除会话")

    return "\n".join(lines)


@tool
def session_detail(
    session_id: str,
) -> str:
    """
    查看指定会话的详细信息,包括完整的会话历史。

    Args:
        session_id: 会话ID(从 session_list 获取)

    Returns:
        str: 会话的详细信息

    Examples:
        # 查看指定会话详情
        session_detail(session_id="20260520_105455_a3f2b8c1-4d5e-6f7a-8b9c-0d1e2f3a4b5c")
    """
    persistence = SessionPersistence()
    session = persistence.load_session(session_id)

    if not session:
        return f"❌ 未找到会话ID为 '{session_id}' 的会话"

    lines = []
    lines.append(f"📝 会话详情：{session.get('title', '无标题')}")
    lines.append("=" * 60)

    # 基本信息
    lines.append(f"会话ID: {session_id}")
    lines.append(f"任务ID: {session.get('task_id', '')}")
    lines.append(f"任务名称: {session.get('task_name', '')}")
    lines.append(f"消息数量: {session.get('message_count', 0)}")
    lines.append(f"开始时间: {session.get('start_time', '')}")
    lines.append(f"结束时间: {session.get('end_time', '')}")
    lines.append(f"持续时间: {session.get('duration_seconds', 0)} 秒")

    # Token统计
    input_tokens = session.get('total_input_tokens', 0)
    output_tokens = session.get('total_output_tokens', 0)
    api_calls = session.get('api_calls', 0)
    lines.append(f"\nToken统计:")
    lines.append(f"  输入Token: {input_tokens}")
    lines.append(f"  输出Token: {output_tokens}")
    lines.append(f"  API调用: {api_calls}")

    # 会话历史
    messages = session.get("messages", [])
    if messages:
        lines.append("\n" + "=" * 60)
        lines.append("会话历史：")
        lines.append("=" * 60)

        # 使用现有的打印函数格式化输出
        lines.append(message2str(messages))

    return "\n".join(lines)


@tool
def session_delete(
    session_id: str,
) -> str:
    """
    删除指定的会话历史。

    ⚠️ 警告：此操作不可恢复,请谨慎使用。

    Args:
        session_id: 要删除的会话ID(从 session_list 获取)

    Returns:
        str: 删除操作结果

    Examples:
        # 删除指定会话
        session_delete(session_id="20260520_105455_a3f2b8c1-4d5e-6f7a-8b9c-0d1e2f3a4b5c")
    """
    persistence = SessionPersistence()

    # 先确认会话存在
    session = persistence.load_session(session_id)
    if not session:
        return f"❌ 未找到会话ID为 '{session_id}' 的会话"

    title = session.get("title", "无标题")

    # 执行删除
    success = persistence.delete_session(session_id)

    if success:
        ok(f"✓ 已删除会话: {title}")
        return f"✅ 成功删除会话 '{title}'\n会话ID: {session_id}"
    else:
        err(f"✗ 删除会话失败: {title}")
        return f"❌ 删除会话失败: {title}\n会话ID: {session_id}"


@tool
def session_update_title(
    session_id: str,
    title: str,
) -> str:
    """
    更新指定会话的标题。

    Args:
        session_id: 会话ID(从 session_list 获取)
        title: 新的标题

    Returns:
        str: 更新操作结果

    Examples:
        # 更新会话标题
        session_update_title(
            session_id="20260520_105455_a3f2b8c1-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
            title="新的会话标题"
        )
    """
    persistence = SessionPersistence()

    # 先确认会话存在
    session = persistence.load_session(session_id)
    if not session:
        return f"❌ 未找到会话ID为 '{session_id}' 的会话"

    old_title = session.get("title", "无标题")

    # 执行更新
    success = persistence.update_title(session_id, title)

    if success:
        ok(f"✓ 已更新会话标题: {old_title} -> {title}")
        return f"✅ 成功更新会话标题\n旧标题: {old_title}\n新标题: {title}\n会话ID: {session_id}"
    else:
        err(f"✗ 更新会话标题失败: {session_id}")
        return f"❌ 更新会话标题失败\n会话ID: {session_id}"


def get_tools() -> list:
    """获取会话管理工具列表"""
    return [
        session_list,
        session_detail,
        session_delete,
        session_update_title,
    ]


def get_all_tools() -> list:
    """获取所有会话管理工具（与 get_tools 相同）"""
    return get_tools()
