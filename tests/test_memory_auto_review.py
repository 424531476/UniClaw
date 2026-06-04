from agent import AgentTask
from tools.memory import auto_review
from utils.message import MessageRole


class _Response:
    def __init__(self, content: str):
        self.content = content


def _task_with_user_messages(count: int) -> AgentTask:
    task = AgentTask(id="main", name="main", prompt="")
    for index in range(count):
        task.messages.append({"role": MessageRole.USER, "content": f"user preference {index}"})
        task.messages.append({"role": MessageRole.ASSISTANT, "content": "ok", "tool_calls": []})
    return task


def test_auto_review_skips_before_ten_user_messages(monkeypatch):
    calls = []

    def fake_chat(*args, **kwargs):
        calls.append((args, kwargs))
        return _Response('{"memories": []}')

    monkeypatch.setattr(auto_review, "chat", fake_chat)

    saved = auto_review.review_and_save_if_due(
        _task_with_user_messages(9), {"model_name": "test-model"}
    )

    assert saved == []
    assert calls == []


def test_auto_review_saves_new_memory_with_memory_save(monkeypatch):
    task = _task_with_user_messages(10)
    saved_args = []

    def fake_chat(*args, **kwargs):
        return _Response(
            """{
                "memories": [{
                    "name": "feedback-memory-save-tool",
                    "type": "feedback",
                    "description": "Use memory_save for durable memory writes",
                    "content": "Use the existing memory_save tool instead of writing a fixed path.",
                    "confidence": 1
                }]
            }"""
        )

    def fake_memory_save(**kwargs):
        saved_args.append(kwargs)
        return "记忆 保存成功: 'feedback-memory-save-tool' [feedback/user]"

    monkeypatch.setattr(auto_review, "chat", fake_chat)
    monkeypatch.setattr(auto_review.memory_save, "func", fake_memory_save)

    saved = auto_review.review_and_save_if_due(task, {"model_name": "test-model"})
    saved_again = auto_review.review_and_save_if_due(task, {"model_name": "test-model"})

    assert [memory.name for memory in saved] == ["feedback-memory-save-tool"]
    assert saved_again == []
    assert saved_args[0]["scope"] == "user"
    assert saved_args[0]["type"] == "feedback"
    assert task.memory_review_user_count == 10


def test_auto_review_uses_chat_fallback_when_memory_save_is_silent(monkeypatch):
    task = _task_with_user_messages(10)
    chat_calls = []
    save_calls = []

    def fake_chat(messages, *args, **kwargs):
        chat_calls.append(messages)
        if len(chat_calls) == 1:
            return _Response(
                """{
                    "memories": [{
                        "name": "feedback-silent-memory-save",
                        "type": "feedback",
                        "description": "Fallback for silent memory_save results",
                        "content": "If memory_save has no observable result, copy messages and use chat fallback.",
                        "confidence": 1
                    }]
                }"""
            )
        return _Response(
            """{
                "memories": [{
                    "name": "feedback-silent-memory-save",
                    "type": "feedback",
                    "description": "Fallback for silent memory_save results",
                    "content": "If memory_save has no observable result, copy messages and use chat fallback.",
                    "confidence": 1
                }]
            }"""
        )

    def fake_memory_save(**kwargs):
        save_calls.append(kwargs)
        if len(save_calls) == 1:
            return ""
        return "记忆 保存成功: 'feedback-silent-memory-save' [feedback/user]"

    monkeypatch.setattr(auto_review, "chat", fake_chat)
    monkeypatch.setattr(auto_review.memory_save, "func", fake_memory_save)

    saved = auto_review.review_and_save_if_due(task, {"model_name": "test-model"})

    assert [memory.name for memory in saved] == ["feedback-silent-memory-save"]
    assert len(chat_calls) == 2
    assert len(save_calls) == 2
    assert chat_calls[1][-1]["content"].startswith("[system] memory_save did not return")
