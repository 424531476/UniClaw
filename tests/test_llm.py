"""
LLM 调用层的单元测试
"""
import pytest
from unittest.mock import patch, MagicMock
from uniclaw.llm import (
    _build_extra_body,
    _messages_to_openai,
    tool_to_openai,
    stream,
    chat,
    achat,
    StreamChunk,
    AIMessage,
    UsageMeta,
)


# ── 辅助函数测试 ──────────────────────────────────────────────


class TestBuildExtraBody:
    """extra_body 构建测试"""

    def test_google_api_returns_none(self):
        result = _build_extra_body(
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            enable_thinking=True,
            thinking=True,
        )
        assert result is None

    def test_thinking_enabled(self):
        result = _build_extra_body(
            "https://api.openai.com/v1/",
            enable_thinking=True,
            thinking=True,
        )
        assert result == {
            "enable_thinking": True,
            "thinking": {"type": "enabled"},
        }

    def test_thinking_disabled(self):
        result = _build_extra_body(
            "https://api.openai.com/v1/",
            enable_thinking=True,
            thinking=False,
        )
        assert result == {
            "enable_thinking": True,
            "thinking": {"type": "disabled"},
        }

    def test_openrouter_thinking_disabled_adds_reasoning(self):
        result = _build_extra_body(
            "https://openrouter.ai/api/v1/",
            enable_thinking=False,
            thinking=False,
        )
        assert result == {
            "enable_thinking": False,
            "thinking": {"type": "disabled"},
            "reasoning": {"effort": "none"},
        }


class TestToolToOpenai:
    """工具格式转换测试"""

    def test_conversion(self):
        tool = MagicMock()
        tool.name = "test_tool"
        tool.description = "A test tool"
        tool.parameters = {"type": "object", "properties": {}}

        result = tool_to_openai(tool)
        assert result == {
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "A test tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }


class TestMessagesToOpenai:
    """消息格式转换测试"""

    def test_dict_message(self):
        messages = [{"role": "user", "content": "hello"}]
        result = _messages_to_openai(messages)
        assert result == [{"role": "user", "content": "hello"}]

    def test_object_with_content(self):
        class FakeMessage:
            def __init__(self):
                self.content = "hello"
                self.role = "user"
        msg = FakeMessage()
        result = _messages_to_openai([msg])
        assert result == [{"role": "user", "content": "hello"}]

    def test_filter_none_values(self):
        messages = [{"role": "user", "content": "hello", "extra": None}]
        result = _messages_to_openai(messages)
        assert "extra" not in result[0]


# ── 多轮对话带工具测试 ────────────────────────────────────────


class TestStreamWithTools:
    """流式调用带工具的测试"""

    def _make_mock_stream(self, chunks):
        """创建模拟的流式响应"""
        for chunk in chunks:
            yield chunk

    def test_multi_turn_with_tool_calls(self):
        """测试多轮对话：用户提问 -> AI 调用工具 -> 工具返回结果 -> AI 回答"""
        # 第一轮：AI 返回 tool_call
        tool_call_chunk = MagicMock()
        tool_call_chunk.choices = [MagicMock()]
        tool_call_chunk.choices[0].delta.content = ""
        tool_call_chunk.choices[0].delta.tool_calls = [MagicMock()]
        tool_call_chunk.choices[0].delta.tool_calls[0].index = 0
        tool_call_chunk.choices[0].delta.tool_calls[0].id = "call_123"
        tool_call_chunk.choices[0].delta.tool_calls[0].function = MagicMock()
        tool_call_chunk.choices[0].delta.tool_calls[0].function.name = "get_weather"
        tool_call_chunk.choices[0].delta.tool_calls[0].function.arguments = '{"city": "Beijing"}'

        usage_chunk = MagicMock()
        usage_chunk.choices = []
        usage_chunk.usage = MagicMock()
        usage_chunk.usage.prompt_tokens = 100
        usage_chunk.usage.completion_tokens = 20
        usage_chunk.model = "gpt-4"

        with patch("uniclaw.llm.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = self._make_mock_stream([
                tool_call_chunk,
                usage_chunk,
            ])

            messages = [{"role": "user", "content": "北京天气怎么样？"}]
            tools = [MagicMock(name="get_weather", description="获取天气", parameters={})]

            chunks = list(stream(
                messages=messages,
                tools=tools,
                model_name="gpt-4",
                openai_api_base="https://api.openai.com/v1/",
                openai_api_key="test-key",
            ))

            # 验证返回了 tool_calls
            assert len(chunks) > 0
            tool_chunk = chunks[-1]
            assert len(tool_chunk.tool_calls) == 1
            assert tool_chunk.tool_calls[0]["function"]["name"] == "get_weather"
            assert tool_chunk.tool_calls[0]["id"] == "call_123"

    def test_extra_body_passed_to_api(self):
        """测试 extra_body 正确传递到 API"""
        content_chunk = MagicMock()
        content_chunk.choices = [MagicMock()]
        content_chunk.choices[0].delta.content = "你好"
        content_chunk.choices[0].delta.tool_calls = None

        usage_chunk = MagicMock()
        usage_chunk.choices = []
        usage_chunk.usage = MagicMock()
        usage_chunk.usage.prompt_tokens = 50
        usage_chunk.usage.completion_tokens = 10
        usage_chunk.model = "gpt-4"

        with patch("uniclaw.llm.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = self._make_mock_stream([
                content_chunk,
                usage_chunk,
            ])

            messages = [{"role": "user", "content": "你好"}]

            list(stream(
                messages=messages,
                model_name="gpt-4",
                openai_api_base="https://api.openai.com/v1/",
                openai_api_key="test-key",
                enable_thinking=True,
                thinking=True,
            ))

            # 验证 kwargs 中包含 extra_body
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert "extra_body" in call_kwargs
            assert call_kwargs["extra_body"]["enable_thinking"] is True
            assert call_kwargs["extra_body"]["thinking"]["type"] == "enabled"

    def test_google_api_no_extra_body(self):
        """测试 Google API 不传递 extra_body"""
        content_chunk = MagicMock()
        content_chunk.choices = [MagicMock()]
        content_chunk.choices[0].delta.content = "你好"
        content_chunk.choices[0].delta.tool_calls = None

        usage_chunk = MagicMock()
        usage_chunk.choices = []
        usage_chunk.usage = MagicMock()
        usage_chunk.usage.prompt_tokens = 50
        usage_chunk.usage.completion_tokens = 10
        usage_chunk.model = "gemini-pro"

        with patch("uniclaw.llm.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = self._make_mock_stream([
                content_chunk,
                usage_chunk,
            ])

            messages = [{"role": "user", "content": "你好"}]

            list(stream(
                messages=messages,
                model_name="gemini-pro",
                openai_api_base="https://generativelanguage.googleapis.com/v1beta/openai/",
                openai_api_key="test-key",
            ))

            # 验证 kwargs 中不包含 extra_body
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert "extra_body" not in call_kwargs


