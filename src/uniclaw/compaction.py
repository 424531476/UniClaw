import math
from uniclaw.utils.message import MessageRole, extract_text
from uniclaw.config import AppConfig

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
    # 再前缀匹配(按 key 长度降序，确保最长前缀优先匹配)
    sorted_keys = sorted(MODEL_CONTEXT_LIMITS.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if short_name.startswith(key):
            return MODEL_CONTEXT_LIMITS[key]
    return 128000


async def maybe_compact(config: AppConfig):
    """
    根据上下文长度阈值判断是否需要执行消息压缩。

    该函数采用两层压缩策略:
    1. 首先尝试裁剪旧的工具调用结果(轻量级操作)
    2. 如果仍超出阈值,则执行完整的消息自动压缩(重量级操作)

    Args:
        config (AppConfig): 应用配置对象

    Returns:
        bool: 如果执行了任何压缩操作返回 True,否则返回 False
              - False: 消息总长度未超过阈值,无需压缩
              - True: 执行了裁剪工具结果或完整消息压缩
    """
    task = config.current_agent
    limit = get_context_limit(config.model_name)
    threshold = limit * 0.7
    model = config.model_name

    if task.session.estimate_tokens(model) <= threshold:
        return False

    # 第一层压缩:裁剪旧的工具调用结果
    task.session.snip_old_tool_results()

    if task.session.estimate_tokens(model) <= threshold:
        return True

    # 第二层压缩:执行完整的消息自动压缩
    await task.session.compact(config)
    return True
