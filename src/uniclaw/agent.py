from __future__ import annotations

import asyncio
from enum import StrEnum
import inspect
import os
import threading
import difflib
import queue
import time
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
import uuid

from uniclaw.tools.registry import search_tools
from uniclaw.utils.constants import SYSTEM_PREFIX
from uniclaw.provider import astream
from uniclaw.tools.session.session import StreamChunk
from uniclaw.compaction import maybe_compact
from uniclaw.tools import get_core_tools, get_tools
from uniclaw.utils.message import MessageRole, extract_text
from dataclasses import dataclass, field
from uniclaw.context import build_system_prompt, get_base_system_prompt
from uniclaw.config import Permissions, AppConfig
from uniclaw.tools.ask import AskUserQuestion

if TYPE_CHECKING:
    from uniclaw.tools.session.session import Session
    from uniclaw.tools.todolist import TodoList
from uniclaw.tools.fs import Edit, Write
from uniclaw.tools.base import tc_name as _tc_name, tc_args as _tc_args, Tool
from uniclaw.tools.multi_agent.sub_agent import AgentDefinition
from uniclaw.tools.multi_agent.tools import (
    check_agent_result,
    send_message,
    agent_close,
)
from uniclaw.tools.shell import Bash
from uniclaw.utils.checkpoint import create_checkpoint
from uniclaw.utils.git import (
    create_worktree,
    get_git_root,
    remove_worktree,
)
from uniclaw.utils.truncation import truncate_text_by_lines
from uniclaw.utils.logger import get_logger
from uniclaw.utils.format import format_args_for_display
from uniclaw.tools.hooks.hook_manager import HookError, HookEvent, run_hooks
import traceback

from uniclaw.utils.wrapper import error_catch

# 只读工具去重:相同 (name, args) 且结果相同时省略重复内容
DEDUP_TOOLS = frozenset({"Read", "Glob", "Grep", "webFetch", "webSearch"})
DEDUP_MIN_CHARS = 500  # 结果超过此长度才去重


class ReturnEvent:

    def __init__(self, default_content=None):
        self.content = default_content
        self.return_event = asyncio.Event()


@dataclass
class UserEvent:
    content: str


@dataclass
class TextChunkEvent:
    content: str


@dataclass
class ThinkingChunkEvent:
    def __init__(self, content):
        self.content = content


@dataclass
class ThinkingStartEvent:
    pass


@dataclass
class AssistantEvent:
    content: str
    tool_calls: list
    in_tokens: int = 0
    out_tokens: int = 0
    model_name: str = ""


@dataclass
class ToolPreparingEvent:
    """LLM 流式输出中检测到工具调用名称,工具尚未执行。"""

    name: str
    args: dict = field(default_factory=dict)


@dataclass
class ToolStartEvent:
    name: str
    args: dict
    tool_call_id: str = ""


@dataclass
class ToolEvent:
    name: str
    content: str
    tool_call_id: str
    args: dict = None


@dataclass
class EndEvent:
    depth: int


@dataclass
class InterruptedEvent:
    message: str = "已中断,等待您的补充指令..."


class PermissionRequestEvent(ReturnEvent):
    def __init__(self, description: str, tool_call: dict = None, explanation: str = ""):
        super().__init__(False)
        self.description: str = description
        self.tool_call: dict = tool_call or {}
        self.explanation: str = explanation


class SlashCommandEvent(ReturnEvent):
    """用户在 agent 运行期间输入了 /command,交由 UI 处理。"""

    def __init__(self, command: str):
        super().__init__()
        self.command: str = command


class ShellCommandEvent(ReturnEvent):
    """用户在 agent 运行期间输入了 !cmd,交由 UI 执行并将结果返回。"""

    def __init__(self, command: str):
        super().__init__()
        self.command: str = command