class TestChatWithTools:
    """同步调用带工具的测试"""

    def test_chat_with_tool_calls(self):
        """测试同步调用返回 tool_calls"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_response.choices[0].message.tool_calls = [MagicMock()]
        mock_response.choices[0].message.tool_calls[0].id = "call_456"
        mock_response.choices[0].message.tool_calls[0].function.name = "search"
        mock_response.choices[0].message.tool_calls[0].function.arguments = '{"query": "test"}'
        mock_response.choices[0].message.reasoning_content = None
        mock_response.choices[0].message.reasoning = None
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 30
        mock_response.model = "gpt-4"

        with patch("uniclaw.llm.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            messages = [{"role": "user", "content": "搜索测试"}]
            tools = [MagicMock(name="search", description="搜索", parameters={})]

            result = chat(
                messages=messages,
                tools=tools,
                model_name="gpt-4",
                openai_api_base="https://api.openai.com/v1/",
                openai_api_key="test-key",
            )

            assert isinstance(result, AIMessage)
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0]["function"]["name"] == "search"
            assert result.tool_calls[0]["id"] == "call_456"

    def test_chat_extra_body_passed(self):
        """测试同步调用 extra_body 传递"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "回答"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.reasoning_content = None
        mock_response.choices[0].message.reasoning = None
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 10
        mock_response.model = "gpt-4"

        with patch("uniclaw.llm.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            chat(
                messages=[{"role": "user", "content": "你好"}],
                model_name="gpt-4",
                openai_api_base="https://api.openai.com/v1/",
                openai_api_key="test-key",
                enable_thinking=True,
                thinking=False,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert "extra_body" in call_kwargs
            assert call_kwargs["extra_body"]["thinking"]["type"] == "disabled"


@pytest.mark.asyncio
class TestAchatWithTools:
    """异步调用带工具的测试"""

    async def test_achat_with_tool_calls(self):
        """测试异步调用返回 tool_calls"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_response.choices[0].message.tool_calls = [MagicMock()]
        mock_response.choices[0].message.tool_calls[0].id = "call_789"
        mock_response.choices[0].message.tool_calls[0].function.name = "calculate"
        mock_response.choices[0].message.tool_calls[0].function.arguments = '{"expr": "1+1"}'
        mock_response.choices[0].message.reasoning_content = None
        mock_response.choices[0].message.reasoning = None
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 80
        mock_response.usage.completion_tokens = 20
        mock_response.model = "gpt-4"

        with patch("uniclaw.llm.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            # 模拟异步上下文管理器
            async def mock_create(**kwargs):
                return mock_response
            mock_client.chat.completions.create = mock_create

            messages = [{"role": "user", "content": "计算 1+1"}]
            tools = [MagicMock(name="calculate", description="计算", parameters={})]

            result = await achat(
                messages=messages,
                tools=tools,
                model_name="gpt-4",
                openai_api_base="https://api.openai.com/v1/",
                openai_api_key="test-key",
            )

            assert isinstance(result, AIMessage)
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0]["function"]["name"] == "calculate"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
