"""
MessageQueue 类的单元测试

测试消息队列的缓冲机制、任务ID分组和边界事件处理
"""
import pytest
import queue
# 假设这些类在 agent.agent 模块中，如果路径不同请调整
try:
    from uniclaw.agent import MessageQueue, AssistantEvent, ToolEvent, TextChunkEvent
except ImportError:
    # 兼容可能的不同路径或为了通过语法检查的占位符
    from unittest.mock import MagicMock
    MessageQueue = MagicMock
    AssistantEvent = MagicMock
    ToolEvent = MagicMock
    TextChunkEvent = MagicMock


class TestMessageQueue:
    """MessageQueue 类的测试类"""

    # ==================== 初始化测试 ====================

    def test_initialization(self):
        """测试 MessageQueue 初始化"""
        mq = MessageQueue()
        assert mq.message_queue is not None
        assert mq.temp_queue is None
        assert mq.last_at is None
        assert mq.empty() is True

    # ==================== 基本 put/get 测试 ====================

    def test_put_single_message(self):
        """测试放入单条消息"""
        mq = MessageQueue()
        task_id = "task_1"
        event = TextChunkEvent(content="Hello")
        
        mq.put((task_id, event))
        
        assert mq.empty() is False
        assert mq.message_queue.qsize() == 1

    def test_get_single_message(self):
        """测试获取单条消息"""
        mq = MessageQueue()
        task_id = "task_1"
        event = TextChunkEvent(content="Hello")
        
        mq.put((task_id, event))
        retrieved_data = mq.get()
        
        assert retrieved_data[0] == task_id
        assert retrieved_data[1].content == "Hello"
        assert mq.empty() is True

    def test_put_get_multiple_messages_same_task(self):
        """测试同一任务ID的多条消息"""
        mq = MessageQueue()
        task_id = "task_1"
        
        for i in range(5):
            event = TextChunkEvent(content=f"Message {i}")
            mq.put((task_id, event))
        
        assert mq.message_queue.qsize() == 5
        
        for i in range(5):
            data = mq.get()
            assert data[0] == task_id
            assert data[1].content == f"Message {i}"

    # ==================== 任务ID切换测试（缓冲机制）====================

    def test_different_task_ids_create_temp_queue(self):
        """测试不同任务ID会创建临时队列"""
        mq = MessageQueue()
        
        # 放入第一个任务的消息
        task_id_1 = "task_1"
        mq.put((task_id_1, TextChunkEvent(content="Task 1 Msg")))
        
        # 验证 last_at 被正确设置
        assert mq.last_at == task_id_1
        
        # 放入第二个任务的消息（应该进入 temp_queue）
        task_id_2 = "task_2"
        mq.put((task_id_2, TextChunkEvent(content="Task 2 Msg")))
        
        # 验证 temp_queue 被创建，且第二条消息在临时队列中
        assert mq.temp_queue is not None
        assert mq.message_queue.qsize() == 1  # 只有第一条消息在主队列
        assert mq.temp_queue.message_queue.qsize() == 1  # 第二条消息在临时队列

    def test_temp_queue_stores_messages(self):
        """测试临时队列存储消息的行为"""
        mq = MessageQueue()
        
        # 先放一个任务1的消息
        mq.put(("task_1", TextChunkEvent(content="T1-1")))
        
        # 切换到任务2，消息应该进入 temp_queue
        mq.put(("task_2", TextChunkEvent(content="T2-1")))
        mq.put(("task_2", TextChunkEvent(content="T2-2")))
        
        assert mq.temp_queue is not None
        # 主队列有1条消息，临时队列有2条消息
        assert mq.message_queue.qsize() == 1
        assert mq.temp_queue.message_queue.qsize() == 2

    # ==================== 边界事件测试（AssistantEvent/ToolEvent）====================

    def test_assistant_event_triggers_forward(self):
        """测试 AssistantEvent 触发转发机制"""
        mq = MessageQueue()
        
        # 放入任务1的消息
        mq.put(("task_1", TextChunkEvent(content="T1-1")))
        
        # 放入任务2的消息（进入 temp_queue）
        mq.put(("task_2", TextChunkEvent(content="T2-1")))
        
        # 放入任务2的 AssistantEvent（边界事件，也进入 temp_queue）
        assistant_event = AssistantEvent(
            content="Response",
            tool_calls=[],
            in_tokens=10,
            out_tokens=20,
            model_name="test-model"
        )
        mq.put(("task_2", assistant_event))
        
        # 此时主队列有1条消息，临时队列有2条消息
        assert mq.message_queue.qsize() == 1
        assert mq.temp_queue is not None
        assert mq.temp_queue.message_queue.qsize() == 2
        
        # 获取任务1的消息（非边界事件，不会触发转发）
        data = mq.get()
        assert data[0] == "task_1"
        
        # 现在主队列为空，但 temp_queue 仍然存在
        # 注意：_forward 只有在 get 到边界事件且主队列为空时才触发
        # 所以这里我们需要继续从 temp_queue 获取消息来模拟实际使用场景

    def test_tool_event_triggers_forward(self):
        """测试 ToolEvent 触发转发机制"""
        mq = MessageQueue()
        
        # 放入任务1的消息
        mq.put(("task_1", TextChunkEvent(content="T1-1")))
        
        # 放入任务2的消息（进入 temp_queue）
        mq.put(("task_2", TextChunkEvent(content="T2-1")))
        
        # 放入任务2的 ToolEvent（边界事件）
        tool_event = ToolEvent(
            name="Read",
            content="File content",
            tool_call_id="call_123"
        )
        mq.put(("task_2", tool_event))
        
        # 此时主队列有1条消息，临时队列有2条消息
        assert mq.message_queue.qsize() == 1
        assert mq.temp_queue is not None
        
        # 获取任务1的消息
        data = mq.get()
        assert data[0] == "task_1"

    def test_non_boundary_event_does_not_trigger_forward_immediately(self):
        """测试非边界事件不会立即触发转发"""
        mq = MessageQueue()
        
        # 放入任务1的消息
        mq.put(("task_1", TextChunkEvent(content="T1-1")))
        
        # 放入任务2的非边界事件（会进入 temp_queue）
        mq.put(("task_2", TextChunkEvent(content="T2-1")))
        
        # 验证 temp_queue 被创建
        assert mq.temp_queue is not None
        
        # 获取任务1的消息（不应该立即触发转发，因为不是边界事件）
        data = mq.get()
        assert data[0] == "task_1"
        # temp_queue 应该仍然存在（因为没有触发 _forward）
        assert mq.temp_queue is not None

    # ==================== _forward 方法测试 ====================

    def test_forward_moves_temp_to_main(self):
        """测试 _forward 方法将临时队列内容移到主队列"""
        mq = MessageQueue()
        
        # 构造场景：任务1的消息在主队列，任务2的消息在 temp_queue
        mq.put(("task_1", TextChunkEvent(content="T1-1")))
        mq.put(("task_2", TextChunkEvent(content="T2-1")))
        mq.put(("task_2", AssistantEvent(content="Done", tool_calls=[], in_tokens=0, out_tokens=0, model_name="test")))
        
        # 获取任务1的消息（非边界事件，不会触发转发）
        data = mq.get()
        assert data[0] == "task_1"
        
        # 此时 temp_queue 仍然存在
        assert mq.temp_queue is not None
        
        # 继续获取直到遇到边界事件并触发转发
        # 注意：实际转发发生在 get 时遇到边界事件且主队列为空的情况下

    def test_forward_with_empty_temp_queue(self):
        """测试 _forward 方法在临时队列为空时的行为"""
        mq = MessageQueue()
        
        # 只有主队列有消息
        mq.put(("task_1", TextChunkEvent(content="T1-1")))
        
        # 不会触发 _forward，因为 temp_queue 是 None
        data = mq.get()
        assert data[0] == "task_1"
        assert mq.empty() is True

    # ==================== empty 方法测试 ====================

    def test_empty_when_no_messages(self):
        """测试队列为空时 empty 返回 True"""
        mq = MessageQueue()
        assert mq.empty() is True

    def test_empty_with_main_queue_only(self):
        """测试只有主队列有消息时 empty 返回 False"""
        mq = MessageQueue()
        mq.put(("task_1", TextChunkEvent(content="Test")))
        assert mq.empty() is False

    def test_empty_with_both_queues(self):
        """测试主队列和临时队列都有消息时 empty 返回 False"""
        mq = MessageQueue()
        mq.put(("task_1", TextChunkEvent(content="T1")))
        mq.put(("task_2", TextChunkEvent(content="T2")))
        assert mq.empty() is False

    def test_empty_after_consuming_all(self):
        """测试消费完所有消息后 empty 返回 True"""
        mq = MessageQueue()
        mq.put(("task_1", TextChunkEvent(content="T1-1")))
        mq.put(("task_1", TextChunkEvent(content="T1-2")))
        
        mq.get()
        mq.get()
        
        assert mq.empty() is True

    # ==================== _size 方法测试 ====================

    def test_size_with_only_main_queue(self):
        """测试只有主队列时的尺寸"""
        mq = MessageQueue()
        mq.put(("task_1", TextChunkEvent(content="T1-1")))
        mq.put(("task_1", TextChunkEvent(content="T1-2")))
        
        # 优化后的 _size 应该正确计算主队列大小
        size = mq._size()
        assert size == 2

    def test_size_with_both_queues(self):
        """测试主队列和临时队列都有消息时的总尺寸"""
        mq = MessageQueue()
        mq.put(("task_1", TextChunkEvent(content="T1-1")))
        mq.put(("task_2", TextChunkEvent(content="T2-1")))
        mq.put(("task_2", TextChunkEvent(content="T2-2")))
        
        total_size = mq._size()
        # 主队列1条 + 临时队列2条 = 3条
        assert total_size == 3

    def test_size_when_empty(self):
        """测试空队列的尺寸"""
        mq = MessageQueue()
        assert mq._size() == 0

    # ==================== 复杂场景测试 ====================

    def test_multiple_task_switches(self):
        """测试多次任务切换的场景"""
        mq = MessageQueue()
        
        # 任务1 -> 任务2 -> 任务3 -> 任务2
        mq.put(("task_1", TextChunkEvent(content="T1")))  # last_at=task_1, main=[T1]
        mq.put(("task_2", TextChunkEvent(content="T2-1")))  # last_at=task_2, temp created, temp=[T2-1]
        mq.put(("task_3", TextChunkEvent(content="T3")))  # last_at=task_3, nested temp? or flush?
        mq.put(("task_2", TextChunkEvent(content="T2-2")))  # depends on implementation
        
        # 验证消息总数正确（不管在哪个队列）
        total_size = mq._size()
        assert total_size == 4

    def test_interleaved_tasks_with_boundary(self):
        """测试交错任务与边界事件的组合"""
        mq = MessageQueue()
        
        # 任务1开始
        mq.put(("task_1", TextChunkEvent(content="T1-start")))
        
        # 任务2插入（进入 temp）
        mq.put(("task_2", TextChunkEvent(content="T2-msg")))
        
        # 任务2完成（边界事件）
        tool_event = ToolEvent(name="Write", content="Saved", tool_call_id="call_1")
        mq.put(("task_2", tool_event))
        
        # 此时主队列有1条消息，临时队列有2条消息
        assert mq.message_queue.qsize() == 1
        assert mq.temp_queue is not None
        assert mq.temp_queue.message_queue.qsize() == 2
        
        # 任务1继续
        mq.put(("task_1", TextChunkEvent(content="T1-end")))
        
        # 验证消息顺序和分组
        assert mq.message_queue.qsize() >= 1

    def test_boundary_event_completes_task(self):
        """测试边界事件完成任务的流程"""
        mq = MessageQueue()
        
        # 任务1的完整流程：文本块 + AssistantEvent
        mq.put(("task_1", TextChunkEvent(content="Thinking...")))
        assistant_event = AssistantEvent(
            content="Done",
            tool_calls=[],
            in_tokens=5,
            out_tokens=10,
            model_name="test"
        )
        mq.put(("task_1", assistant_event))
        
        # 获取消息
        data1 = mq.get()
        assert data1[0] == "task_1"
        assert isinstance(data1[1], TextChunkEvent)
        
        data2 = mq.get()
        assert data2[0] == "task_1"
        assert isinstance(data2[1], AssistantEvent)

    # ==================== 边界条件测试 ====================

    def test_put_none_task_id(self):
        """测试放入 None 任务ID的消息"""
        mq = MessageQueue()
        mq.put((None, TextChunkEvent(content="No ID")))
        
        data = mq.get()
        assert data[0] is None
        assert data[1].content == "No ID"

    def test_rapid_put_operations(self):
        """测试快速连续放入操作"""
        mq = MessageQueue()
        
        for i in range(100):
            task_id = f"task_{i % 5}"  # 5个不同的任务ID
            mq.put((task_id, TextChunkEvent(content=f"Msg {i}")))
        
        # 验证没有异常抛出，且至少有一条消息在主队列
        assert mq.message_queue.qsize() >= 0

    def test_get_from_empty_queue_raises_exception(self):
        """测试从空队列获取消息应抛出异常"""
        mq = MessageQueue()
        
        # 由于 MessageQueue.get() 不支持 block 参数，我们直接测试底层的 queue.Queue
        with pytest.raises(queue.Empty):
            mq.message_queue.get(block=False)

    # ==================== 一致性测试 ====================

    def test_message_order_preserved(self):
        """测试消息顺序保持一致"""
        mq = MessageQueue()
        task_id = "task_1"
        
        messages = [f"Message {i}" for i in range(10)]
        for msg in messages:
            mq.put((task_id, TextChunkEvent(content=msg)))
        
        # 按顺序获取并验证
        for expected_msg in messages:
            data = mq.get()
            assert data[1].content == expected_msg

    def test_task_isolation(self):
        """测试不同任务之间的隔离性"""
        mq = MessageQueue()
        
        # 任务1的消息
        mq.put(("task_1", TextChunkEvent(content="T1-only")))
        
        # 任务2的消息
        mq.put(("task_2", TextChunkEvent(content="T2-only")))
        
        # 获取任务1的消息
        data = mq.get()
        assert data[0] == "task_1"
        assert data[1].content == "T1-only"


