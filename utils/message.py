"""消息工具函数

从对话消息中提取和构建上下文摘要等通用功能。
"""


def build_context_summary(
    messages: list,
    max_messages: int = 0,
    max_chars: int = 0,
    roles: tuple = ("user", "assistant"),
) -> str:
    """从对话消息中提取最近消息作为上下文摘要。

    Args:
        messages: 消息列表,每条为 {"role": str, "content": str|list}
        max_messages: 最多取几条消息,0 表示全部
        max_chars: 摘要总字符上限,0 表示不限制
        roles: 要提取的角色,默认只取 user 和 assistant

    Returns:
        格式化的上下文文本,每行 "[role]: content"
    """
    if not messages:
        return ""

    # 过滤目标角色
    filtered = []
    for msg in messages:
        if msg.get("role") not in roles:
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            # 多模态消息,只取文本部分
            content = " ".join(
                b.get("text", "") for b in content if b.get("type") == "text"
            )
        if content and content.strip():
            filtered.append((msg["role"], content.strip()))

    if not filtered:
        return ""

    # 截取最近 N 条
    if max_messages > 0:
        filtered = filtered[-max_messages:]

    # 截断到总字符上限
    if max_chars > 0:
        lines = []
        total = 0
        for role, content in filtered:
            if total + len(content) > max_chars:
                remaining = max_chars - total
                if remaining > 50:
                    content = content[:remaining] + "..."
                else:
                    break
            lines.append(f"[{role}]: {content}")
            total += len(content)
        return "\n".join(lines)

    return "\n".join(f"[{role}]: {content}" for role, content in filtered)
