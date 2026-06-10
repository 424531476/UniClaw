import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from uniclaw.agent import AgentTask
from uniclaw.compaction import _count_tokens_tiktoken, get_context_limit
from uniclaw.config import AppConfig
from uniclaw.console.ui import info, warn
from uniclaw.context import build_system_prompt


AUTOCOMPACT_RATIO = 0.30
BAR_CELLS = 50


@dataclass
class ContextItem:
    name: str
    tokens: int


@dataclass
class ContextReport:
    model: str
    limit: int
    system_prompt_tokens: int
    tool_tokens: int
    skill_tokens: int
    message_tokens: int
    autocompact_tokens: int
    tool_groups: list[ContextItem]
    skill_groups: list[ContextItem]
    skills: list[ContextItem]
    tools: list[ContextItem]

    @property
    def used_tokens(self) -> int:
        return (
            self.system_prompt_tokens
            + self.tool_tokens
            + self.skill_tokens
            + self.message_tokens
        )

    @property
    def free_tokens(self) -> int:
        return max(0, self.limit - self.used_tokens - self.autocompact_tokens)


def _token_count_text(text: str, model: str | None = None) -> int:
    return _count_tokens_tiktoken(text or "", model)


def _format_tokens(tokens: int) -> str:
    sign = "-" if tokens < 0 else ""
    tokens = abs(int(tokens))
    if tokens >= 1_000_000:
        return f"{sign}{tokens / 1_000_000:.1f}m"
    if tokens >= 1_000:
        return f"{sign}{tokens / 1_000:.1f}k"
    return f"{sign}{tokens}"


def _pct(tokens: int, limit: int) -> float:
    if limit <= 0:
        return 0.0
    return tokens / limit * 100


