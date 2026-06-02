import math
from llm import chat


def _count_str_chars(obj) -> int:
    """递归计算嵌套结构中所有字符串值的总字符数。

    该函数会遍历传入的嵌套数据结构(包括字典、列表和字符串),
    统计其中所有字符串类型值的字符总数。对于非字符串类型的值,
    函数会递归处理其子元素。

    Args:
        obj: 需要统计字符数的对象,可以是字符串、字典、列表或其他类型。
            - 如果是字符串,直接返回其长度
            - 如果是字典,递归统计所有值的字符数
            - 如果是列表,递归统计所有元素的字符数
            - 其他类型返回0

    Returns:
        int: 嵌套结构中所有字符串值的总字符数。如果输入不是字符串、
             字典或列表,则返回0。
    """
    if isinstance(obj, str):
        return len(obj)
    if isinstance(obj, dict):
        return sum(_count_str_chars(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_str_chars(item) for item in obj)
    return 0


# 模型到 tiktoken 编码器的映射
_MODEL_ENCODINGS = {
    # GPT-4o / GPT-4.1 系列使用 o200k_base
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4.1": "o200k_base",
    "gpt-4.1-mini": "o200k_base",
    "gpt-4.1-nano": "o200k_base",
    # 其他 GPT 系列使用 cl100k_base
    "gpt-3.5-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
}

_encoder_cache = {}


def _get_encoder(model: str = None):
    """根据模型名获取对应的 tiktoken 编码器。"""
    try:
        import tiktoken
    except ImportError:
        return None

    if not model:
        return tiktoken.get_encoding("cl100k_base")

    # 去掉 provider 前缀
    parts = model.split("/") if "/" in model else None
    short_name = parts[len(parts) - 1] if parts else model

    # 查找匹配的编码器
    encoding_name = None
    for key, enc in _MODEL_ENCODINGS.items():
        if short_name.startswith(key):
            encoding_name = enc
            break

    # 默认使用 cl100k_base
    if encoding_name is None:
        encoding_name = "cl100k_base"

    # 缓存编码器
    if encoding_name not in _encoder_cache:
        try:
            _encoder_cache[encoding_name] = tiktoken.get_encoding(encoding_name)
        except Exception:
            return None

    return _encoder_cache[encoding_name]


def _count_tokens_tiktoken(text: str, model: str = None) -> int:
    """使用 tiktoken 精确计算文本的 token 数量。"""
    encoder = _get_encoder(model)
    if encoder is None:
        return int(len(text) / 2.8)
    try:
        return len(encoder.encode(text))
    except Exception:
        return int(len(text) / 2.8)


def _estimate_visual_tokens(block: dict) -> int:
    """估算图片/视频内容块的 token 数量(基于 OpenAI 多模态模型的计算规则)。"""
    btype = block.get("type")
    if btype == "image_url":
        url = block.get("image_url", {}).get("url", "")
    elif btype == "video_url":
        url = block.get("video_url", {}).get("url", "")
    else:
        return 0
    try:
        import base64
        from io import BytesIO
        from PIL import Image

        if not url.startswith("data:"):
            return 85  # 外部 URL 低分辨率估算

        # 解码 base64 获取图片尺寸
        _, data = url.split(",", 1)
        img = Image.open(BytesIO(base64.b64decode(data)))
        w, h = img.size

        # 高分辨率计算：每 512x512 图块约 170 tokens + 基础 85
        tiles = ((w + 511) // 512) * ((h + 511) // 512)
        return 85 + tiles * 170
    except Exception:
        return 500  # 保守估算


def _estimate_audio_tokens(block: dict) -> int:
    """估算音频内容块的 token 数量(基于 OpenAI 音频模型的计算规则)。

    OpenAI 音频模型大约每 0.1 秒音频消耗 1 token。
    由于无法从 base64 数据直接获取时长,使用文件大小估算：
    - MP3/WAV: 约 16KB/秒(128kbps)
    - 每秒约 10 tokens
    """
    if block.get("type") != "input_audio":
        return 0
    try:
        data = block.get("input_audio", {}).get("data", "")
        if not data:
            return 100  # 默认估算
        # base64 编码后大小约为原始的 4/3
        audio_bytes = len(data) * 3 / 4
        # 估算秒数(假设 128kbps = 16KB/秒)
        duration_seconds = audio_bytes / 16000
        # 每秒约 10 tokens
        return max(50, int(duration_seconds * 10))
    except Exception:
        return 500  # 保守估算


def estimate_tokens(messages: list, model: str = None) -> int:
    """估算消息列表的 token 数量。优先使用 tiktoken 精确计算。

    Args:
        messages: 包含"content"字段的消息字典列表(字符串或字典列表)
        model: 模型名称,用于选择对应的分词器
    Returns:
        近似 token 数量,整数类型
    """
    total_tokens = 0
    msg_count = 0
    for m in messages:
        msg_count += 1
        content = m.get("content", "")
        if isinstance(content, str):
            total_tokens += _count_tokens_tiktoken(content, model)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "image_url":
                        total_tokens += _estimate_visual_tokens(block)
                    elif block.get("type") == "input_audio":
                        total_tokens += _estimate_audio_tokens(block)
                    elif block.get("type") == "video_url":
                        total_tokens += _estimate_visual_tokens(block)
                    else:
                        for v in block.values():
                            if isinstance(v, str):
                                total_tokens += _count_tokens_tiktoken(v, model)
        for tc in m.get("tool_calls", []):
            total_tokens += _count_str_chars(tc)
    # 框架令牌：每条消息约4个令牌 + 5%缓冲
    framing_tokens = msg_count * 4
    return int((total_tokens + framing_tokens) * 1.05)


MODEL_CONTEXT_LIMITS = {
    # OpenAI GPT 系列
    "gpt-3.5-turbo": 16385,
    "gpt-4": 8192,
    "gpt-4-turbo": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1": 1000000,
    "gpt-4.1-mini": 1000000,
    "gpt-4.1-nano": 1000000,
    "gpt-5": 128000,
    "gpt-5.4": 128000,
    # OpenAI 推理系列
    "o1": 200000,
    "o1-mini": 128000,
    "o1-pro": 200000,
    "o3": 200000,
    "o3-mini": 200000,
    "o4-mini": 200000,
    # Claude 系列
    "claude-3-5-sonnet": 200000,
    "claude-3-5-haiku": 200000,
    "claude-sonnet-4-6": 200000,
    "claude-opus-4-7": 200000,
    "claude-haiku-4-5-20251001": 200000,
    # Google Gemini 系列
    "gemini-1.5-pro": 2000000,
    "gemini-1.5-flash": 1000000,
    "gemini-2.0-flash": 1000000,
    "gemini-2.5-pro": 1000000,
    "gemini-2.5-flash": 1000000,
    # Meta Llama 系列
    "llama-3.1": 128000,
    "llama-3.3": 128000,
    "llama-4-scout": 10000000,
    "llama-4-maverick": 1000000,
    # DeepSeek 系列
    "deepseek-chat": 128000,
    "deepseek-v3": 128000,
    "deepseek-reasoner": 128000,
    "deepseek-r1": 128000,
    # 小米 MiMo 系列
    "mimo-v2.5-pro": 1000000,
    "mimo-7b": 32768,
    # 阿里 Qwen 系列
    "qwen-turbo": 128000,
    "qwen-plus": 131072,
    "qwen-max": 131072,
    "qwen-2.5": 128000,
    "qwen-3": 128000,
    "qwq-32b": 128000,
}


def get_context_limit(model: str | None = None) -> int:
    if not model:
        return 128000
    # 去掉 provider 前缀,如 "openai/gpt-4o" -> "gpt-4o"
    if "/" in model:
        parts = model.split("/")
        short_name = parts[len(parts) - 1]
    else:
        short_name = model
    # 先精确匹配
    if short_name in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[short_name]
    # 再前缀匹配(按长到短)
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if short_name.startswith(key):
            return limit
    return 128000


def snip_old_tool_results(
    messages: list,
    max_chars: int = 2000,
    preserve_last_n_turns: int = 6,
) -> list:
    """截断距离末尾超过preserve_last_n_turns条的旧工具角色消息。

    对于内容长度超过max_chars的旧工具消息,保留前半部分和最后四分之一,
    在中间插入'[... N chars snipped ...]'标记。
    原地修改并返回同一个列表。

    Args:
        messages: 消息字典列表(原地修改)
        max_chars: 截断前的最大字符长度
        preserve_last_n_turns: 从末尾开始保留的消息数量
    Returns:
        同一个消息列表(已原地修改)
    """
    # 计算需要处理的旧消息的截止索引,保留最后preserve_last_n_turns条消息不处理
    cutoff = max(0, len(messages) - preserve_last_n_turns)

    # 遍历所有需要处理的旧消息
    for i in range(cutoff):
        m = messages[i]
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        if not isinstance(content, str) or len(content) <= max_chars:
            continue

        # 对超长内容进行截断：保留前半部分和最后四分之一,中间用省略标记替换
        first_half = content[: max_chars // 2]
        last_quarter = content[-(max_chars // 4) :]
        snipped = len(content) - len(first_half) - len(last_quarter)
        m["content"] = f"{first_half}\n[... {snipped} 个字符已省略 ...]\n{last_quarter}"
    return messages


def find_split_point(messages: list, keep_ratio: float = 0.3) -> int:
    """查找分割点,使得最近部分的消息约占总token数的keep_ratio比例。

    从消息列表末尾向前遍历,累加token估算值,返回当最近部分的token数达到总token数
    约keep_ratio比例时的索引位置。

    Args:
        messages: 消息字典列表
        keep_ratio: 在最近部分中保留的token比例(0.0-1.0)
    Returns:
        分割索引(messages[:idx]为旧消息,messages[idx:]为新消息)
    """
    # 处理空消息列表的边界情况
    if not messages:
        return 0

    # 确保keep_ratio在有效范围[0.0, 1.0]内
    keep_ratio = max(0.0, min(1.0, keep_ratio))

    # 计算总token数和需要保留的目标token数
    total = estimate_tokens(messages)
    target = int(total * keep_ratio)

    # 从后往前遍历消息,累加token数,找到分割点
    running = 0
    for i in range(len(messages) - 1, -1, -1):
        running += estimate_tokens([messages[i]])
        if running >= target:
            return i

    # 如果所有消息的token数都未达到目标,返回起始位置
    return 0


def compact_messages(messages: list, config: dict, focus: str = "") -> list:
    """通过LLM调用将旧消息压缩为摘要。

    在find_split_point处分割,对旧部分进行摘要,返回
    [摘要消息, 确认消息, *最近消息]。

    参数:
        messages: 完整消息列表
        config: 代理配置字典(必须包含"model_name")
        focus: 可选的聚焦指令,用于指导摘要生成
    返回:
        新的压缩后消息列表
    """
    # 查找消息分割点,确定需要压缩的历史消息范围
    split = find_split_point(messages)
    if split <= 0:
        return messages

    # 将消息分为旧消息(需要压缩)和最近消息(保留原样)
    old = messages[:split]
    recent = messages[split:]

    # 构建旧消息的文本表示,用于生成摘要
    old_text = ""
    for m in old:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            old_text += f"[{role}]: {content}\n"
        elif isinstance(content, list):
            old_text += f"[{role}]: {content}\n"

    # 构建摘要提示词,包含核心指令和可选的聚焦方向
    summary_prompt = (
        "请简洁地总结以下对话历史。"
        "保留关键决策、文件路径、工具结果以及继续对话所需的上下文信息。"
    )
    if focus:
        summary_prompt += f"\n\n特别关注:{focus}"
    summary_prompt += "\n\n" + old_text

    # 调用LLM生成对话历史摘要
    messages = [
        {"role": "system", "content": "你是一个简洁的摘要生成器。"},
        {"role": "user", "content": summary_prompt},
    ]
    resp = chat(
        messages,
        model_name=config["model_name"],
        openai_api_base=config.get("OPENAI_BASE_URL", ""),
        openai_api_key=config.get("OPENAI_API_KEY", ""),
        multimodal_model_name=config.get("multimodal_model_name"),
    )
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


def maybe_compact(task, config: dict):
    """
    根据上下文长度阈值判断是否需要执行消息压缩。

    该函数采用两层压缩策略：
    1. 首先尝试裁剪旧的工具调用结果(轻量级操作)
    2. 如果仍超出阈值,则执行完整的消息自动压缩(重量级操作)

    Args:
        task: 代理任务对象,包含需要检查的消息列表(需有 messages 属性)
        config (dict): 配置字典,用于控制压缩行为的参数

    Returns:
        bool: 如果执行了任何压缩操作返回 True,否则返回 False
              - False: 消息总长度未超过阈值,无需压缩
              - True: 执行了裁剪工具结果或完整消息压缩
    """
    limit = get_context_limit(config.get("model_name"))
    threshold = limit * 0.7
    model = config.get("model_name")

    if estimate_tokens(task.messages, model) <= threshold:
        return False

    # 第一层压缩：裁剪旧的工具调用结果
    snip_old_tool_results(task.messages)

    if estimate_tokens(task.messages, model) <= threshold:
        return True

    # 第二层压缩：执行完整的消息自动压缩
    task.messages = compact_messages(task.messages, config)
    return True
