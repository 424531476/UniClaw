import math
from llm import chat
from agent import AgentState


def _count_str_chars(obj) -> int:
    """递归计算嵌套结构中所有字符串值的总字符数。

    该函数会遍历传入的嵌套数据结构（包括字典、列表和字符串），
    统计其中所有字符串类型值的字符总数。对于非字符串类型的值，
    函数会递归处理其子元素。

    Args:
        obj: 需要统计字符数的对象，可以是字符串、字典、列表或其他类型。
            - 如果是字符串，直接返回其长度
            - 如果是字典，递归统计所有值的字符数
            - 如果是列表，递归统计所有元素的字符数
            - 其他类型返回0

    Returns:
        int: 嵌套结构中所有字符串值的总字符数。如果输入不是字符串、
             字典或列表，则返回0。
    """
    if isinstance(obj, str):
        return len(obj)
    if isinstance(obj, dict):
        return sum(_count_str_chars(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_str_chars(item) for item in obj)
    return 0


def estimate_tokens(messages: list) -> int:
    """估算令牌数量。使用字符数/2.8（针对代码密集型内容的保守估计）。

    旧的字符数/3.5除数低估了代码密集型对话的实际令牌数量，因为：
    (1) 代码令牌每个约2.5-3个字符，而不是3.5个；
    (2) 工具模式、JSON键和特殊字符比纯文本占用更多令牌；
    (3) 每条消息的框架开销（约4个令牌/消息）未被计入。
    这导致压缩在应该触发时被跳过，进而引发上下文溢出崩溃。

    Args:
        messages: 包含"content"字段的消息字典列表（字符串或字典列表）
    Returns:
        近似令牌数量，整数类型
    """
    total_chars = 0
    msg_count = 0
    for m in messages:
        msg_count += 1
        content = m.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    for v in block.values():
                        if isinstance(v, str):
                            total_chars += len(v)
        for tc in m.get("tool_calls", []):
            # 递归计算所有字符串值，包括嵌套的输入字典
            # （例如：{"id": "c1", "name": "Bash", "input": {"command": "..."}}）
            total_chars += _count_str_chars(tc)
    # 内容令牌：字符数/2.8 + 框架令牌：每条消息4个令牌 + 10%缓冲
    content_tokens = int(total_chars / 2.8)
    framing_tokens = msg_count * 4
    return int((content_tokens + framing_tokens) * 1.1)


def get_context_limit(model: str = None):
    return 128000


def snip_old_tool_results(
    messages: list,
    max_chars: int = 2000,
    preserve_last_n_turns: int = 6,
) -> list:
    """截断距离末尾超过preserve_last_n_turns条的旧工具角色消息。

    对于内容长度超过max_chars的旧工具消息，保留前半部分和最后四分之一，
    在中间插入'[... N chars snipped ...]'标记。
    原地修改并返回同一个列表。

    Args:
        messages: 消息字典列表（原地修改）
        max_chars: 截断前的最大字符长度
        preserve_last_n_turns: 从末尾开始保留的消息数量
    Returns:
        同一个消息列表（已原地修改）
    """
    # 计算需要处理的旧消息的截止索引，保留最后preserve_last_n_turns条消息不处理
    cutoff = max(0, len(messages) - preserve_last_n_turns)

    # 遍历所有需要处理的旧消息
    for i in range(cutoff):
        m = messages[i]
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        if not isinstance(content, str) or len(content) <= max_chars:
            continue

        # 对超长内容进行截断：保留前半部分和最后四分之一，中间用省略标记替换
        first_half = content[: max_chars // 2]
        last_quarter = content[-(max_chars // 4) :]
        snipped = len(content) - len(first_half) - len(last_quarter)
        m["content"] = f"{first_half}\n[... {snipped} 个字符已省略 ...]\n{last_quarter}"
    return messages


def find_split_point(messages: list, keep_ratio: float = 0.3) -> int:
    """查找分割点，使得最近部分的消息约占总token数的keep_ratio比例。

    从消息列表末尾向前遍历，累加token估算值，返回当最近部分的token数达到总token数
    约keep_ratio比例时的索引位置。

    Args:
        messages: 消息字典列表
        keep_ratio: 在最近部分中保留的token比例（0.0-1.0）
    Returns:
        分割索引（messages[:idx]为旧消息，messages[idx:]为新消息）
    """
    # 处理空消息列表的边界情况
    if not messages:
        return 0

    # 确保keep_ratio在有效范围[0.0, 1.0]内
    keep_ratio = max(0.0, min(1.0, keep_ratio))

    # 计算总token数和需要保留的目标token数
    total = estimate_tokens(messages)
    target = int(total * keep_ratio)

    # 从后往前遍历消息，累加token数，找到分割点
    running = 0
    for i in range(len(messages) - 1, -1, -1):
        running += estimate_tokens([messages[i]])
        if running >= target:
            return i

    # 如果所有消息的token数都未达到目标，返回起始位置
    return 0


def compact_messages(messages: list, config: dict, focus: str = "") -> list:
    """通过LLM调用将旧消息压缩为摘要。

    在find_split_point处分割，对旧部分进行摘要，返回
    [摘要消息, 确认消息, *最近消息]。

    参数:
        messages: 完整消息列表
        config: 代理配置字典（必须包含"model_name"）
        focus: 可选的聚焦指令，用于指导摘要生成
    返回:
        新的压缩后消息列表
    """
    # 查找消息分割点，确定需要压缩的历史消息范围
    split = find_split_point(messages)
    if split <= 0:
        return messages

    # 将消息分为旧消息（需要压缩）和最近消息（保留原样）
    old = messages[:split]
    recent = messages[split:]

    # 构建旧消息的文本表示，用于生成摘要
    old_text = ""
    for m in old:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            old_text += f"[{role}]: {content}\n"
        elif isinstance(content, list):
            old_text += f"[{role}]: {content}\n"

    # 构建摘要提示词，包含核心指令和可选的聚焦方向
    summary_prompt = (
        "请简洁地总结以下对话历史。"
        "保留关键决策、文件路径、工具结果以及继续对话所需的上下文信息。"
    )
    if focus:
        summary_prompt += f"\n\n特别关注：{focus}"
    summary_prompt += "\n\n" + old_text

    # 调用LLM生成对话历史摘要
    messages = [
        {"role": "system", "content": "你是一个简洁的摘要生成器。"},
        {"role": "user", "content": summary_prompt},
    ]
    resp = chat(messages, config["model_name"])
    summary_text = resp.content

    # 构造压缩后的消息列表：摘要消息 + 确认消息 + 最近消息
    summary_msg = {
        "role": "user",
        "content": f"[之前的对话摘要]\n{summary_text}",
    }
    ack_msg = {
        "role": "assistant",
        "content": "明白了。我已经了解了之前对话的上下文。让我们继续。",
    }
    return [summary_msg, ack_msg, *recent]


def maybe_compact(state: AgentState, config: dict):
    """
    根据上下文长度阈值判断是否需要执行消息压缩。

    该函数采用两层压缩策略：
    1. 首先尝试裁剪旧的工具调用结果（轻量级操作）
    2. 如果仍超出阈值，则执行完整的消息自动压缩（重量级操作）

    Args:
        state (AgentState): 代理状态对象，包含需要检查的消息列表
        config (dict): 配置字典，用于控制压缩行为的参数

    Returns:
        bool: 如果执行了任何压缩操作返回 True，否则返回 False
              - False: 消息总长度未超过阈值，无需压缩
              - True: 执行了裁剪工具结果或完整消息压缩
    """
    limit = get_context_limit()
    threshold = limit * 0.7

    if estimate_tokens(state.messages) <= threshold:
        return False

    # 第一层压缩：裁剪旧的工具调用结果
    snip_old_tool_results(state.messages)

    if estimate_tokens(state.messages) <= threshold:
        return True

    # 第二层压缩：执行完整的消息自动压缩
    state.messages = compact_messages(state.messages, config)
    return True
