"""格式化工具函数模块

提供统一的参数格式化、文本显示等工具函数。
"""
from uniclaw.utils.message import MessageRole, extract_text


def format_args_for_display(args: dict, max_length: int = 100, separator: str = ", ") -> str:
    """格式化参数字典为显示字符串,处理多行和超长情况。

    Args:
        args: 参数字典
        max_length: 单个参数值的最大显示长度,默认 100 字符
        separator: 参数之间的分隔符,默认 ", "

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

    return separator.join(formatted_args)

