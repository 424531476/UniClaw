"""
对话管理工具

提供 AI 可直接调用的对话管理功能，包括查看对话列表、查看对话详情、删除对话等。
"""

from langchain_core.tools import tool
from tools.persistence import ConversationPersistence, message2str, print_conversation_history
from console.ui import info, ok, err, warn


@tool
def conversation_list(
    limit: int = 20,
) -> str:
    """
    列出保存的对话历史,显示会话ID、标题、时间和消息数量等信息。

    Args:
        task_id: 可选,按任务ID筛选对话
        limit: 返回的最大对话数量,默认20

    Returns:
        str: 格式化的对话列表信息

    Examples:
        # 列出最近20个对话
        conversation_list()

        # 列出最近50个对话
        conversation_list(limit=50)
    """
    persistence = ConversationPersistence()
    conversations = persistence.list_conversations(limit=limit)

    if not conversations:
        return "没有找到任何对话历史"

    lines = []
    lines.append(f"📋 对话列表（共 {len(conversations)} 个）：")
    lines.append("=" * 60)

    for idx, conv in enumerate(conversations, 1):
        session_id = conv.get("session_id", "unknown")
        title = conv.get("title", "无标题")
        message_count = conv.get("message_count", 0)
        start_time = conv.get("start_time", "")
        end_time = conv.get("end_time", "")

        lines.append(f"\n[{idx}] {title}")
        lines.append(f"    会话ID: {session_id}")
        lines.append(f"    消息数: {message_count}")
        if start_time:
            lines.append(f"    开始时间: {start_time}")
        if end_time:
            lines.append(f"    结束时间: {end_time}")

    lines.append("\n" + "=" * 60)
    lines.append("💡 使用 conversation_detail 查看详情，使用 conversation_delete 删除对话")

    return "\n".join(lines)


@tool
def conversation_detail(
    session_id: str,
) -> str:
    """
    查看指定对话的详细信息，包括完整的对话历史。

    Args:
        session_id: 会话ID(从 conversation_list 获取)

    Returns:
        str: 对话的详细信息

    Examples:
        # 查看指定对话详情
        conversation_detail(session_id="20260520_105455_a3f2b8c1-4d5e-6f7a-8b9c-0d1e2f3a4b5c")
    """
    persistence = ConversationPersistence()
    conversation = persistence.load_conversation(session_id)

    if not conversation:
        return f"❌ 未找到会话ID为 '{session_id}' 的对话"

    lines = []
    lines.append(f"📝 对话详情：{conversation.get('title', '无标题')}")
    lines.append("=" * 60)

    # 基本信息
    lines.append(f"会话ID: {session_id}")
    lines.append(f"任务ID: {conversation.get('task_id', '')}")
    lines.append(f"任务名称: {conversation.get('task_name', '')}")
    lines.append(f"消息数量: {conversation.get('message_count', 0)}")
    lines.append(f"开始时间: {conversation.get('start_time', '')}")
    lines.append(f"结束时间: {conversation.get('end_time', '')}")
    lines.append(f"持续时间: {conversation.get('duration_seconds', 0)} 秒")

    # Token统计
    input_tokens = conversation.get('total_input_tokens', 0)
    output_tokens = conversation.get('total_output_tokens', 0)
    api_calls = conversation.get('api_calls', 0)
    lines.append(f"\nToken统计:")
    lines.append(f"  输入Token: {input_tokens}")
    lines.append(f"  输出Token: {output_tokens}")
    lines.append(f"  API调用: {api_calls}")

    # 对话历史
    messages = conversation.get("messages", [])
    if messages:
        lines.append("\n" + "=" * 60)
        lines.append("对话历史：")
        lines.append("=" * 60)
        
        # 使用现有的打印函数格式化输出
        lines.append(message2str(messages))

    return "\n".join(lines)


@tool
def conversation_delete(
    session_id: str,
) -> str:
    """
    删除指定的对话历史。

    ⚠️ 警告：此操作不可恢复，请谨慎使用。

    Args:
        session_id: 要删除的会话ID(从 conversation_list 获取)

    Returns:
        str: 删除操作结果

    Examples:
        # 删除指定对话
        conversation_delete(session_id="20260520_105455_a3f2b8c1-4d5e-6f7a-8b9c-0d1e2f3a4b5c")
    """
    persistence = ConversationPersistence()
    
    # 先确认对话存在
    conversation = persistence.load_conversation(session_id)
    if not conversation:
        return f"❌ 未找到会话ID为 '{session_id}' 的对话"

    title = conversation.get("title", "无标题")
    
    # 执行删除
    success = persistence.delete_conversation(session_id)

    if success:
        ok(f"✓ 已删除对话: {title}")
        return f"✅ 成功删除对话 '{title}'\n会话ID: {session_id}"
    else:
        err(f"✗ 删除对话失败: {title}")
        return f"❌ 删除对话失败: {title}\n会话ID: {session_id}"


@tool
def conversation_update_title(
    session_id: str,
    title: str,
) -> str:
    """
    更新指定对话的标题。

    Args:
        session_id: 会话ID(从 conversation_list 获取)
        title: 新的标题

    Returns:
        str: 更新操作结果

    Examples:
        # 更新对话标题
        conversation_update_title(
            session_id="20260520_105455_a3f2b8c1-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
            title="新的对话标题"
        )
    """
    persistence = ConversationPersistence()
    
    # 先确认对话存在
    conversation = persistence.load_conversation(session_id)
    if not conversation:
        return f"❌ 未找到会话ID为 '{session_id}' 的对话"

    old_title = conversation.get("title", "无标题")
    
    # 执行更新
    success = persistence.update_title(session_id, title)

    if success:
        ok(f"✓ 已更新对话标题: {old_title} -> {title}")
        return f"✅ 成功更新对话标题\n旧标题: {old_title}\n新标题: {title}\n会话ID: {session_id}"
    else:
        err(f"✗ 更新对话标题失败: {session_id}")
        return f"❌ 更新对话标题失败\n会话ID: {session_id}"


def get_tools() -> list:
    """获取对话管理工具列表"""
    return [
        conversation_list,
        conversation_detail,
        conversation_delete,
        conversation_update_title,
    ]


def get_all_tools() -> list:
    """获取所有对话管理工具（与 get_tools 相同）"""
    return get_tools()
