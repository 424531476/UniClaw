import sys

import pytest

from tools.hooks import HookError, HookEvent, run_hooks, add_hook
from tools.hooks import hook_read, hook_add


def _python_append_command(path):
    script = (
        "import json, pathlib, sys; "
        f"p=pathlib.Path({str(path)!r}); "
        "p.write_text((p.read_text(encoding='utf-8') if p.exists() else '') + "
        "json.load(sys.stdin)['event'] + '\\n', encoding='utf-8')"
    )
    return f'"{sys.executable}" -c "{script}"'


def test_claude_style_hook_runs_matching_tool(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "hook.log"
    add_hook(
        event="PreToolUse",
        commands=[_python_append_command(out)],
        matcher="Bash",
    )

    run_hooks(
        HookEvent.PRE_TOOL_USE,
        {"tool_name": "Bash", "args": {"command": "echo hi"}},
        config={"cwd": str(tmp_path)},
    )
    run_hooks(
        HookEvent.PRE_TOOL_USE,
        {"tool_name": "Read", "args": {"file_path": "a.py"}},
        config={"cwd": str(tmp_path)},
    )

    assert out.read_text(encoding="utf-8") == "PreToolUse\n"


def test_pre_tool_hook_nonzero_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    add_hook(
        event="PreToolUse",
        commands=[f'"{sys.executable}" -c "import sys; sys.stderr.write(\'blocked\'); sys.exit(2)"'],
        matcher="Bash",
    )

    with pytest.raises(HookError) as exc:
        run_hooks(
            HookEvent.PRE_TOOL_USE,
            {"tool_name": "Bash"},
            config={"cwd": str(tmp_path)},
        )

    assert "blocked" in str(exc.value)


def test_hook_add_and_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = hook_add.func(event="SessionStart", commands="echo hi", name="test-hook")
    assert "已添加 hook" in result

    read_output = hook_read.func()
    assert "SessionStart" in read_output
    assert "echo hi" in read_output
    assert "test-hook" in read_output


def test_invalid_event_rejected(tmp_path):
    with pytest.raises(ValueError, match="未知的hooks事件"):
        add_hook(event="Nope", commands=["echo hi"])
