from uniclaw.commands import COMMANDS
from uniclaw.commands.context_usage import ContextItem, ContextReport, format_context_report


def test_context_command_registered():
    assert "context" in COMMANDS


def test_format_context_report_includes_categories_and_breakdowns():
    report = ContextReport(
        model="test-model",
        limit=10_000,
        system_prompt_tokens=1_000,
        tool_tokens=2_000,
        skill_tokens=300,
        message_tokens=200,
        autocompact_tokens=3_000,
        tool_groups=[ContextItem("fs", 1200), ContextItem("shell", 800)],
        skill_groups=[ContextItem("user", 300)],
        skills=[ContextItem("demo", 300)],
        tools=[ContextItem("Read", 900)],
    )

    text = format_context_report(report)

    assert "Context Usage" in text
    assert "test-model" in text
    assert "System prompt" in text
    assert "System tools" in text
    assert "Skills" in text
    assert "Messages" in text
    assert "Autocompact buffer" in text
    assert "fs" in text
    assert "demo" in text