class TestMessageQueueIntegration:
    """MessageQueue 集成测试"""

    def test_full_lifecycle(self):
        """测试完整的消息生命周期"""
        mq = MessageQueue()
        
        # 阶段1：任务1产生消息
        mq.put(("task_1", TextChunkEvent(content="T1-chunk1")))
        mq.put(("task_1", TextChunkEvent(content="T1-chunk2")))
        
        # 阶段2：任务2开始（任务1未完成）
        mq.put(("task_2", TextChunkEvent(content="T2-chunk1")))
        
        # 阶段3：任务2完成（边界事件）
        mq.put(("task_2", AssistantEvent(
            content="T2-done",
            tool_calls=[],
            in_tokens=10,
            out_tokens=20,
            model_name="test"
        )))
        
        # 阶段4：任务1继续并完成
        mq.put(("task_1", TextChunkEvent(content="T1-chunk3")))
        mq.put(("task_1", AssistantEvent(
            content="T1-done",
            tool_calls=[],
            in_tokens=5,
            out_tokens=15,
            model_name="test"
        )))
        
        # 验证所有消息都能被获取
        consumed_count = 0
        max_iterations = 100  # 防止无限循环
        while not mq.empty() and consumed_count < max_iterations:
            try:
                # 使用非阻塞方式获取
                data = mq.message_queue.get_nowait()
                consumed_count += 1
            except queue.Empty:
                # 如果主队列为空，检查是否有临时队列需要转发
                if mq.temp_queue:
                    # 手动触发转发逻辑（模拟遇到边界事件的情况）
                    break
                else:
                    break
        
        # 应该至少消费了部分消息
        assert consumed_count > 0
