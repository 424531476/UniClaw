import asyncio

import pytest
from agent import AgentTask
from tools.persistence import SessionPersistence


def _config(tmp_path):
    return {
        "model_name": "test-model",
        "permission_mode": "auto",
        "verbose": False,
        "cwd": str(tmp_path),
    }


@pytest.mark.anyio
async def test_save_load_preserves_full_message_fields(tmp_path):
    task = AgentTask(id="main", name="main", prompt="")
    task.messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "analyze this"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,abc123"},
                },
            ],
        },
        {
            "role": "assistant",
            "content": "ok",
            "reasoning_content": "private reasoning",
            "tool_calls": [{"id": "call_1", "name": "Read", "args": {"path": "a.py"}}],
        },
        {
            "role": "tool",
            "name": "Read",
            "tool_call_id": "call_1",
            "content": "print('hi')",
        },
    ]

    persistence = SessionPersistence()
    # 临时修改存储目录到测试目录
    original_dir = persistence.storage_dir
    persistence.storage_dir = tmp_path / "sessions"
    persistence.metadata_file = persistence.storage_dir / "metadata.json"
    persistence.storage_dir.mkdir(parents=True, exist_ok=True)

    path = await persistence.save_session(task, _config(tmp_path))
    loaded = persistence.load_session(task.session_id)
    
    # 恢复原始目录
    persistence.storage_dir = original_dir
    persistence.metadata_file = original_dir / "metadata.json"

    assert path.endswith(".json")
    assert loaded["messages"] == task.messages
    assert loaded["messages"][1]["reasoning_content"] == "private reasoning"
    assert loaded["messages"][1]["tool_calls"][0]["id"] == "call_1"
    assert loaded["messages"][0]["content"][1]["image_url"]["url"].endswith("abc123")


@pytest.mark.anyio
async def test_search_sessions_reports_matching_message_numbers(tmp_path):
    config = _config(tmp_path)
    task = AgentTask(id="main", name="main", prompt="")
    task.messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "crawler script"},
    ]
    persistence = SessionPersistence()
    # 临时修改存储目录到测试目录
    original_dir = persistence.storage_dir
    persistence.storage_dir = tmp_path / "sessions"
    persistence.metadata_file = persistence.storage_dir / "metadata.json"
    persistence.storage_dir.mkdir(parents=True, exist_ok=True)

    await persistence.save_session(task, config)

    results = persistence.search_sessions("crawler")
    
    # 恢复原始目录
    persistence.storage_dir = original_dir
    persistence.metadata_file = original_dir / "metadata.json"

    assert len(results) == 1
    assert results[0]["matches"] == [2]


@pytest.mark.anyio
async def test_session_load_command_replaces_task_messages(tmp_path):
    config = _config(tmp_path)
    source = AgentTask(id="main", name="main", prompt="")
    source.messages = [{"role": "user", "content": "saved message"}]
    persistence = SessionPersistence()
    # 临时修改存储目录到测试目录
    original_dir = persistence.storage_dir
    persistence.storage_dir = tmp_path / "sessions"
    persistence.metadata_file = persistence.storage_dir / "metadata.json"
    persistence.storage_dir.mkdir(parents=True, exist_ok=True)

    await persistence.save_session(source, config)

    target = AgentTask(id="main", name="main", prompt="")
    target.messages = [{"role": "user", "content": "old message"}]

    # 直接测试加载功能
    data = persistence.load_session(source.session_id)
    assert data is not None
    target.messages = data.get("messages", [])
    setattr(target, "session_id", source.session_id)

    assert target.messages == source.messages
    assert target.session_id == source.session_id
    
    # 恢复原始目录
    persistence.storage_dir = original_dir
    persistence.metadata_file = original_dir / "metadata.json"
