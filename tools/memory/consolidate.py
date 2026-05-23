import json

from llm import achat
from tools.memory.memory import Memory


def consolidate_system_prompt() -> str:
    existing_memories = Memory.get_memory_index_preview().strip()
    if existing_memories:
        existing_memories = (
            "\n现有记忆摘要(请避免重复提取相同内容):" + existing_memories
        )

    CONSOLIDATE_SYSTEM_PROMPT = f"""\
    你是一个记忆提取专家。分析一段对话，提取值得长期保留的记忆。
    {existing_memories}

    提取规则：
    1. **用户偏好 (user)**：用户的角色、技能水平、工作习惯、沟通偏好
    2. **工作流反馈 (feedback)**：用户纠正过的方法、确认有效的做法、明确的"不要做X"指令
    3. **项目信息 (project)**：正在进行的工作、重要决策、截止日期、团队动态

    可以提取：
    - 命令执行出错的原因和正确的做法(避免重复踩坑)

    不要提取：
    - 临时的调试信息或一次性的代码修改
    - 已经在代码或 CLAUDE.md 中记录的信息
    - 模型自己生成的分析结论(除非用户明确确认)
    - 通用的编程知识

    质量高于数量,最多提取 3 条记忆。只提取最有价值的内容。

    返回一个 JSON 对象,包含键 "memories",其值为对象列表,每个对象包含：
    - name: 简短标识符,例如 "user_prefers_concise_responses"
    - type: "user" | "feedback" | "project"
    - description: 单行描述(用于搜索相关性)
    - content: 记忆主体；对于反馈/项目类型,以规则/事实开头,然后添加 **Why:** 和 **How to apply:** 行
    - confidence: 浮点数 0.0-1.0(推断的用 ~0.8,明确陈述的用 ~0.9)

    如果没有新的或值得保存的内容,返回 {{"memories": []}}。
    直接输出 JSON,不要用 markdown 代码块包裹。"""
    return CONSOLIDATE_SYSTEM_PROMPT


def _format_messages_for_analysis(messages: list) -> str:
    """将消息列表格式化为可读文本，用于 LLM 分析。"""
    parts = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            parts.append(f"[{role}]: {content}")
        elif isinstance(content, list):
            text_blocks = []
            for block in content:
                if isinstance(block, dict):
                    for v in block.values():
                        if isinstance(v, str):
                            text_blocks.append(v)
            if text_blocks:
                parts.append(f"[{role}]: {' '.join(text_blocks)}")
    return "\n".join(parts)


async def consolidate_session(messages: list, config: dict) -> list[Memory]:
    """分析会话消息，提取值得长期保留的记忆并保存。

    使用 LLM 分析对话内容，识别用户偏好、工作流反馈、
    项目信息等值得记忆的内容，最多提取 3 条，自动保存到磁盘。

    Args:
        messages: 对话消息列表
        config: 配置字典，需包含 model_name 或 mini_model_name

    Returns:
        Memory 对象列表（已保存）
    """
    if not messages:
        return []

    conversation_text = _format_messages_for_analysis(messages)
    if not conversation_text.strip():
        return []

    system_prompt = consolidate_system_prompt()

    llm_messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"请分析以下对话并提取值得长期保存的记忆:\n\n{conversation_text}",
        },
    ]

    model_name = config.get("mini_model_name") or config.get("model_name")
    resp = await achat(llm_messages, model_name, enable_thinking=False, thinking=False)
    raw = resp.content.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    items = data.get("memories", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        return []

    memories = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "").strip()
        description = item.get("description", "").strip()
        content = item.get("content", "").strip()
        mem_type = item.get("type", "user").strip()
        confidence = item.get("confidence", 0.8)

        if not name or not content:
            continue
        if mem_type not in ("user", "feedback", "project"):
            mem_type = "user"

        mem = Memory(
            name=name,
            description=description,
            content=content,
            type=mem_type,
            source="model",
            confidence=float(confidence),
        )

        result = mem.save_memory()
        if result["status"] == "identical":
            continue
        if result["status"] == "conflict":
            old_content = result["existing"]["content"].strip()
            if old_content == content.strip():
                continue
            counter = 2
            base_name = name
            while Memory.exists(mem.scope, f"{base_name}_v{counter}"):
                counter += 1
            mem.name = f"{base_name}_v{counter}"
            mem.filename = Memory.get_memory_path(mem.scope, mem.name)
            mem.save_memory()

        memories.append(mem)

    return memories
