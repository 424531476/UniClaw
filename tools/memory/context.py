import json
import math
from pathlib import Path
import time
from config import load_config
from context import Scope
from .memory import Memory
from utils.truncation import truncate_text_by_lines


def _get_tool_names() -> dict:
    """延迟获取工具名称,避免循环导入"""
    from .tools import memory_save, memory_delete

    return {
        "save": memory_save.name,
        "delete": memory_delete.name,
    }


# 记忆格式示例(frontmatter)
MEMORY_FORMAT_EXAMPLE = """\
```markdown
---
name: {{记忆名称}}
description: {{单行描述——用于决定相关性,所以要具体}}
type: {{user | feedback | project | reference}}
source: {{user | model | tool}}
scope: {{user | project}}
confidence: {{0.0-1.0}}
---

{{记忆内容——对于 feedback/project 类型:规则/事实,然后是 **Evidence:** 和 **How to apply:** 行；命令/工具失败经验还要包含 **Failed:** 和 **Use instead:**}}
```"""
MEMORY_SYSTEM_PROMPT = """\
## 记忆系统

你有一个持久的、基于文件的记忆系统。记忆存储为带有 YAML frontmatter 的 markdown 文件。
随着时间的推移建立这个系统,以便未来的对话拥有关于用户、他们的偏好以及你们一起工作的上下文。

**字段说明**:
- `name`:稳定、可搜索、文件名安全的短标识。
- `description`:单行摘要,用于检索相关性判断。
- `content`:可直接指导未来行为的正文。
- `type`:只保存无法从代码库直接派生的内容:
  - `user` -- 用户长期角色、目标、知识、稳定偏好
  - `feedback` -- 用户纠正、确认的方法、工具/命令失败后的正确做法
  - `project` -- 项目约定、环境限制、验证路径、决策
  - `reference` -- 外部系统指针(Linear、Grafana、Slack 等)
- `source`: `user`、`model` 或 `tool`,不要伪装来源。
- `scope`:`user` 或 `project`；项目专属内容优先用 `project`。
- `confidence`:0.0-1.0;明确事实/用户确认接近 1.0,推断应降低或不保存。

**何时保存**:
- 用户纠正你、确认一种方法,或分享应该超越本次对话持续存在的上下文。
- 工具或命令执行出错,并且已经知道失败原因、正确命令、正确环境、权限规则或规避方法时,必须保存为 `feedback`。
- 对于命令/工具失败记忆,正文必须包含:`**Failed:**` 原命令/工具与关键报错；`**Why:**` 失败原因；`**Use instead:**` 下次应使用的命令/流程；`**How to apply:**` 适用项目/环境/触发条件。
- 如果检索到的旧记忆明显错误、API 已更新、路径/命令已失效,必须及时修正或删除:能形成替代内容时,用 `{save}(..., force=True)` 覆盖同名记忆；只有旧内容无替代价值时,才用 `{delete}` 删除。

**feedback/project 的正文结构**:以规则/事实开头,然后:
  **Evidence:** (来自用户确认、工具输出或可复现结果的证据) | **How to apply:** (此指导何时生效)

**格式**:
{format_example}

**保存操作**:
- 必须使用 {save} 和 {delete} 工具来写入或删除记忆，直接修改文件会导致索引错误
- 可以直接读取记忆文件获取详细内容
- 修正同名旧记忆时传 `force=True`；索引(MEMORY.md)会自动更新

**不应该保存的内容**:
- 已在代码、README、AGENTS.md、CLAUDE.md、git 历史或现有记忆中记录的内容
- 流水账、日记式记录(如"今天修了某个bug")；如果要记录,必须包含:问题原因 + 解决方法 + 对未来任务的帮助
- 只有当前任务有用的中间状态、临时日志、未定位原因的报错片段
- 助理自己推测出的用户需求、偏好或项目事实,除非用户明确确认
- 通用编程知识或任何项目外也普遍成立的常识
- 普通调试修复默认不保存；但命令/工具失败一旦形成可复用规则,必须保存为 feedback

**在从记忆中推荐之前**:记忆可能已过时,在采取行动之前验证它仍然存在。对于当前状态,优先使用 `git log` 或阅读代码。
"""


def ai_select_memories(query: str, memories: list, max_results: int):
    text_lines = []
    for i, memory in enumerate(memories):
        text_line = f"{i}:[{memory.type}] {memory.name} {memory.description}"
        text_lines.append(text_line)
    text = "\n".join(text_lines)

    system = (
        "你负责选择与查询相关的记忆。"
        "返回一个 JSON 对象,包含键 'indices',其值为整数索引列表(从0开始),"
        f"来自提供的列表。最多选择 {max_results} 个条目。"
        '仅包含与查询明确相关的索引。如果没有相关项,返回 {"indices": []}。'
        "重要:直接输出原始 JSON 字符串,不要使用 Markdown 代码块(如 ```json)包裹,不要添加任何额外文本。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"查询:{query}\n\n记忆:\n{text}"},
    ]
    from llm import chat
    cfg = load_config()

    ai_message = chat(
        messages,
        model_name=cfg.get("mini_model_name", ""),
        openai_api_base=cfg.get("OPENAI_BASE_URL", ""),
        openai_api_key=cfg.get("OPENAI_API_KEY", ""),
        multimodal_model_name=cfg.get("multimodal_model_name"),
        enable_thinking=False,
        thinking=False,
    )
    parsed = json.loads(ai_message.content)
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
    return results


def memory_freshness_text(mtime_s: float) -> str:
    """对于超过 1 天的记忆的陈旧警告(如果是新的则为空字符串)。

    由用户报告的陈旧代码状态记忆(引用已更改的代码的文件:行号)
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
    """自 mtime_s 以来的天数(向下取整,对未来时间限制为 0)。"""
    return max(0, math.floor((time.time() - mtime_s) / 86_400))


def get_memory_system_prompt() -> str:
    """获取内存系统提示。"""
    body = Memory.get_memory_index_preview()
    tool_names = _get_tool_names()
    prompt = MEMORY_SYSTEM_PROMPT.format(
        save=tool_names["save"],
        delete=tool_names["delete"],
        format_example=MEMORY_FORMAT_EXAMPLE,
    )
    return f"{prompt}\n\n## MEMORY.md\n{body}"
