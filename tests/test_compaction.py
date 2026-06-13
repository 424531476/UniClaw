"""上下文压缩逻辑测试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from uniclaw.compaction import maybe_compact


def _make_config(model_name, estimate_tokens):
    """创建模拟 config,session 的 estimate_tokens 返回指定值。"""
    session = SimpleNamespace(
        estimate_tokens=MagicMock(return_value=estimate_tokens),
        snip_old_tool_results=MagicMock(),
        compact=AsyncMock(),
    )
    return SimpleNamespace(
        current_agent=SimpleNamespace(session=session),
        model_name=model_name,
    )


async def test_below_threshold_no_action():
    """token 数低于阈值时不做任何压缩。"""
    config = _make_config("gpt-4o", estimate_tokens=10000)
    result = await maybe_compact(config)
    assert result is False
    config.current_agent.session.snip_old_tool_results.assert_not_called()
    config.current_agent.session.compact.assert_not_called()


async def test_snip_only():
    """token 数超阈值但 snip 后足够时,只做 snip。"""
    # gpt-4o limit=128000, threshold=128000*0.7=89600
    session = SimpleNamespace(
        estimate_tokens=MagicMock(side_effect=[90000, 80000]),
        snip_old_tool_results=MagicMock(),
        compact=AsyncMock(),
    )
    config = SimpleNamespace(
        current_agent=SimpleNamespace(session=session),
        model_name="gpt-4o",
    )
    result = await maybe_compact(config)
    assert result is True
    session.snip_old_tool_results.assert_called_once()
    session.compact.assert_not_called()


async def test_full_compact():
    """token 数超阈值且 snip 后仍然超时,执行完整压缩。"""
    session = SimpleNamespace(
        estimate_tokens=MagicMock(side_effect=[90000, 89700]),
        snip_old_tool_results=MagicMock(),
        compact=AsyncMock(),
    )
    config = SimpleNamespace(
        current_agent=SimpleNamespace(session=session),
        model_name="gpt-4o",
    )
    result = await maybe_compact(config)
    assert result is True
    session.snip_old_tool_results.assert_called_once()
    session.compact.assert_called_once()


async def test_unknown_model_uses_default_limit():
    """未知模型使用默认 128000 limit,低于阈值时不压缩。"""
    # 128000 * 0.7 = 89600, 50000 < 89600 → 不压缩
    config = _make_config("unknown-model", estimate_tokens=50000)
    result = await maybe_compact(config)
    assert result is False


def test_get_context_limit_known_models():
    """验证已知模型的 context limit。"""
    from uniclaw.compaction import get_context_limit

    assert get_context_limit("gpt-4o") == 128000
    assert get_context_limit("gpt-4.1") == 1000000
    assert get_context_limit(None) == 128000
    assert get_context_limit("openai/gpt-4o") == 128000