def _serialize_tool(tool: Any) -> str:
    from uniclaw.llm import tool_to_openai

    try:
        payload = tool_to_openai(tool)
    except Exception:
        payload = {
            "name": getattr(tool, "name", tool.__class__.__name__),
            "description": getattr(tool, "description", ""),
            "args": getattr(tool, "args", {}),
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _tool_group_name(tool: Any) -> str:
    module = getattr(tool, "__module__", "") or tool.__class__.__module__
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == "tools":
        return parts[1]
    name = getattr(tool, "name", "")
    if "_" in name:
        return name.split("_", 1)[0]
    return "other"


def _top_items(items: list[ContextItem], limit: int = 8) -> list[ContextItem]:
    return sorted(items, key=lambda item: item.tokens, reverse=True)[:limit]


def _build_usage_bar(report: ContextReport) -> list[str]:
    used_cells = round(report.used_tokens / report.limit * BAR_CELLS) if report.limit else 0
    buffer_cells = (
        round(report.autocompact_tokens / report.limit * BAR_CELLS)
        if report.limit
        else 0
    )
    used_cells = max(0, min(BAR_CELLS, used_cells))
    buffer_cells = max(0, min(BAR_CELLS - used_cells, buffer_cells))
    free_cells = max(0, BAR_CELLS - used_cells - buffer_cells)

    cells = ["⛁"] * used_cells + ["⛶"] * free_cells + ["⛝"] * buffer_cells
    if not cells:
        cells = ["⛶"] * BAR_CELLS

    lines = []
    for i in range(0, BAR_CELLS, 10):
        lines.append(" ".join(cells[i : i + 10]))
    return lines


def analyze_context(task: AgentTask, config: AppConfig) -> ContextReport:
    model = config.model_name or "unknown"
    limit = get_context_limit(model)

    system_prompt = build_system_prompt(config)
    system_prompt_tokens = _token_count_text(system_prompt, model)
    message_tokens = task.session.estimate_tokens(model)

    from uniclaw.tools import get_tools

    tool_groups: dict[str, int] = defaultdict(int)
    tool_items: list[ContextItem] = []
    for tool in get_tools():
        tokens = _token_count_text(_serialize_tool(tool), model)
        tool_items.append(ContextItem(getattr(tool, "name", "unknown"), tokens))
        tool_groups[_tool_group_name(tool)] += tokens

    from uniclaw.tools.skill.loader import load_skills

    skill_source_groups: dict[str, int] = defaultdict(int)
    skill_items: list[ContextItem] = []
    for skill in load_skills(task.session.root_dir):
        skill_text = "\n".join(
            [
                skill.name,
                skill.description,
                ", ".join(skill.triggers),
                ", ".join(skill.tools),
                skill.when_to_use,
                skill.argument_hint,
                skill.prompt,
            ]
        )
        tokens = _token_count_text(skill_text, model)
        skill_items.append(ContextItem(skill.name, tokens))
        skill_source_groups[skill.source or "user"] += tokens

    autocompact_tokens = int(limit * AUTOCOMPACT_RATIO)

    return ContextReport(
        model=model,
        limit=limit,
        system_prompt_tokens=system_prompt_tokens,
        tool_tokens=sum(item.tokens for item in tool_items),
        skill_tokens=sum(item.tokens for item in skill_items),
        message_tokens=message_tokens,
        autocompact_tokens=autocompact_tokens,
        tool_groups=[
            ContextItem(name, tokens)
            for name, tokens in sorted(
                tool_groups.items(), key=lambda item: item[1], reverse=True
            )
        ],
        skill_groups=[
            ContextItem(name, tokens)
            for name, tokens in sorted(
                skill_source_groups.items(), key=lambda item: item[1], reverse=True
            )
        ],
        skills=_top_items(skill_items, 10),
        tools=_top_items(tool_items, 10),
    )


def format_context_report(report: ContextReport) -> str:
    lines = ["Context Usage"]
    bar = _build_usage_bar(report)
    for idx, row in enumerate(bar):
        suffix = ""
        if idx == 0:
            suffix = f"  {report.model}"
        elif idx == 1:
            suffix = (
                f"  {_format_tokens(report.used_tokens)}/{_format_tokens(report.limit)} "
                f"tokens ({_pct(report.used_tokens, report.limit):.1f}%)"
            )
        elif idx == 3:
            suffix = "  Estimated usage by category"
        elif idx == 4:
            suffix = (
                f"  ⛁ System prompt: {_format_tokens(report.system_prompt_tokens)} "
                f"tokens ({_pct(report.system_prompt_tokens, report.limit):.1f}%)"
            )
        lines.append(f"  {row}{suffix}")

    category_lines = [
        ("System tools", report.tool_tokens, "⛁"),
        ("Skills", report.skill_tokens, "⛁"),
        ("Messages", report.message_tokens, "⛁"),
        ("Free space", report.free_tokens, "⛶"),
        ("Autocompact buffer", report.autocompact_tokens, "⛝"),
    ]
    for label, tokens, marker in category_lines:
        lines.append(
            f"  {marker} {label}: {_format_tokens(tokens)} tokens "
            f"({_pct(tokens, report.limit):.1f}%)"
        )

    if report.tool_groups:
        lines.append("")
        lines.append("Tools · by package")
        for item in report.tool_groups:
            lines.append(f"├ {item.name}: ~{_format_tokens(item.tokens)} tokens")

    if report.tools:
        lines.append("")
        lines.append("Largest tools")
        for item in report.tools:
            lines.append(f"├ {item.name}: ~{_format_tokens(item.tokens)} tokens")

    if report.skill_groups:
        lines.append("")
        lines.append("Skills · /skills")
        for item in report.skill_groups:
            lines.append(f"├ {item.name}: ~{_format_tokens(item.tokens)} tokens")

    if report.skills:
        lines.append("")
        lines.append("Largest skills")
        for item in report.skills:
            lines.append(f"├ {item.name}: ~{_format_tokens(item.tokens)} tokens")

    lines.append("")
    lines.append("Note: values are local estimates; provider-side tool schema overhead may differ.")
    return "\n".join(lines)


def cmd_context(_args: str, config: AppConfig) -> bool:
    task = config.current_agent
    try:
        info("\n" + format_context_report(analyze_context(task, config)))
    except Exception as exc:
        warn(f"无法估算上下文: {exc}")
    return True
