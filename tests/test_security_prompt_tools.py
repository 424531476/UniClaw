from types import SimpleNamespace

import console.ui


from tools.security import (
    clear_llm_safe_prompt,
    edit_llm_safe_prompt,
    llm_safe_check,
    read_llm_safe_prompt,
    write_llm_safe_prompt,
)


def test_llm_safe_prompt_tools_persist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert read_llm_safe_prompt.func() == "当前未设置 llm_safe_check 注入提示词。"

    assert (
        write_llm_safe_prompt.func("允许 git push")
        == "已保存 llm_safe_check 注入提示词。"
    )
    assert read_llm_safe_prompt.func() == "允许 git push"

    assert (
        edit_llm_safe_prompt.func("允许 docker ps")
        == "已编辑并保存 llm_safe_check 注入提示词。"
    )
    assert read_llm_safe_prompt.func() == "允许 docker ps"

    assert clear_llm_safe_prompt.func() == "已清除 llm_safe_check 注入提示词。"
    assert read_llm_safe_prompt.func() == "当前未设置 llm_safe_check 注入提示词。"


def test_llm_safe_check_uses_injected_system_prompt(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(console.ui.TUISpinner, "start", lambda message: 1)
    monkeypatch.setattr(console.ui.TUISpinner, "stop", lambda wait_id=None: None)

    captured_messages = {}

    def fake_chat(
        messages, model_name, temperature, max_tokens, enable_thinking, thinking
    ):
        captured_messages["messages"] = messages
        return SimpleNamespace(content='{"is_safe": true, "explanation": "OK"}')

    monkeypatch.setattr("llm.chat", fake_chat, raising=True)

    tc = {"name": "DummyTool", "args": {"param": "value"}}
    config = {
        "mini_model_name": "gpt-3.5-mini",
        "llm_safe_system_prompt": "允许 git push 操作",
    }

    is_safe, explanation = llm_safe_check(tc, config)

    assert is_safe is True
    assert explanation == "OK"
    assert "允许 git push 操作" in captured_messages["messages"][0]["content"]


def test_llm_safe_check_uses_config_prompt(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(console.ui.TUISpinner, "start", lambda message: 1)
    monkeypatch.setattr(console.ui.TUISpinner, "stop", lambda wait_id=None: None)

    captured_messages = {}

    def fake_chat(
        messages, model_name, temperature, max_tokens, enable_thinking, thinking
    ):
        captured_messages["messages"] = messages
        return SimpleNamespace(content='{"is_safe": true, "explanation": "OK"}')

    monkeypatch.setattr("llm.chat", fake_chat, raising=True)

    tc = {"name": "DummyTool", "args": {"param": "value"}}
    config = {
        "mini_model_name": "gpt-3.5-mini",
        "llm_safe_system_prompt": "允许 docker logs 操作",
    }

    is_safe, explanation = llm_safe_check(tc, config)

    assert is_safe is True
    assert explanation == "OK"
    assert "允许 docker logs 操作" in captured_messages["messages"][0]["content"]
