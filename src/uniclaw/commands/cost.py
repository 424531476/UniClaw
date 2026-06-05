"""费用统计命令"""

from uniclaw.agent import AgentTask
from uniclaw.console.ui import info


def cmd_cost(_args: str, _task: AgentTask, _config: dict) -> bool:
    """显示详细的 token 消耗和费用统计(按模型计费,价格来自 OpenRouter)"""
    from uniclaw.utils.usage import get_stats, UsageField, TOTAL, DAILY

    data = get_stats()
    total = data.get(TOTAL, {})
    daily = data.get(DAILY, {})
    by_model = data.get("by_model", {})

    in_tokens = total.get(UsageField.INPUT_TOKENS, 0)
    out_tokens = total.get(UsageField.OUTPUT_TOKENS, 0)
    api_calls = total.get(UsageField.API_CALLS, 0)
    tool_calls = total.get(UsageField.TOOL_CALLS, 0)
    total_tokens = in_tokens + out_tokens

    info(f"\n费用统计\n")
    info("─" * 50)
    info(f"  输入 tokens:   {in_tokens:>12,}")
    info(f"  输出 tokens:   {out_tokens:>12,}")
    info(f"  总 tokens:     {total_tokens:>12,}")
    info(f"  API 调用:      {api_calls:>12,}")
    info(f"  工具调用:      {tool_calls:>12,}")

    # 按模型计费
    if by_model:
        total_cost = 0.0
        info(f"\n按模型计费:\n")
        info(f"  {'模型':<28} {'输入':>10} {'输出':>10} {'调用':>6} {'费用':>10}")
        info(f"  {'─'*28} {'─'*10} {'─'*10} {'─'*6} {'─'*10}")
        for model_name, m in sorted(by_model.items()):
            m_in = m.get(UsageField.INPUT_TOKENS, 0)
            m_out = m.get(UsageField.OUTPUT_TOKENS, 0)
            m_calls = m.get(UsageField.API_CALLS, 0)
            m_cost = m.get("cost", 0.0)
            total_cost += m_cost
            display_name = model_name if len(model_name) <= 27 else model_name[:24] + "..."
            info(
                f"  {display_name:<28} {m_in:>10,} {m_out:>10,} "
                f"{m_calls:>6} ${m_cost:>9.4f}"
            )
        info(f"  {'─'*28} {'─'*10} {'─'*10} {'─'*6} {'─'*10}")
        info(f"  {'合计':<28} {in_tokens:>10,} {out_tokens:>10,} "
             f"{api_calls:>6} ${total_cost:>9.4f}")
    else:
        # 兼容旧数据(无 by_model)
        info(f"  (旧数据无费用记录,升级后的新调用将自动计费)")

    # 每日统计
    if daily:
        info(f"\n最近 7 天:\n")
        info(f"  {'日期':<12} {'输入':>10} {'输出':>10} {'合计':>10} {'调用':>6} {'费用':>10}")
        info(f"  {'─'*12} {'─'*10} {'─'*10} {'─'*10} {'─'*6} {'─'*10}")
        for date in sorted(daily.keys(), reverse=True)[:7]:
            day = daily[date]
            d_in = day.get(UsageField.INPUT_TOKENS, 0)
            d_out = day.get(UsageField.OUTPUT_TOKENS, 0)
            d_calls = day.get(UsageField.API_CALLS, 0)
            d_cost = day.get("cost", 0.0)
            info(
                f"  {date:<12} {d_in:>10,} {d_out:>10,} {d_in+d_out:>10,} "
                f"{d_calls:>6} ${d_cost:>9.4f}"
            )
    info("")

    return True
