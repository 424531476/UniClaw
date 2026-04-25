def truncate_text(text: str, max_chars: int = 10000, keep_ratio: float = 0.8) -> str:
    """
    对过长的文本内容进行截断操作

    保留文本的前面和后面部分，在中间显示被截断的字符数信息。

    Args:
        text (str): 需要截断的原始文本内容
        max_chars (int): 最大允许字符数，默认为10000字符
        keep_ratio (float): 保留比例，前后部分各占此值的一半。默认为0.8（即前面40%，后面40%，总共80%）

    Returns:
        str: 截断后的文本，格式为"前面部分...[截断了X个字符]...后面部分"
             如果文本未超过max_chars，则返回原文本
    """
    if not text:
        return text

    total_chars = len(text)

    # 如果文本长度未超过限制，直接返回原文本
    if total_chars <= max_chars:
        return text

    # 计算前后部分各自应该保留的字符数
    keep_chars_per_part = int(max_chars * keep_ratio / 2)

    # 获取前面部分
    front_text = text[:keep_chars_per_part]

    # 获取后面部分
    back_text = text[-keep_chars_per_part:]

    # 计算被截断的字符数
    truncated_chars = total_chars - len(front_text) - len(back_text)

    # 构建截断提示信息
    truncation_info = f"...[截断了{truncated_chars}个字符]..."

    # 组合最终结果
    result = f"{front_text}{truncation_info}{back_text}"

    return result


def truncate_text_by_lines(text: str, max_chars: int = 10000, keep_ratio: float = 0.8) -> str:
    """
    对过长的文本内容按字符数进行截断操作

    当文本超过最大字符数限制时，保留前面和后面的完整行，在中间显示被截断的行数和字符数信息。
    截断点始终在行边界处，不会截断到一行的中间。

    Args:
        text (str): 需要截断的原始文本内容
        max_chars (int): 最大允许字符数，默认为10000个字符
        keep_ratio (float): 保留比例，前后部分各占此值的一半。默认为0.8（即前面40%，后面40%，总共80%）

    Returns:
        str: 截断后的文本，格式为"前面部分行...[截断了X行，Y个字符]...后面部分行"
             如果文本字符数未超过max_chars，则返回原文本
    """
    if not text:
        return text

    total_chars = len(text)

    # 如果文本字符数未超过限制，直接返回原文本
    if total_chars <= max_chars:
        return text

    # 按行分割文本
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    # 计算前后部分各自应该保留的字符数
    keep_chars_per_part = int(max_chars * keep_ratio / 2)

    # 从前向后累加行，直到接近目标字符数
    front_chars = 0
    front_line_count = 0
    for i, line in enumerate(lines):
        line_len = len(line)
        if front_chars + line_len > keep_chars_per_part and front_line_count > 0:
            break
        front_chars += line_len
        front_line_count += 1

    # 从后向前累加行，直到接近目标字符数
    back_chars = 0
    back_line_count = 0
    for i in range(total_lines - 1, -1, -1):
        line_len = len(lines[i])
        if back_chars + line_len > keep_chars_per_part and back_line_count > 0:
            break
        back_chars += line_len
        back_line_count += 1

    # 获取前面部分的行
    front_lines = lines[:front_line_count]

    # 获取后面部分的行
    back_lines = lines[-back_line_count:] if back_line_count > 0 else []

    # 计算被截断的行数和字符数
    truncated_lines = total_lines - front_line_count - back_line_count
    truncated_chars = total_chars - front_chars - back_chars

    # 构建截断提示信息
    truncation_info = f"\n...[截断了{truncated_lines}行，{truncated_chars}个字符]...\n"

    # 组合最终结果
    result = "".join(front_lines).rstrip() + truncation_info + "".join(back_lines)

    return result