async def _check_permission(tc: dict, config: AppConfig) -> tuple[bool, str]:
    """检查工具调用是否需要用户权限确认。

    根据配置的权限模式和工具类型,判断是否自动批准该工具调用。
    某些安全操作或特定模式下的操作可以自动放行,其他操作需要用户手动确认。

    Args:
        tc (dict): 工具调用字典,包含以下键:
            - name (str): 工具名称,如 "Read", "Write", "Bash" 等
            - args (dict): 工具参数,不同工具有不同的参数字段
        config (AppConfig): 应用配置对象

    Returns:
        tuple[bool, str]: (是否自动批准, LLM解释文本)
            - 第一个元素:True 表示自动批准,False 表示需要用户确认
            - 第二个元素:LLM 生成的安全分析解释(仅 AUTO 模式下 LLM 判定不安全时有值)

    Note:
        - 计划模式切换工具始终自动批准
        - ACCEPT_ALL 模式下所有操作自动批准
        - MANUAL 模式下所有操作都需要用户确认
        - 只读类工具和记忆/技能列表工具自动批准
        - PLAN 模式下,写入计划目录的 Write 操作自动批准
        - Bash 命令通过安全检查后自动批准
        - 写入当前工作目录下文件的 Write 操作自动批准
        - AUTO 模式下,以上快速路径都未命中时,调用 LLM 检测安全性
        - 其他情况默认需要用户确认
    """
    perm_mode = config.permission_mode
    name = _tc_name(tc)

    if perm_mode == Permissions.ACCEPT_ALL:
        return (True, "")
    if perm_mode == Permissions.MANUAL:
        return (False, "")  # 始终询问

    # 安全工具自动批准(只读类工具和管理工具,computer use 启用时包含写入工具)
    from uniclaw.tools.security import is_safe_tool

    if is_safe_tool(name):
        return (True, "")

    # 活跃 skill 声明的工具自动放行
    from uniclaw.tools.skill.tools import get_active_skill_tools

    if name in get_active_skill_tools():
        return (True, "")

    # PLAN 模式下的特殊处理
    if perm_mode == Permissions.PLAN:

        # Write 工具:写入计划目录自动放行
        if name in (Write.name, Edit.name):
            from pathlib import Path

            file_path = _tc_args(tc).get("file_path", "")
            try:
                abs_file = Path(file_path).resolve()
                from uniclaw.tools.plan import get_plans_dir

                if abs_file.is_relative_to(get_plans_dir(config).resolve()):
                    return (True, "")
            except (ValueError, OSError):
                pass

    # Bash 命令安全检查(安全则直接放行,不安全则继续走后续流程包括 LLM 检测)
    if name == Bash.name:
        from uniclaw.tools.security import is_safe_bash

        args = _tc_args(tc)
        command = args.get("command", "").strip()
        if is_safe_bash(command, config.root_dir):
            return (True, "")

    # 其他工具的持久化规则检查
    from uniclaw.tools.security import check_saved_tool_rule

    if check_saved_tool_rule(name, config.root_dir):
        return (True, "")

    # Write 工具:如果写入的是可写目录下的文件,则自动放行
    if name in (Write.name, Edit.name):
        from pathlib import Path

        file_path = _tc_args(tc).get("file_path", "")
        writable_dirs = config.writable_dirs

        if writable_dirs:
            try:
                abs_file = Path(file_path).resolve()
                for d in writable_dirs:
                    abs_dir = Path(d).resolve()
                    if abs_file.is_relative_to(abs_dir):
                        return (True, "")
            except (ValueError, Exception):
                pass

    # 所有快速路径都未命中,调用 LLM 检测安全性
    from uniclaw.tools.security import llm_safe_check

    is_safe, explanation = await llm_safe_check(tc, config)
    if is_safe:
        return (True, "")
    return (False, explanation)


def _permission_desc(tc: dict) -> str:
    """生成权限请求的美观描述信息

    Args:
        tc: 工具调用字典,包含工具名称和参数

    Returns:
        格式化的权限请求描述字符串
    """
    name = _tc_name(tc)
    inp = _tc_args(tc)

    # Bash 命令执行
    if name == Bash.name:
        command = inp.get("command", "")
        return f"🖥️  运行 Shell 命令:\n   {command}"

    # 文件写入操作
    if name == Write.name:
        file_path = inp.get("file_path", "")
        return f"📝 写入文件:\n   {file_path}"

    # 文件编辑操作
    if name == Edit.name:
        file_path = inp.get("file_path", "")
        old_string = inp.get("old_string", "")
        new_string = inp.get("new_string", "")
        replace_all = inp.get("replace_all", False)
        diff = _edit_permission_diff(file_path, old_string, new_string)
        suffix = "\n   replace_all=true" if replace_all else ""
        return f"✏️  编辑文件:\n   {file_path}{suffix}\n\n{diff}"

    # 其他工具调用
    formatted_args = format_args_for_display(inp, 500, ",\n")
    return f"🔧 调用工具: {name}({formatted_args})"


