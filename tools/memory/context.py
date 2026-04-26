import json
import math
from pathlib import Path
import time
from config import get_config
from context import Scope
from .memory import Memory
from utils.truncation import truncate_text_by_lines

# 记忆格式示例（frontmatter）
MEMORY_FORMAT_EXAMPLE = """\
```markdown
---
name: {{记忆名称}}
description: {{单行描述——用于决定相关性，所以要具体}}
type: {{user | feedback | project | reference}}
---

{{记忆内容——对于 feedback/project 类型：规则/事实，然后是 **Why:** 和 **How to apply:** 行}}
```"""
MEMORY_SYSTEM_PROMPT = """\
## 记忆系统

你有一个持久的、基于文件的记忆系统。记忆存储为带有 YAML frontmatter 的 markdown 文件。
随着时间的推移建立这个系统，以便未来的对话拥有关于用户、他们的偏好以及你们一起工作的上下文。

**type**（只保存无法从代码库中派生的内容）：
- **user** — 角色、目标、知识、偏好
- **feedback** — 关于如何工作的指导（更正和对不明显方法的确认）
- **project** — 正在进行的工作、决策、不在 git 历史中的截止日期
- **reference** — 指向外部系统的指针（Linear、Grafana、Slack 等）

**何时保存**：如果用户纠正你、确认一种方法，或分享应该超越本次对话持续存在的上下文。
对于反馈：保存更正和安静的确认。

**feedback/project 的正文结构**：以规则/事实开头，然后：
  **Why:** （给出的原因）| **How to apply:** （此指导何时生效）

**格式**：
{format_example}

**保存分为两步**：
1. 使用 memory_save 将记忆写入其自己的文件（例如 `feedback_testing.md`）。
2. 索引（MEMORY.md）会自动更新。

**不应该保存的内容**：代码模式、架构、git 历史、调试修复、
CLAUDE.md 中已有的内容，或短暂的任务状态。

**在从记忆中推荐之前**：命名文件、函数或标志的记忆可能已过时。
在采取行动之前验证它仍然存在。对于当前状态，优先使用 `git log` 或阅读代码。
""".format(
    format_example=MEMORY_FORMAT_EXAMPLE
)


def ai_select_memories(query: str, memories: list, max_results: int):
    text_lines = []
    for i, memory in enumerate(memories):
        text_line = f"{i}:[{memory.type}] {memory.name} {memory.description}"
        text_lines.append(text_line)
    text = "\n".join(text_lines)

    system = (
        "你负责选择与查询相关的记忆。"
        "返回一个 JSON 对象，包含键 'indices'，其值为整数索引列表（从0开始），"
        f"来自提供的列表。最多选择 {max_results} 个条目。"
        '仅包含与查询明确相关的索引。如果没有相关项，返回 {"indices": []}。'
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"查询：{query}\n\n记忆：\n{text}"},
    ]
    from llm import chat

    ai_message = chat(messages, get_config().mini_model_name)
    parsed = json.loads(ai_message["content"])

    indices = [int(i) for i in parsed["indices"]]
    indices = indices[:max_results]
    results = []
    for i in indices:
        if i < 0 or i >= len(memories):
            continue
        memory = memories[i]
        mtime_s = Path(memory.filename).stat().st_mtime

        results.append(
            {
                "name": memory.name,
                "description": memory.description,
                "type": memory.type,
                "scope": memory.scope,
                "content": memory.content,
                "filename": memory.filename,
                "mtime_s": mtime_s,
                "freshness_text": memory_freshness_text(mtime_s),
                "confidence": memory.confidence,
                "source": memory.source,
                "memory": memory,
                # "created": memory.created,
                # "last_used_at": memory.last_used_at,
            }
        )


def memory_freshness_text(mtime_s: float) -> str:
    """对于超过 1 天的记忆的陈旧警告（如果是新的则为空字符串）。

    由用户报告的陈旧代码状态记忆（引用已更改的代码的文件:行号）
    被断言为事实的问题驱动。
    """
    d = memory_age_days(mtime_s)
    if d <= 1:
        return ""
    return (
        f"这条记忆已有 {d} 天。 "
        "记忆是特定时间点的观察记录,而非实时状态 — "
        "关于代码行为或文件:行号引用的声明可能已过时。 "
        "在断言为事实之前,请对照当前代码进行验证。"
    )


def memory_age_days(mtime_s: float) -> int:
    """自 mtime_s 以来的天数（向下取整，对未来时间限制为 0）。"""
    return max(0, math.floor((time.time() - mtime_s) / 86_400))


def get_memory_system_prompt() -> str:
    parts: list[str] = []
    for scope in [Scope.USER.value, Scope.PROJECT.value]:
        content = Memory.get_index_content(scope)
        content = truncate_text_by_lines(content)
        parts.append(content)
    body = "\n\n".join(parts)
    return f"{MEMORY_SYSTEM_PROMPT}\n\n## MEMORY.md\n{body}"
