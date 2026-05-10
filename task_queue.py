"""后台任务队列 — 支持长时间运行任务的后台执行和进度跟踪

参照 OpenClaw 架构：
- 权限策略：按工具类型分级，非全放行
- 维护巡检：定期检查卡住的任务，标记为 lost
- 通知策略：per-task 可配置 (done_only / state_changes / silent)
"""
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from agent import (
    AgentStatus,
    EndEvent,
    MultiAgent,
    PermissionRequestEvent,
    TextChunkEvent,
    ThinkingChunkEvent,
    ToolEvent,
    TooStartlEvent,
)

logger = logging.getLogger(__name__)

MAX_BACKGROUND_TASKS = 3
MAINTENANCE_INTERVAL = 60       # 维护巡检间隔（秒）
STALE_TASK_THRESHOLD = 600      # 任务卡住阈值（秒），10 分钟

# 只读类工具 — 后台任务自动放行
_READ_ONLY_TOOLS = frozenset({
    "Read", "ReadImage", "Glob", "Grep", "RunCode",
    "WebFetch", "WebSearch",
    "memory_save", "memory_delete", "memory_list", "memory_search",
    "schedule_create", "schedule_list", "schedule_remove", "schedule_toggle",
    "skill_list",
})


class NotifyPolicy(str, Enum):
    DONE_ONLY = "done_only"          # 仅完成/失败时通知（默认）
    STATE_CHANGES = "state_changes"  # 状态变化时通知
    SILENT = "silent"                # 静默，不通知


@dataclass
class BackgroundTaskInfo:
    task_id: str
    name: str
    prompt: str
    status: str = AgentStatus.PENDING.value
    submitted_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    result_summary: Optional[str] = None
    event_queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
    collected_text: list[str] = field(default_factory=list, repr=False)
    agent_task_ref: object = field(default=None, repr=False)
    config: dict = field(default_factory=dict, repr=False)
    notify_policy: str = NotifyPolicy.DONE_ONLY.value
    last_event_at: float = field(default_factory=time.time)


def _check_bg_permission(tool_call: dict, config: dict) -> tuple[bool, str]:
    """后台任务权限策略 — 按工具类型分级，非全放行。

    Returns:
        (允许, 原因) — 原因用于拒绝时告知 agent
    """
    name = tool_call.get("name", "")
    args = tool_call.get("args", {})

    # 只读工具 — 放行
    if name in _READ_ONLY_TOOLS:
        return True, ""

    # Edit 工具 — 检查是否在 CWD 下
    if name == "Edit":
        file_path = args.get("file_path", "")
        cwd = config.get("cwd", "")
        if cwd:
            try:
                if Path(file_path).resolve().is_relative_to(Path(cwd).resolve()):
                    return True, ""
            except (ValueError, OSError):
                pass
        return False, "后台任务不允许编辑 CWD 之外的文件"

    # Write 工具 — 检查是否在 CWD 下
    if name == "Write":
        file_path = args.get("file_path", "")
        cwd = config.get("cwd", "")
        if cwd:
            try:
                if Path(file_path).resolve().is_relative_to(Path(cwd).resolve()):
                    return True, ""
            except (ValueError, OSError):
                pass
        return False, "后台任务不允许写入 CWD 之外的文件"

    # Bash 工具 — 安全检查
    if name == "Bash":
        from tools.security import is_safe_bash
        cmd = args.get("command", "")
        if is_safe_bash(cmd):
            return True, ""
        return False, f"后台任务不允许执行危险命令: {cmd[:80]}"

    # 其他工具 — 拒绝
    return False, f"后台任务不允许使用工具: {name}"


