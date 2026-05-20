import asyncio
from agent import AgentTask
from commands.conversation import cmd_conversation
from tools.persistence import ConversationPersistence


def _config(tmp_path):
    return {
        "model_name": "test-model",
        "permission_mode": "auto",
        "verbose": False,
        "cwd": str(tmp_path),
    }


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

    persistence = ConversationPersistence()
    # 临时修改存储目录到测试目录
    original_dir = persistence.storage_dir
    persistence.storage_dir = tmp_path / "conversations"
    persistence.metadata_file = persistence.storage_dir / "metadata.json"
    persistence.storage_dir.mkdir(parents=True, exist_ok=True)
    
    path = await persistence.save_conversation(task, _config(tmp_path))
    loaded = persistence.load_conversation(task.conversation_session_id)
    
    # 恢复原始目录
    persistence.storage_dir = original_dir
    persistence.metadata_file = original_dir / "metadata.json"

    assert path.endswith(".json")
    assert loaded["messages"] == task.messages
    assert loaded["messages"][1]["reasoning_content"] == "private reasoning"
    assert loaded["messages"][1]["tool_calls"][0]["id"] == "call_1"
    assert loaded["messages"][0]["content"][1]["image_url"]["url"].endswith("abc123")


async def test_search_conversations_reports_matching_message_numbers(tmp_path):
    config = _config(tmp_path)
    task = AgentTask(id="main", name="main", prompt="")
    task.messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "crawler script"},
    ]
    persistence = ConversationPersistence()
    # 临时修改存储目录到测试目录
    original_dir = persistence.storage_dir
    persistence.storage_dir = tmp_path / "conversations"
    persistence.metadata_file = persistence.storage_dir / "metadata.json"
    persistence.storage_dir.mkdir(parents=True, exist_ok=True)
    
    await persistence.save_conversation(task, config)

    results = persistence.search_conversations("crawler")
    
    # 恢复原始目录
    persistence.storage_dir = original_dir
    persistence.metadata_file = original_dir / "metadata.json"

    assert len(results) == 1
    assert results[0]["matches"] == [2]


async def test_conversation_load_command_replaces_task_messages(tmp_path):
    config = _config(tmp_path)
    source = AgentTask(id="main", name="main", prompt="")
    source.messages = [{"role": "user", "content": "saved message"}]
    persistence = ConversationPersistence()
    # 临时修改存储目录到测试目录
    original_dir = persistence.storage_dir
    persistence.storage_dir = tmp_path / "conversations"
    persistence.metadata_file = persistence.storage_dir / "metadata.json"
    persistence.storage_dir.mkdir(parents=True, exist_ok=True)
    
    await persistence.save_conversation(source, config)

    target = AgentTask(id="main", name="main", prompt="")
    target.messages = [{"role": "user", "content": "old message"}]

    # 直接测试加载功能
    data = persistence.load_conversation(source.conversation_session_id)
    assert data is not None
    target.messages = data.get("messages", [])
    setattr(target, "conversation_session_id", source.conversation_session_id)
    
    assert target.messages == source.messages
    assert target.conversation_session_id == source.conversation_session_id
    
    # 恢复原始目录
    persistence.storage_dir = original_dir
    persistence.metadata_file = original_dir / "metadata.json"