def _edit_permission_diff(file_path: str, old_string: str, new_string: str) -> str:
    """Build a compact preview diff for an Edit permission prompt."""

    def _diff_lines(value: str) -> list[str]:
        lines = str(value).splitlines(keepends=True)
        if not lines and value:
            lines = [str(value)]
        return [line if line.endswith(("\n", "\r")) else f"{line}\n" for line in lines]

    old_lines = _diff_lines(old_string)
    new_lines = _diff_lines(new_string)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{Path(file_path).name}",
            tofile=f"b/{Path(file_path).name}",
            n=3,
        )
    )
    if not diff_lines:
        return "拟修改内容无差异。"

    max_lines = 160
    if len(diff_lines) > max_lines:
        hidden = len(diff_lines) - max_lines
        diff_lines = diff_lines[:max_lines]
        diff_lines.append(f"... ({hidden} more diff lines hidden)\n")
    return "拟修改 diff:\n" + "".join(diff_lines)


class AgentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST = "lost"


@dataclass
class AgentTask:

    name: str
    prompt: str
    session: Session
    user_queue: asyncio.Queue = field(default_factory=asyncio.Queue, repr=False)
    status: str = AgentStatus.PENDING
    result: Optional[str] = None
    result_read_index: int = 0

    worktree_path: str = ""
    worktree_branch: str = ""
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    tool_cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    future: Optional[asyncio.Task] = field(default=None, repr=False)
    event_queue: Optional[queue.Queue] = field(default=None, repr=False)
    todolist: Optional["TodoList"] = field(default=None, repr=False)
    pending_tools: list = field(default_factory=list, repr=False)
    allowed_tools_set: Optional[set[str]] = field(default=None, repr=False)

    @property
    def id(self) -> str:
        return self.session.id

    async def drain_user_queue(self, multi_agent: "MultiAgent") -> str:
        """从 user_queue 取出所有待处理消息,分类处理:
        - !cmd → 执行 shell 命令,结果追加到 messages 让 LLM 可见
        - /command → 交由 UI 处理斜杠命令(不追加到 messages)
        - 其他 → 合并为一条用户消息追加到 messages
        返回合并后的普通用户文本。"""
        messages = []
        while not self.user_queue.empty():
            try:
                messages.append(self.user_queue.get_nowait())
            except Exception:
                break
        if not messages:
            return ""

        self.cancel_event.clear()
        text_parts = []
        for msg in messages:
            stripped = msg.strip()
            if stripped.startswith("!"):
                cmd = stripped[1:].strip()
                if cmd:
                    event = ShellCommandEvent(cmd)
                    shell_output = (
                        await multi_agent.send_event_to_user(self, event) or ""
                    )
                    self.session.add_message(
                        MessageRole.USER,
                        f"{SYSTEM_PREFIX}(用户执行Shell命令)\n$ {cmd}\n{shell_output}",
                    )
            elif stripped.startswith("/"):
                event = SlashCommandEvent(stripped)
                await multi_agent.send_event_to_user(self, event)
            else:
                text_parts.append(msg)

        if text_parts:
            content = "\n\n".join(text_parts)
            self.session.add_message(MessageRole.USER, content)
            await multi_agent.send_event_to_user(self, UserEvent(content))
            return content
        return ""

    async def to_dict(self, config: AppConfig) -> dict | None:
        data = await self.session.to_dict(config)
        if data is None:
            return None
        metadata = {
            "permission_mode": config.permission_mode,
            "verbose": config.verbose,
        }
        data["metadata"] = metadata
        return data


