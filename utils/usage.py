"""用量统计模块 — 跟踪 token 消耗和 API 调用次数，持久化到磁盘"""
import json
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from context import get_app_dir, Scope


class UsageField(str, Enum):
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    API_CALLS = "api_calls"
    TOOL_CALLS = "tool_calls"


# 数据结构的顶层键
TOTAL = "total"
DAILY = "daily"

# 统计字段列表（用于生成空记录）
_STAT_FIELDS = [UsageField.INPUT_TOKENS, UsageField.OUTPUT_TOKENS, UsageField.API_CALLS, UsageField.TOOL_CALLS]


_lock = threading.Lock()


def _stats_path() -> Path:
    return get_app_dir(Scope.USER.value) / "usage.json"


def _load() -> dict:
    p = _stats_path()
    if not p.exists():
        return {TOTAL: _new_record(), DAILY: {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {TOTAL: _new_record(), DAILY: {}}


def _save(data: dict):
    p = _stats_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _new_record() -> dict:
    return {f.value: 0 for f in _STAT_FIELDS}


def record_usage(input_tokens: int = 0, output_tokens: int = 0, tool_calls: int = 0):
    """记录一次 API 调用的用量"""
    if input_tokens == 0 and output_tokens == 0 and tool_calls == 0:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        data = _load()
        # 累计总量
        data[TOTAL][UsageField.INPUT_TOKENS] += input_tokens
        data[TOTAL][UsageField.OUTPUT_TOKENS] += output_tokens
        data[TOTAL][UsageField.API_CALLS] += 1
        data[TOTAL][UsageField.TOOL_CALLS] += tool_calls
        # 每日统计
        if today not in data[DAILY]:
            data[DAILY][today] = _new_record()
        day = data[DAILY][today]
        day[UsageField.INPUT_TOKENS] += input_tokens
        day[UsageField.OUTPUT_TOKENS] += output_tokens
        day[UsageField.API_CALLS] += 1
        day[UsageField.TOOL_CALLS] += tool_calls
        _save(data)


def get_stats() -> dict:
    """获取用量统计"""
    return _load()


def format_stats(data: dict | None = None) -> str:
    """格式化用量统计为可读文本"""
    if data is None:
        data = _load()
    total = data.get(TOTAL, _new_record())
    daily = data.get(DAILY, {})

    lines = ["用量统计:"]
    lines.append(f"  总计: {total[UsageField.INPUT_TOKENS]:,} 输入 + {total[UsageField.OUTPUT_TOKENS]:,} 输出 tokens")
    lines.append(f"  总计: {total[UsageField.API_CALLS]:,} 次 API 调用, {total[UsageField.TOOL_CALLS]:,} 次工具调用")
    total_tokens = total[UsageField.INPUT_TOKENS] + total[UsageField.OUTPUT_TOKENS]
    lines.append(f"  总 tokens: {total_tokens:,}")

    if daily:
        lines.append("")
        lines.append("  最近 7 天:")
        for date in sorted(daily.keys(), reverse=True)[:7]:
            day = daily[date]
            in_t = day[UsageField.INPUT_TOKENS]
            out_t = day[UsageField.OUTPUT_TOKENS]
            lines.append(
                f"    {date}: {in_t:,}+{out_t:,}={in_t + out_t:,} tokens, "
                f"{day[UsageField.API_CALLS]} 次调用"
            )

    return "\n".join(lines)
