import pytest
from uniclaw.agent import AgentTask
from uniclaw.tools.session.session_manager import SessionManager


def _config(tmp_path):
    return {
        "model_name": "test-model",
        "mini_model_name": "test-model",
        "OPENAI_API_KEY": "test",
        "OPENAI_BASE_URL": "",
        "permission_mode": "auto",
        "verbose": False,
        "cwd": str(tmp_path),
    }


@pytest.fixture(autouse=True)
def _patch_session_dir(tmp_path, monkeypatch):
    """将 SessionManager 的存储目录重定向到测试临时目录。"""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(SessionManager, "_default_dir", staticmethod(lambda: session_dir))


@pytest.mark.asyncio
async def test_save_load_preserves_full_message_fields(tmp_path):
    task = AgentTask(name="main", prompt="")
    task.session.add_user_message(
        content=[
            {"type": "text", "text": "analyze this"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,abc123"},
            },
        ]
    )
    task.session.add_assistant_message(
        content="ok",
        model_name="test-model",
        usage_meta={},
        reasoning_content="private reasoning",
        tool_calls=[{"id": "call_1", "name": "Read", "args": {"path": "a.py"}}],
    )
    task.session.add_tool_call_message(
        content="print('hi')",
        tool_call={"name": "Read", "tool_call_id": "call_1", "args": {}},
    )

    await SessionManager.save_session(task, _config(tmp_path))
    loaded = SessionManager.load_session(task.session.id)

    assert loaded is not None
    messages = loaded.to_messages()
    assert len(messages) == 3
    assert messages[1]["reasoning_content"] == "private reasoning"
    assert messages[1]["tool_calls"][0]["id"] == "call_1"
    assert messages[0]["content"][1]["image_url"]["url"].endswith("abc123")


@pytest.mark.asyncio
async def test_search_sessions_reports_matching_message_numbers(tmp_path):
    config = _config(tmp_path)
    task = AgentTask(name="main", prompt="")
    task.session.add_user_message(content="hello")
    task.session.add_assistant_message(
        content="crawler script", model_name="test-model", usage_meta={}
    )

    await SessionManager.save_session(task, config)

    results = SessionManager.search_sessions("crawler")

    assert len(results) == 1
    assert len(results[0]["matches"]) >= 1


@pytest.mark.asyncio
async def test_session_load_command_replaces_task_messages(tmp_path):
    config = _config(tmp_path)
    source = AgentTask(name="main", prompt="")
    source.session.add_user_message(content="saved message")

    await SessionManager.save_session(source, config)

    target = AgentTask(name="main", prompt="")
    target.session.add_user_message(content="old message")

    # 直接测试加载功能
    loaded = SessionManager.load_session(source.session.id)
    assert loaded is not None
    target.session.replace_messages(loaded.to_messages())

    assert target.session.to_messages() == loaded.to_messages()
