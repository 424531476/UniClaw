"""格式化工具函数模块

提供统一的参数格式化、文本显示等工具函数。
"""


def format_args_for_display(args: dict, max_length: int = 100) -> str:
    """格式化参数字典为显示字符串,处理多行和超长情况。

    Args:
        args: 参数字典
        max_length: 单个参数值的最大显示长度,默认 100 字符

    Returns:
        格式化后的参数字符串,单个参数值超过 max_length 字符时截断并添加"..."
    """
    if not args:
        return ""

    # 生成参数列表,对每个参数值进行处理
    formatted_args = []
    for k, v in args.items():
        # 将值转换为字符串
        v_str = str(v)

        # 标记是否需要添加省略号
        needs_ellipsis = False

        # 如果值包含换行符(多行),只取第一行并标记需要省略号
        if "\n" in v_str:
            v_str = v_str.split("\n")[0]
            needs_ellipsis = True

        # 检查长度是否超过指定最大长度
        if len(v_str) > max_length:
            v_str = v_str[:max_length]
            needs_ellipsis = True

        # 如果需要,添加省略号
        if needs_ellipsis:
            v_str += "..."

        formatted_args.append(f"{k}={v_str}")

    return ", \n".join(formatted_args)


def _format_tool_call(tool_call: dict) -> str:
    """格式化单个工具调用为显示字符串"""
    name = tool_call.get("name", "unknown")
    args = tool_call.get("args", {})
    if args:
        args_str = format_args_for_display(args)
        return f"{name}({args_str})"
    else:
        return f"{name}()"


def format_session_history(messages: list) -> list:
    """格式化对话历史消息为显示行列表
    
    Args:
        messages: 消息列表,支持用户、助手、工具三种角色的消息
        
    Returns:
        格式化后的显示行列表,包括分隔线和每条消息的格式化字符串
    """
    if not messages:
        return []
    
    lines = []
    lines.append("--- 对话历史内容 ---")
    
    for i, message in enumerate(messages):
        role = message.get("role", "unknown")
        
        if role == "user":
            content = message.get("content", "")
            if isinstance(content, list):
                # 处理多模态消息(包含文本和图片等)
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        text_parts.append(part)
                content = "\n".join(text_parts)
            
            # 简化长内容的显示
            display_content = content[:200] + "..." if len(content) > 200 else content
            lines.append(f"[{i+1}] USER: {display_content}")
            
        elif role == "assistant":
            content = message.get("content", "")
            display_content = content[:200] + "..." if len(content) > 200 else content
            lines.append(f"[{i+1}] ASSISTANT: {display_content}")
            
            # 显示工具调用信息
            tool_calls = message.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    tool_line = f"[{i+1}] TOOL_CALL: {_format_tool_call(tc)}"
                    lines.append(tool_line)
                    
        elif role == "tool":
            name = message.get("name", "unknown")
            content = message.get("content", "")
            display_content = content[:200] + "..." if len(content) > 200 else content
            lines.append(f"[{i+1}] TOOL_RESULT ({name}): {display_content}")
            
        else:
            content = message.get("content", "")
            display_content = content[:200] + "..." if len(content) > 200 else content
            lines.append(f"[{i+1}] {role.upper()}: {display_content}")
    
    lines.append("--- 对话历史结束 ---")
    return lines