class MultiAgent:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self.id2AgentTask: dict[str, AgentTask] = {}
            self.loop: asyncio.AbstractEventLoop | None = None  # 主事件循环引用
            self._initialized = True

    @classmethod
    def get_instance(cls):
        """获取 MultiAgent 单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = object.__new__(cls)
                    cls._instance.__init__()
        return cls._instance

    async def send_event_to_user(self, task, event):
        """将事件放入队列。对于有 return_event 的事件,等待 UI 处理后返回内容。"""
        if task.event_queue:
            task.event_queue.put((task, event))

        if hasattr(event, "return_event"):
            await event.return_event.wait()
            return event.content

    async def wait(self, task_id: str, timeout: float = None):
        """
        异步等待指定任务完成并返回任务对象。

        如果设置了 timeout,每次超时后会检查 messages 是否有新增:
        有新内容则继续等待,无新内容则返回。

        Args:
            task_id (str): 任务的唯一标识符。
            timeout (float, optional): 每轮等待的超时时间(秒)。

        Returns:
            AgentTask or None: 返回对应的任务对象。
        """
        task = self.id2AgentTask.get(task_id)
        if task is None:
            return None
        if task.future is None:
            return task

        last_msg_count = len(task.session)
        while True:
            try:
                await asyncio.wait_for(asyncio.shield(task.future), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass
            # 任务已完成
            if task.status in (
                AgentStatus.COMPLETED,
                AgentStatus.FAILED,
                AgentStatus.CANCELLED,
            ):
                break
            # 有 timeout 时:检查 messages 是否有新增
            current_msg_count = len(task.session)
            if current_msg_count > last_msg_count:
                last_msg_count = current_msg_count
            else:
                break  # 无新内容,结束等待
        return task

    def start_agent(
        self,
        user_message: str | list[dict[str, Any]],
        config: AppConfig,
        system_prompt: Optional[str] = None,
    ) -> AgentTask:
        task = config.current_agent
        task.prompt = user_message
        task.status = AgentStatus.PENDING
        self.id2AgentTask[task.id] = task
        task.future = asyncio.create_task(self.run(user_message, system_prompt, config))
        return task

    async def start_sub_agent(
        self,
        user_message: str,
        config: AppConfig,
        system_prompt: str | None = None,
        agent_def: Optional[AgentDefinition] = None,
        isolation: bool = False,
        inherit_events: bool = False,
        notify_parent: bool = False,
        keep_alive: bool = False,
    ) -> AgentTask:
        """启动子代理。config 应通过 create_child_config() 预先创建。"""
        parent_task = config.parent_agent
        task = config.current_agent
        task.prompt = user_message
        task.status = AgentStatus.PENDING
        root_dir = config.root_dir

        if (
            inherit_events
            and parent_task is not None
            and parent_task.event_queue is not None
        ):
            task.event_queue = parent_task.event_queue
        self.id2AgentTask[task.id] = task

        base_system_prompt = get_base_system_prompt(config)
        allowed_tools = None
        if agent_def:
            if agent_def.model_name:
                config.model_name = agent_def.model_name
            if agent_def.tools:
                allowed_tools = agent_def.tools
            if agent_def.system_prompt:
                base_system_prompt += f"\n\n{agent_def.system_prompt}"

        if not allowed_tools:
            allowed_tools = await get_tools(config)
        elif allowed_tools and isinstance(allowed_tools[0], str):
            # agent_def.tools 是字符串名,转为 Tool 对象
            from uniclaw.tools.registry import ToolRegistry

            entries = ToolRegistry.get_instance().get_all_entries()
            resolved = []
            for name in allowed_tools:
                if name in entries:
                    resolved.append(entries[name].tool)
                else:
                    get_logger("agent", task.session.root_dir).warning(
                        f"agent_def.tools 中的工具 '{name}' 未在注册表中找到,已忽略"
                    )
            allowed_tools = resolved
        # 子代理展示可搜索的扩展工具
        from uniclaw.tools.registry import get_registry_system_prompt

        registry_ctx = get_registry_system_prompt(config)
        if registry_ctx:
            base_system_prompt += f"\n\n{registry_ctx}"
        # 用户传递的系统提示词放在最后
        system_prompt = (
            f"{base_system_prompt}\n\n{"" if system_prompt is None else system_prompt}"
        )
        if isolation:
            git_root = await get_git_root(root_dir)
            if not git_root:
                task.status = AgentStatus.FAILED
                task.result = "isolation需要git仓库"
                return task
            try:
                worktree_path, worktree_branch = await create_worktree(git_root)
            except Exception as e:
                task.status = AgentStatus.FAILED
                task.result = f"isolation创建工作树失败: {e}"
                return task
            task.worktree_path = worktree_path
            task.worktree_branch = worktree_branch
            notice = (
                f"\n\n[注意:你正在一个隔离的 git worktree 中工作,位于 "
                f"{worktree_path}(分支:{worktree_branch})。"
                f"你的更改与主工作区 {git_root} 隔离。"
                f"在完成之前提交你的更改,以便可以审查/合并。]"
            )
            system_prompt = system_prompt + notice
            config.writable_dirs.insert(0, worktree_path)
            task.session.root_dir = Path(worktree_path)

        async def _run_proc(user_message, system_prompt, config, task: AgentTask):
            try:
                task.user_queue.put_nowait(user_message)
                while not task.cancel_event.is_set():
                    if keep_alive:
                        task.status = AgentStatus.WAITING
                    try:
                        msg = await asyncio.wait_for(
                            task.user_queue.get(),
                            timeout=0.2 if keep_alive else None,
                        )
                    except asyncio.TimeoutError:
                        if keep_alive:
                            continue
                        break
                    if msg == "__agent_close__":
                        task.status = AgentStatus.COMPLETED
                        break
                    await self.run(msg, system_prompt, config, allowed_tools)
                    if task.cancel_event.is_set():
                        task.result = "任务已取消。"
                        return
                    task.result = task.session.get_assistant_messages()
                    if (
                        notify_parent
                        and parent_task is not None
                        and parent_task is not task
                    ):
                        parent_task.user_queue.put_nowait(
                            f"{SYSTEM_PREFIX}[child_agent]\n"
                            f"名称: {task.name}\n"
                            f"任务ID: {task.id}\n"
                            f"状态: {task.status}\n"
                            "消息: 此子智能体有新的输出。\n"
                            f'- 请调用 {check_agent_result.name}(task_id="{task.id}") 来读取结果\n'
                            f'- 使用 {send_message.name}(task_id="{task.id}", message="...") 发送消息\n'
                            f'- 使用 {agent_close.name}(task_id="{task.id}") 关闭智能体'
                        )
                    if not keep_alive:
                        break
                if not task.result:
                    task.result = task.session.get_assistant_messages()
            except Exception as e:
                task.result = f"任务处理失败:{str(e)}"
                task.status = AgentStatus.FAILED
            finally:
                if task.status == AgentStatus.WAITING:
                    task.status = AgentStatus.COMPLETED
                if task.worktree_path:
                    await remove_worktree(
                        task.worktree_path, task.worktree_branch, root_dir
                    )

        task.future = asyncio.create_task(
            _run_proc(user_message, system_prompt, config, task)
        )
        return task

    def list_tasks(self) -> list[AgentTask]:
        return list(self.id2AgentTask.values())

    def send_message(self, task_id: str, message: str) -> bool:
        task = self.id2AgentTask.get(task_id)
        if task is None:
            return False
        if task.status not in (
            AgentStatus.RUNNING,
            AgentStatus.PENDING,
            AgentStatus.WAITING,
        ):
            return False
        task.user_queue.put_nowait(message)
        return True

    def close_agent(self, task_id: str) -> bool:
        task = self.id2AgentTask.get(task_id)
        if task is None:
            return False
        if task.status in (
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.CANCELLED,
        ):
            return True
        task.user_queue.put_nowait("__agent_close__")
        return True

    async def _run_init(self, user_message, config: AppConfig) -> bool:
        """初始化 run 环境:深度检查、钩子、消息。成功返回 True,失败返回 False。"""
        task = config.current_agent
        if config.depth >= config.max_agent_depth:
            task.status = AgentStatus.FAILED
            task.result = f"错误:超过最大深度 ({config.max_agent_depth})"
            return False
        task.status = AgentStatus.RUNNING
        if not config.is_sub:
            await run_hooks(
                HookEvent.SESSION_START,
                {"user_message": extract_text(user_message), "depth": config.depth},
                config=config,
                task=task,
            )
        task.session.add_message(MessageRole.USER, user_message)
        await self.send_event_to_user(task, UserEvent(user_message))
        return True

    async def _stream_response(
        self, task, system_message, config: AppConfig, tools
    ) -> StreamChunk | None:
        """异步流式调用 LLM,处理 thinking/text chunk。返回 resp,取消返回 None。"""
        try:
            resp = None
            async for chunk in astream(
                system_message,
                task.session,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                tools=tools,
                config=config,
            ):
                if task.cancel_event.is_set():
                    task.status = AgentStatus.CANCELLED
                    await self.send_event_to_user(task, InterruptedEvent())
                    return None
                if resp is None:
                    resp = chunk
                else:
                    resp += chunk
                if chunk.reasoning_content:
                    await self.send_event_to_user(
                        task, ThinkingChunkEvent(chunk.reasoning_content)
                    )
                if chunk.content:
                    await self.send_event_to_user(task, TextChunkEvent(chunk.content))
                if chunk.new_tool_call_name:
                    await self.send_event_to_user(
                        task,
                        ToolPreparingEvent(
                            chunk.new_tool_call_name, chunk.new_tool_call_args
                        ),
                    )
            if task.cancel_event.is_set():
                await self.send_event_to_user(task, InterruptedEvent())
                return None
            return resp
        except Exception as e:
            error_traceback = traceback.format_exc()
            get_logger("agent", task.session.root_dir).error(error_traceback)
            await self.send_event_to_user(
                task,
                TextChunkEvent(f"\n⚠️ 模型请求失败:{str(e)}\n"),
            )
            task.status = AgentStatus.FAILED
            return None

    async def _process_response(self, resp, task, config: AppConfig):
        """处理 LLM 响应:构建消息、记录 usage、发送事件。返回 tool_calls 列表。"""
        content = resp.content or ""
        tool_calls = resp.tool_calls
        reasoning = resp.reasoning_content or ""

        in_tokens = resp.usage.input_tokens if resp.usage else 0
        out_tokens = resp.usage.output_tokens if resp.usage else 0
        total_tokens = resp.usage.total_tokens if resp.usage else in_tokens + out_tokens
        actual_model = resp.model_name or config.model_name
        usage_dict = {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "total_tokens": total_tokens,
        }

        task.session.add_message(
            MessageRole.ASSISTANT,
            content,
            model_name=actual_model,
            usage=usage_dict,
            tool_calls=tool_calls,
            reasoning_content=reasoning or None,
        )

        await run_hooks(
            HookEvent.PRE_ASSISTANT,
            {
                "content": resp.content,
                "tool_calls": resp.tool_calls,
                "in_tokens": in_tokens,
                "out_tokens": out_tokens,
                "model_name": actual_model,
            },
            config=config,
            task=task,
        )
        await self.send_event_to_user(
            task,
            AssistantEvent(
                content=resp.content,
                tool_calls=resp.tool_calls,
                in_tokens=in_tokens,
                out_tokens=out_tokens,
                model_name=actual_model,
            ),
        )
        from uniclaw.utils.usage import record_usage

        await record_usage(
            in_tokens, out_tokens, len(resp.tool_calls), model=actual_model
        )
        return resp.tool_calls

    async def _execute_single_tool(
        self, tool_call, name2tool, config: AppConfig
    ) -> tuple[dict, Any]:
        """执行单个工具调用(权限检查 + hooks + 执行 + UI 事件)。

        返回 (tool_call, tool_resp_content)。
        """
        task = config.current_agent
        tool_resp_content = None
        tc_name = _tc_name(tool_call)
        tc_args = _tc_args(tool_call)

        # 查找工具
        try:
            tool = name2tool[tc_name]
        except KeyError:
            if task.allowed_tools_set and tc_name in task.allowed_tools_set:
                tool_resp_content = (
                    f"工具 '{tc_name}' 是扩展工具,当前未加载。"
                    f'请先使用 {search_tools.name} 搜索 "{tc_name}" 来加载该工具,然后重试。'
                )
            else:
                tool_resp_content = f"工具不存在: {tc_name}"

        # PRE_TOOL_USE hook
        if tool_resp_content is None:
            try:
                await run_hooks(
                    HookEvent.PRE_TOOL_USE,
                    {
                        "tool_name": tc_name,
                        "tool_call": tool_call,
                        "args": tc_args,
                    },
                    config=config,
                    task=task,
                )
            except HookError as e:
                tool_resp_content = f"Hook blocked tool call: {e}"

        # 权限检查
        if tool_resp_content is None:
            permitted, llm_explanation = await _check_permission(tool_call, config)
            if not permitted:
                description = _permission_desc(tool_call)
                try:
                    await run_hooks(
                        HookEvent.PERMISSION_REQUEST,
                        {
                            "tool_name": tc_name,
                            "tool_call": tool_call,
                            "args": tc_args,
                            "description": description,
                            "explanation": llm_explanation,
                        },
                        config=config,
                        task=task,
                    )
                    req = PermissionRequestEvent(
                        description=description,
                        tool_call=tool_call,
                        explanation=llm_explanation,
                    )
                    permitted = await self.send_event_to_user(task, req) or True
                except HookError as e:
                    permitted = f"Hook blocked permission request: {e}"
                await run_hooks(
                    HookEvent.PERMISSION_RESPONSE,
                    {
                        "tool_name": tc_name,
                        "tool_call": tool_call,
                        "args": tc_args,
                        "permitted": permitted is True,
                        "response": permitted,
                    },
                    config=config,
                    task=task,
                )
            if permitted is True:
                task.tool_cancel_event.clear()
                config.tool_cancel_event = task.tool_cancel_event
                tc_id = tool_call.get("id", "")
                await self.send_event_to_user(
                    task,
                    ToolStartEvent(tc_name, dict(tc_args), tool_call_id=tc_id),
                )
                try:
                    sig = inspect.signature(tool.func)
                    kwargs = (
                        {**tc_args, "config": config}
                        if "config" in sig.parameters
                        else dict(tc_args)
                    )
                    # 支持异步工具:检测是否为协程函数
                    if inspect.iscoroutinefunction(tool.func):
                        tool_resp_content = await tool.func(**kwargs)
                    else:
                        tool_resp_content = tool.func(**kwargs)
                    if isinstance(tool_resp_content, str):
                        tool_resp_content = truncate_text_by_lines(
                            tool_resp_content
                        )
                    # 只读工具去重:结果与之前相同且较大时省略
                    dedup_msg = task.session.check_dedup(
                        tc_name, tc_args, tool_resp_content
                    )
                    if dedup_msg:
                        tool_resp_content = dedup_msg
                except Exception as e:
                    get_logger("agent", task.session.root_dir).error(
                        f"工具调用失败 [{tc_name}]\n参数: {tc_args}\n{traceback.format_exc()}"
                    )
                    tool_resp_content = f"工具调用失败: {e}"
            else:
                tool_resp_content = (
                    "用户拒绝: " + permitted
                    if isinstance(permitted, str) and permitted.strip()
                    else "用户拒绝执行"
                )

        # POST_TOOL_USE hook
        await run_hooks(
            HookEvent.POST_TOOL_USE,
            {
                "tool_name": tc_name,
                "tool_call": tool_call,
                "args": tc_args,
                "result": extract_text(tool_resp_content),
            },
            config=config,
            task=task,
        )
        display_content = (
            tool_resp_content
            if isinstance(tool_resp_content, str)
            else extract_text(tool_resp_content)
        )
        await self.send_event_to_user(
            task,
            ToolEvent(
                name=tc_name,
                content=display_content,
                tool_call_id=tool_call.get("id", ""),
                args=tc_args,
            ),
        )
        return tool_call, tool_resp_content

    async def _execute_tool_calls(
        self,
        tool_calls,
        name2tool,
        config: AppConfig,
        tools: list = None,
    ) -> bool:
        """并行执行工具调用列表。返回 True 表示被 cancel。"""
        task = config.current_agent

        # 并行执行所有工具
        results = await asyncio.gather(
            *[
                self._execute_single_tool(tc, name2tool, config)
                for tc in tool_calls
            ]
        )

        # 按顺序处理结果: add_message + cancel 检查
        for tool_call, tool_resp_content in results:
            tc_name = _tc_name(tool_call)
            # 检查是否为多模态内容(如图片),需要特殊处理
            _mm_types = {"image_url", "input_audio", "video_url"}
            if isinstance(tool_resp_content, list) and any(
                isinstance(b, dict) and b.get("type") in _mm_types
                for b in tool_resp_content
            ):
                # 提取文本部分作为 tool 回复
                extracted = extract_text(tool_resp_content, separator="\n")
                task.session.add_message(
                    MessageRole.TOOL,
                    extracted or "(见下方多媒体内容)",
                    name=tc_name,
                    tool_call_id=tool_call.get("id", ""),
                )
                # 将多模态内容作为 user 消息,让 LLM 能看到图片/音频/视频
                task.session.add_message(MessageRole.USER, tool_resp_content)
            else:
                # TOOL 消息 content 必须是 str,非 str 内容需转换
                final_content = (
                    tool_resp_content
                    if isinstance(tool_resp_content, str)
                    else extract_text(tool_resp_content)
                )
                task.session.add_message(
                    MessageRole.TOOL,
                    final_content,
                    name=tc_name,
                    tool_call_id=tool_call.get("id", ""),
                )
        if task.cancel_event.is_set():
            task.status = AgentStatus.CANCELLED
            await self.send_event_to_user(task, InterruptedEvent())
            return True
        # 加载待发现的工具(由 search_tools 等工具写入)
        if tools is not None and task.pending_tools:
            for t in task.pending_tools:
                if t.name not in name2tool:
                    tools.append(t)
                    name2tool[t.name] = t
            task.pending_tools.clear()
        return False

    async def _run_cleanup(self, task, config: AppConfig):
        """设置最终状态,触发 SESSION_END 钩子,发送 EndEvent。"""
        if task.status == AgentStatus.RUNNING:
            task.status = AgentStatus.COMPLETED
        if not config.is_sub:
            await run_hooks(
                HookEvent.SESSION_END,
                {"status": task.status, "depth": config.depth},
                config=config,
                task=task,
            )
        await self.send_event_to_user(task, EndEvent(depth=config.depth))

    @error_catch("agent")
    async def run(
        self,
        user_message: str | list[dict[str, Any]],
        system_message: Optional[str] = None,
        config: AppConfig = None,
        allowed_tools: list[Tool] | None = None,
    ):
        task = config.current_agent
        if not await self._run_init(user_message, config):
            return
        task.cancel_event.clear()

        # 自动创建 Git 检查点(使用用户消息的文本部分作为描述)
        await create_checkpoint(
            task.session.root_dir, message=extract_text(user_message)
        )
        if system_message is None:
            system_message = build_system_prompt(config)
        # 使用核心工具(约 15 个)+ search_tools,扩展工具按需加载
        is_sub = config.is_sub
        tools = list(await get_core_tools(sub_agent=is_sub))
        if is_sub:
            ext_names = {t.name for t in allowed_tools}
            task.allowed_tools_set = {t.name for t in tools} | ext_names
        else:
            task.allowed_tools_set = {t.name for t in await get_tools(config)}

        name2tool = {tool.name: tool for tool in tools}
        while True:
            while True:
                if task.cancel_event.is_set():
                    task.status = AgentStatus.CANCELLED
                    await self.send_event_to_user(task, InterruptedEvent())
                    break

                await maybe_compact(config)

                await self.send_event_to_user(task, ThinkingStartEvent())

                resp = await self._stream_response(task, system_message, config, tools)
                if resp is None:
                    break

                tool_calls = await self._process_response(resp, task, config)
                content = await task.drain_user_queue(self)
                if not tool_calls:
                    if content:
                        continue
                    break

                if task.cancel_event.is_set():
                    task.status = AgentStatus.CANCELLED
                    await self.send_event_to_user(task, InterruptedEvent())
                    break
                if await self._execute_tool_calls(
                    tool_calls, name2tool, config, tools
                ):
                    break
                content = await task.drain_user_queue(self)
            todo = task.todolist
            incomplete = todo.get_incomplete() if todo else []
            if (
                todo
                and todo.overseer.active
                and not config.is_sub
                and not task.cancel_event.is_set()
                and incomplete
            ):
                msg = f"{SYSTEM_PREFIX}还有以下任务未完成,请继续:\n" + "\n".join(
                    f"- {item}" for item in incomplete
                )
                msg += f"\n\n请查看TodoList当前任务列表并继续完成剩余任务。如需与用户交流,请使用 {AskUserQuestion.name} 工具。"
                task.user_queue.put_nowait(msg)
                content = await task.drain_user_queue(self)
                continue
            else:
                break

        await self._run_cleanup(task, config)
        return
