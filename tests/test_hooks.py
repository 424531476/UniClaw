import json
import sys

import pytest

from hook_manager import (
    HookError,
    HookEvent,
    get_hooks_path,
    run_hooks,
    write_hooks_config,
)
from tools.hooks import hook_read, hook_validate, hook_write


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
    config = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": _python_append_command(out),
                        }
                    ],
                }
            ]
        }
    }
    write_hooks_config(json.dumps(config), str(tmp_path))

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
    config = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{sys.executable}" -c "import sys; sys.stderr.write(\'blocked\'); sys.exit(2)"',
                        }
                    ],
                }
            ]
        }
    }
    write_hooks_config(json.dumps(config), str(tmp_path))

    with pytest.raises(HookError) as exc:
        run_hooks(
            HookEvent.PRE_TOOL_USE,
            {"tool_name": "Bash"},
            config={"cwd": str(tmp_path)},
        )

    assert "blocked" in str(exc.value)


def test_hook_tools_read_validate_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = json.dumps({"hooks": {"SessionStart": [{"command": "echo hi"}]}})

    assert hook_validate.func(content) == "hooks config is valid"
    result = hook_write.func(content, config={"cwd": str(tmp_path)})
    assert str(get_hooks_path(str(tmp_path))) in result
    assert hook_read.func(config={"cwd": str(tmp_path)}) == (
        json.dumps(json.loads(content), indent=2, ensure_ascii=False) + "\n"
    )


def test_invalid_hook_config_rejected(tmp_path):
    with pytest.raises(ValueError):
        write_hooks_config(json.dumps({"hooks": {"Nope": []}}), str(tmp_path))