class BackgroundTaskQueue:
    _instance: "BackgroundTaskQueue | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self.tasks: dict[str, BackgroundTaskInfo] = {}
        self.notify_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

        # 事件消费线程
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="bg-task-monitor"
        )
        self._monitor_thread.start()

        # 维护巡检线程
        self._maintenance_thread = threading.Thread(
            target=self._maintenance_loop, daemon=True, name="bg-task-maintenance"
        )
        self._maintenance_thread.start()

    @classmethod
    def get_instance(cls) -> "BackgroundTaskQueue":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 提交 ──────────────────────────────────────────────────

    def submit(
        self,
        prompt: str,
        config: dict,
        notify_policy: str = NotifyPolicy.DONE_ONLY.value,
    ) -> tuple[bool, str]:
        """提交后台任务。返回 (成功, 消息/任务ID)"""
        running_count = sum(
            1 for t in self.tasks.values()
            if t.status in (AgentStatus.PENDING.value, AgentStatus.RUNNING.value)
        )
        if running_count >= MAX_BACKGROUND_TASKS:
            return False, f"后台任务数已达上限 ({MAX_BACKGROUND_TASKS})，请等待任务完成后再提交"

        task_id = uuid.uuid4().hex[:12]
        name = prompt[:50].replace("\n", " ")
        info = BackgroundTaskInfo(
            task_id=task_id,
            name=name,
            prompt=prompt,
            notify_policy=notify_policy,
        )
        info.config = config
        self.tasks[task_id] = info

        multi_agent = MultiAgent.get_instance()
        agent_task = multi_agent.start(
            prompt,
            config=config,
            name=f"bg:{task_id[:8]}",
            bg_event_queue=info.event_queue,
        )
        info.agent_task_ref = agent_task
        info.status = AgentStatus.RUNNING.value
        return True, task_id

    # ── 事件消费线程 ──────────────────────────────────────────

    def _monitor_loop(self):
        """守护线程：轮询后台任务事件队列"""
        while not self._stop_event.is_set():
            for info in list(self.tasks.values()):
                if info.status not in (AgentStatus.PENDING.value, AgentStatus.RUNNING.value):
                    continue
                self._drain_task_events(info)
            self._stop_event.wait(0.5)

    def _drain_task_events(self, info: BackgroundTaskInfo):
        """非阻塞消费单个后台任务的所有待处理事件"""
        while True:
            try:
                _task, event = info.event_queue.get_nowait()
            except queue.Empty:
                break

            info.last_event_at = time.time()

            if isinstance(event, TextChunkEvent):
                info.collected_text.append(event.content)
            elif isinstance(event, ThinkingChunkEvent):
                pass
            elif isinstance(event, PermissionRequestEvent):
                # 按权限策略处理，而非全放行
                permitted, reason = _check_bg_permission(event.tool_call, info.config)
                if not permitted:
                    info.collected_text.append(f"\n[权限拒绝] {reason}\n")
                event.content = permitted
                event.return_event.set()
            elif isinstance(event, EndEvent):
                if event.depth == 0:
                    self._finalize_task(info, AgentStatus.COMPLETED.value)
            elif isinstance(event, (ToolEvent, TooStartlEvent)):
                # 记录工具调用到 collected_text 以便审计
                if isinstance(event, ToolEvent):
                    info.collected_text.append(f"\n[工具] {event.name}: {event.content[:200]}\n")

        # 检查底层任务是否失败
        if info.agent_task_ref and info.status == AgentStatus.RUNNING.value:
            agent_status = info.agent_task_ref.status
            if agent_status == AgentStatus.FAILED.value:
                info.result_summary = info.agent_task_ref.result or "任务执行失败"
                self._finalize_task(info, AgentStatus.FAILED.value)

    def _finalize_task(self, info: BackgroundTaskInfo, status: str):
        """统一的任务终结处理"""
        info.status = status
        info.completed_at = time.time()
        if status == AgentStatus.COMPLETED.value:
            info.result_summary = "".join(info.collected_text)[-500:]
        self._emit_notification(info)

    def _emit_notification(self, info: BackgroundTaskInfo):
        """根据通知策略决定是否发送通知"""
        policy = info.notify_policy
        if policy == NotifyPolicy.SILENT.value:
            return
        # done_only 和 state_changes 都在终结时通知
        self.notify_queue.put((info.task_id, info.status, info.result_summary or ""))

    # ── 维护巡检线程 ──────────────────────────────────────────

    def _maintenance_loop(self):
        """守护线程：定期检查卡住的任务，参照 OpenClaw 的 maintenance sweep"""
        while not self._stop_event.is_set():
            self._stop_event.wait(MAINTENANCE_INTERVAL)
            if self._stop_event.is_set():
                break
            try:
                self._sweep_stale_tasks()
            except Exception as e:
                logger.error(f"维护巡检失败: {e}")

    def _sweep_stale_tasks(self):
        """检查所有 running 任务，超时的标记为 lost"""
        now = time.time()
        for info in list(self.tasks.values()):
            if info.status != AgentStatus.RUNNING.value:
                continue

            elapsed = now - info.last_event_at
            if elapsed < STALE_TASK_THRESHOLD:
                continue

            # 最后一次检查：底层 agent 是否已经结束
            if info.agent_task_ref:
                agent_status = info.agent_task_ref.status
                if agent_status == AgentStatus.COMPLETED.value:
                    self._finalize_task(info, AgentStatus.COMPLETED.value)
                    continue
                elif agent_status == AgentStatus.FAILED.value:
                    info.result_summary = info.agent_task_ref.result or "任务执行失败"
                    self._finalize_task(info, AgentStatus.FAILED.value)
                    continue
                elif agent_status in (
                    AgentStatus.CANCELLED.value, AgentStatus.LOST.value
                ):
                    info.status = agent_status
                    info.completed_at = now
                    continue

            # 真的卡住了 — 标记为 lost
            logger.warning(f"后台任务 {info.task_id} 超时 ({elapsed:.0f}s)，标记为 lost")
            info.result_summary = f"任务超时无响应 ({elapsed:.0f}s)，已标记为丢失"
            self._finalize_task(info, AgentStatus.LOST.value)

    # ── 查询接口 ──────────────────────────────────────────────

    def check_notifications(self) -> list[tuple[str, str, str]]:
        """非阻塞获取所有待通知项。返回 [(task_id, status, summary)]"""
        notifications = []
        while True:
            try:
                notifications.append(self.notify_queue.get_nowait())
            except queue.Empty:
                break
        return notifications

    def list_tasks(self) -> list[BackgroundTaskInfo]:
        return sorted(self.tasks.values(), key=lambda t: t.submitted_at, reverse=True)

    def view_task(self, task_id: str) -> Optional[str]:
        info = self.tasks.get(task_id)
        if info is None:
            return None
        return "".join(info.collected_text)

    def cancel_task(self, task_id: str) -> bool:
        info = self.tasks.get(task_id)
        if info is None:
            return False
        if info.status not in (AgentStatus.PENDING.value, AgentStatus.RUNNING.value):
            return False
        if info.agent_task_ref:
            info.agent_task_ref.cancel_event.set()
        info.status = AgentStatus.CANCELLED.value
        info.completed_at = time.time()
        return True
