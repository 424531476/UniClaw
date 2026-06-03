from concurrent.futures import Future, ThreadPoolExecutor
from enum import StrEnum
import os
import threading
import difflib
import queue
import time
from pathlib import Path
from typing import Any, Optional
import uuid

from langchain.messages import AIMessageChunk
from llm import stream
from tools import get_tools
from dataclasses import dataclass, field
from context import build_system_prompt
from config import Permissions, load_config
from tools.ask import AskUserQuestion
from tools.fs import Edit, Write
from tools.multi_agent.sub_agent import AgentDefinition
from tools.multi_agent.tools import check_agent_result, send_message, agent_close
from tools.shell import Bash
from tools.todolist import TodoList
from utils.git import create_worktree, get_git_root, remove_worktree
from utils.truncation import truncate_text_by_lines
from utils.logger import get_logger
from utils.format import format_args_for_display
from tools.hooks.hook_manager import HookError, HookEvent, run_hooks
import traceback

from utils.wrapper import error_catch

logger = get_logger("agent")


class MessageRole(StrEnum):
    """
    消息角色枚举

    定义了对话中不同角色的类型:
        SYSTEM: 系统消息,用于设置助手的行为和背景
        USER: 用户消息,表示用户输入的内容
        ASSISTANT: 助手消息,表示助手的回复
        TOOL: 工具消息,表示工具调用的结果
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ReturnEvent:

    def __init__(self, default_content=None):
        self.content = default_content
        self.return_event = threading.Event()


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
class ToolStartEvent:
    name: str
    args: dict


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


def _extract_text(content) -> str:
    """从多模态内容中提取纯文本,用于 UI 显示"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(texts)
    return str(content)


def _check_permission(tc: dict, config: dict) -> tuple[bool, str]:
    """检查工具调用是否需要用户权限确认。

    根据配置的权限模式和工具类型,判断是否自动批准该工具调用。
    某些安全操作或特定模式下的操作可以自动放行,其他操作需要用户手动确认。

    Args:
        tc (dict): 工具调用字典,包含以下键:
            - name (str): 工具名称,如 "Read", "Write", "Bash" 等
            - args (dict): 工具参数,不同工具有不同的参数字段
        config (dict): 配置字典,包含以下键:
            - permission_mode (str): 权限模式,可选值为 Permissions.ACCEPT_ALL,
              Permissions.MANUAL, Permissions.PLAN 等
            - cwd (str, optional): 当前工作目录路径

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
    perm_mode = config.get("permission_mode", Permissions.AUTO)
    name = tc["name"]

    if perm_mode == Permissions.ACCEPT_ALL:
        return (True, "")
    if perm_mode == Permissions.MANUAL:
        return (False, "")  # 始终询问

    # 安全工具自动批准(只读类工具和管理工具,computer use 启用时包含写入工具)
    from tools.security import is_safe_tool

    if is_safe_tool(name):
        return (True, "")

    # 活跃 skill 声明的工具自动放行
    from tools.skill.tools import get_active_skill_tools

    if name in get_active_skill_tools():
        return (True, "")

    # PLAN 模式下的特殊处理
    if perm_mode == Permissions.PLAN:

        # Write 工具:写入计划目录自动放行
        if name in (Write.name, Edit.name):
            from pathlib import Path

            file_path = tc["args"].get("file_path", "")
            try:
                abs_file = Path(file_path).resolve()
                from tools.plan import PLANS_DIR

                if abs_file.is_relative_to(PLANS_DIR.resolve()):
                    return (True, "")
            except (ValueError, OSError):
                pass

    # Bash 命令安全检查(安全则直接放行,不安全则继续走后续流程包括 LLM 检测)
    if name == Bash.name:
        from tools.security import is_safe_bash

        command = tc["args"].get("command", "").strip()
        if is_safe_bash(command):
            return (True, "")

    # 其他工具的持久化规则检查
    from tools.security import check_saved_tool_rule

    if check_saved_tool_rule(name):
        return (True, "")

    # Write 工具:如果写入的是 cwd 目录下的文件,则自动放行
    if name in (Write.name, Edit.name):
        from pathlib import Path

        file_path = tc["args"].get("file_path", "")
        cwd = config.get("cwd", None)

        # 如果 cwd 为 None,保守处理,需要用户确认
        if isinstance(cwd, str) and cwd:
            try:
                # 将路径解析为绝对路径并检查是否在 cwd 下
                abs_file = Path(file_path).resolve()
                abs_cwd = Path(cwd).resolve()

                # 检查文件路径是否是 cwd 的子路径
                if abs_file.is_relative_to(abs_cwd):
                    return (True, "")
            except (ValueError, Exception):
                # 如果路径解析失败,保守处理,需要用户确认
                pass

    # 所有快速路径都未命中,调用 LLM 检测安全性
    from tools.security import llm_safe_check

    is_safe, explanation = llm_safe_check(tc, config)
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
    name = tc["name"]
    inp = tc["args"]

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


class MessageQueue:
    """
    消息队列类,支持基于任务ID的消息缓冲和转发机制。

    该队列采用双层结构:
    - message_queue: 主队列,存储当前活跃任务的消息
    - temp_queue: 临时队列,缓存其他任务的消息

    当遇到边界事件(AssistantEvent/ToolEvent)且主队列为空时,
    会自动将临时队列的内容转发到主队列。

    注意:该类是线程安全的,使用 RLock 保护所有共享状态的访问。
    """

    def __init__(self):
        """初始化消息队列"""
        self.message_queue = queue.Queue()
        self.temp_queue: Optional[MessageQueue] = None
        self.last_task = None
        self.last_at = None
        self._lock = threading.RLock()  # 使用可重入锁支持递归调用

    def put(self, data):
        """
        将消息放入队列。

        如果消息的任务ID与当前活跃任务相同,则放入主队列；
        否则放入临时队列进行缓冲。

        Args:
            data: 元组 (task, event),其中 at 是任务ID对象引用,event 是事件对象
        """
        with self._lock:
            task, event = data

            # 使用对象引用比较(is),确保同一任务的消息进入同一队列
            if self.last_task is None or task is self.last_task:
                self.message_queue.put(data)
                # 更新当前活跃任务ID
                self.last_task = task
                self.last_at = task
            else:
                # 不同任务ID,创建或使用临时队列
                if self.temp_queue is None:
                    self.temp_queue = MessageQueue()
                self.temp_queue.put(data)

    def get(self):
        """
        从主队列获取一条消息。

        如果获取到边界事件(AssistantEvent/ToolEvent)且主队列为空,
        则触发转发机制,将临时队列的内容转移到主队列。

        Returns:
            元组 (task, event)

        Raises:
            queue.Empty: 当队列为空时抛出
        """
        with self._lock:
            data = self.message_queue.get()
            task, event = data

            # 检查是否需要转发:主队列空且遇到边界事件
            if self.message_queue.empty() and isinstance(
                event, (AssistantEvent, ToolEvent)
            ):
                self._forward()

            return data

    def _forward(self):
        """
        将临时队列的内容转发到主队列。

        该方法会递归处理多层嵌套的临时队列,
        并将最内层队列的引用提升到当前层级。

        注意:此方法在调用时必须已持有锁(由 get() 或外部调用者保证)。
        """
        while self.temp_queue and self.temp_queue._size() > 0:
            # 将临时队列的主队列提升为当前队列
            while not self.temp_queue.message_queue.empty():
                self.message_queue.put(self.temp_queue.message_queue.get())
            # 同步更新 last_task
            self.last_task = self.temp_queue.last_task
            self.last_at = self.temp_queue.last_at
            # 递归处理更深层的临时队列
            self.temp_queue._forward()

        # 转发完成后清空临时队列引用
        self.temp_queue = None

    def empty(self):
        """
        检查队列是否为空。

        Returns:
            bool: 如果主队列为空则返回 True
        """
        with self._lock:
            main_empty = self.message_queue.empty()
            return main_empty

    def _size(self):
        """
        计算队列中的消息总数(包括主队列和所有临时队列)。

        Returns:
            int: 消息总数
        """
        with self._lock:
            main_size = self.message_queue.qsize()
            temp_size = self.temp_queue._size() if self.temp_queue else 0
            return main_size + temp_size


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
    id: str  # 任务ID也是线程id
    name: str
    prompt: str
    messages: list = field(default_factory=list)
    user_queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
    status: str = AgentStatus.PENDING
    result: Optional[str] = None
    result_read_index: int = 0
    # depth: int = 0

    worktree_path: str = ""
    worktree_branch: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    tool_cancel_event: threading.Event = field(
        default_factory=threading.Event, repr=False
    )
    future: Optional[Future] = field(default=None, repr=False)
    event_queue: Optional[queue.Queue] = field(default=None, repr=False)

    def drain_user_queue(self, multi_agent: "MultiAgent") -> str:
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
                    result = multi_agent.send_event_to_user(self, event)
                    shell_output = result if result else ""
                    self.messages.append(
                        {
                            "role": MessageRole.USER,
                            "content": f"[用户执行Shell命令]\n$ {cmd}\n{shell_output}",
                        }
                    )
            elif stripped.startswith("/"):
                event = SlashCommandEvent(stripped)
                multi_agent.send_event_to_user(self, event)
            else:
                text_parts.append(msg)

        if text_parts:
            content = "\n\n".join(text_parts)
            self.messages.append({"role": MessageRole.USER, "content": content})
            multi_agent.send_event_to_user(self, UserEvent(content))
            return content
        return ""


class MultiAgent:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # 防止重复初始化
        if hasattr(self, "_initialized") and self._initialized:
            return
        self.id2AgentTask: dict[str, AgentTask] = {}
        self.pool = ThreadPoolExecutor(16)
        self.event_queue = queue.Queue()
        self._initialized = True

    @classmethod
    def get_instance(cls):
        """获取 MultiAgent 单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def send_event_to_user(self, task, event):
        target_queue = (
            task.event_queue if task.event_queue is not None else self.event_queue
        )
        target_queue.put((task, event))
        if hasattr(event, "return_event"):
            if not event.return_event.wait(timeout=300):
                return "权限请求等待超时"
            return event.content

    def wait(self, task_id: str, timeout: float = None):
        """
        等待指定任务完成并返回任务对象。

        该方法会阻塞当前线程直到任务完成或超时。如果任务已经完成,立即返回；
        如果任务尚未完成,则等待其执行完毕。

        Args:
            task_id (str): 任务的唯一标识符,用于查找对应的任务对象。
            timeout (float, optional): 等待超时时间(秒)。如果为None,则无限期等待直到任务完成。
                                      如果指定了超时时间,超过该时间后任务仍未完成则抛出异常。

        Returns:
            AgentTask or None: 返回对应的任务对象。如果找不到指定的task_id,则返回None。
                              无论任务是否成功执行,都会返回任务对象(包含执行状态和结果)。

        Note:
            - 如果任务不存在(task_id无效),返回None。
            - 如果任务没有关联的future对象,直接返回任务对象(可能任务还未开始执行)。
            - 如果任务执行过程中发生异常,仍然返回任务对象,可以通过检查任务状态获取异常信息。
        """
        task = self.id2AgentTask.get(task_id)
        if task is None:
            return None
        if task.future is None:
            return task
        try:
            task.future.result(timeout=timeout)
        except Exception:
            return task
        return task

    def start(
        self,
        user_message: str,
        task: AgentTask,
        system_prompt: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> AgentTask:
        task.prompt = user_message
        task.status = AgentStatus.PENDING
        self.id2AgentTask[task.id] = task
        future = self.pool.submit(self.run, user_message, system_prompt, config, task)
        task.future = future
        return task

    def start_sub_agent(
        self,
        name: str,
        user_message: str,
        system_prompt: Optional[str],
        config: dict,
        agent_def: Optional[AgentDefinition] = None,
        isolation: bool = False,
    ) -> AgentTask:
        task_id = uuid.uuid4().hex[:12]
        short_name = name or task_id[:8]
        task = AgentTask(
            id=task_id,
            name=short_name,
            prompt=user_message,
            status=AgentStatus.PENDING,
        )
        inherit_events = bool(config and config.get("_inherit_event_queue"))
        notify_parent = bool(config and config.get("_notify_parent_on_complete"))
        keep_alive = bool(config and config.get("_keep_alive"))
        parent_task = config.get("_parent_task") if config else None
        if (
            inherit_events
            and parent_task is not None
            and parent_task.event_queue is not None
        ):
            task.event_queue = parent_task.event_queue
        self.id2AgentTask[task.id] = task
        # 拷贝配置时排除带 "_" 前缀的内部键
        config = {k: v for k, v in config.items() if not k.startswith("_")}
        config["depth"] += 1
        allowed_tools = None
        if agent_def:
            if agent_def.model_name:
                config["model_name"] = agent_def.model_name
            if agent_def.tools:
                allowed_tools = agent_def.tools
            if agent_def.system_prompt:
                system_prompt = (
                    agent_def.system_prompt.rstrip() + "\n\n" + system_prompt
                )
        cwd = config["cwd"] if config["cwd"] else os.getcwd()
        if isolation:
            git_root = get_git_root(cwd)
            if not git_root:
                task.status = AgentStatus.FAILED
                task.result = "isolation需要git仓库"
                return task
            try:
                worktree_path, worktree_branch = create_worktree(git_root)
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
            config["cwd"] = worktree_path

        def _run_proc(user_message, system_prompt, config, task: AgentTask):
            try:
                task.user_queue.put(user_message)
                while not task.cancel_event.is_set():
                    if keep_alive:
                        task.status = AgentStatus.WAITING
                    try:
                        msg = task.user_queue.get(timeout=0.2 if keep_alive else 0)
                    except queue.Empty:
                        if keep_alive:
                            continue
                        break
                    if msg == "__agent_close__":
                        task.status = AgentStatus.COMPLETED
                        break
                    self.run(msg, system_prompt, config, task, allowed_tools)
                    if task.cancel_event.is_set():
                        task.result = "任务已取消。"
                        return
                    task.result = self.get_assistant_messages(task.messages)
                    if (
                        notify_parent
                        and parent_task is not None
                        and parent_task is not task
                    ):
                        parent_task.user_queue.put_nowait(
                            "[system][child_agent]\n"
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
                    task.result = self.get_assistant_messages(task.messages)
            except Exception as e:
                task.result = f"任务处理失败:{str(e)}"
                task.status = AgentStatus.FAILED
            finally:
                if task.status == AgentStatus.WAITING:
                    task.status = AgentStatus.COMPLETED
                if task.worktree_path:
                    remove_worktree(
                        task.worktree_path, task.worktree_branch, os.getcwd()
                    )

        future = self.pool.submit(_run_proc, user_message, system_prompt, config, task)
        task.future = future
        return task

    @staticmethod
    def get_assistant_messages(messages):
        assistant_messages = list()
        for message in messages:
            if message["role"] == "assistant" and message["content"]:
                assistant_messages.append(message["content"])
        return "\n".join(assistant_messages)

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

    def _run_init(self, user_message, config, task) -> bool:
        """初始化 run 环境:config、深度检查、钩子、工具。返回 bool。"""
        if config is None:
            config = load_config()
        config["_current_task"] = task
        if config["depth"] >= config["max_agent_depth"]:
            task.status = AgentStatus.FAILED
            task.result = f"错误:超过最大深度 ({config["max_agent_depth"]})"
            return False
        task.status = AgentStatus.RUNNING
        run_hooks(
            HookEvent.SESSION_START,
            {"user_message": _extract_text(user_message), "depth": config["depth"]},
            config=config,
            task=task,
        )
        task.messages.append({"role": MessageRole.USER, "content": user_message})
        self.send_event_to_user(task, UserEvent(user_message))
        return True

    def _stream_response(
        self, task, system_message, config, tools
    ) -> AIMessageChunk | None:
        """流式调用 LLM,处理 thinking/text chunk。返回 resp,取消时返回 "cancelled",失败返回 None。"""
        messages = [
            {"role": MessageRole.SYSTEM, "content": system_message},
            *task.messages,
        ]
        try:
            resp = None
            for chunk in stream(
                messages=messages,
                model_name=config["model_name"],
                openai_api_base=config.get("OPENAI_BASE_URL", ""),
                openai_api_key=config.get("OPENAI_API_KEY", ""),
                multimodal_model_name=config.get("multimodal_model_name"),
                temperature=config["temperature"],
                max_tokens=config["max_tokens"],
                top_p=config["top_p"],
                tools=tools,
            ):
                if task.cancel_event.is_set():
                    task.status = AgentStatus.CANCELLED
                    self.send_event_to_user(task, InterruptedEvent())
                    return None
                if resp is None:
                    resp = chunk
                else:
                    resp += chunk
                if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs.get(
                    "reasoning_content"
                ):
                    thinking = chunk.additional_kwargs["reasoning_content"]
                    self.send_event_to_user(task, ThinkingChunkEvent(thinking))
                if chunk.content:
                    self.send_event_to_user(task, TextChunkEvent(chunk.content))
            if task.cancel_event.is_set():
                self.send_event_to_user(task, InterruptedEvent())
                return None
            return resp
        except Exception as e:
            import traceback

            error_traceback = traceback.format_exc()
            logger.error(error_traceback)
            self.send_event_to_user(
                task,
                TextChunkEvent(f"\n⚠️ 模型请求失败:{str(e)}\n"),
            )
            task.status = AgentStatus.FAILED
            return None

    def _process_response(self, resp, task, config):
        """处理 LLM 响应:构建消息、记录 usage、发送事件。返回 tool_calls 列表。"""
        assistant_message = {
            "role": MessageRole.ASSISTANT,
            "content": resp.content if resp.content else "",
            "tool_calls": resp.tool_calls,
        }
        if hasattr(resp, "additional_kwargs") and resp.additional_kwargs.get(
            "reasoning_content"
        ):
            assistant_message["reasoning_content"] = resp.additional_kwargs[
                "reasoning_content"
            ]
        task.messages.append(assistant_message)

        usage_meta = getattr(resp, "usage_metadata", None) or {}
        in_tokens = usage_meta.get("input_tokens", 0)
        out_tokens = usage_meta.get("output_tokens", 0)
        actual_model = (
            resp.response_metadata.get("model_name", config["model_name"])
            if hasattr(resp, "response_metadata")
            else config["model_name"]
        )
        run_hooks(
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
        self.send_event_to_user(
            task,
            AssistantEvent(
                content=resp.content,
                tool_calls=resp.tool_calls,
                in_tokens=in_tokens,
                out_tokens=out_tokens,
                model_name=actual_model,
            ),
        )
        from utils.usage import record_usage

        record_usage(in_tokens, out_tokens, len(resp.tool_calls), model=actual_model)
        return resp.tool_calls

    def _execute_tool_calls(self, tool_calls, name2tool, task, config) -> bool:
        """执行工具调用列表。返回 True 表示被 cancel。"""
        for tool_call in tool_calls:
            tool_resp_content = None
            try:
                tool = name2tool[tool_call["name"]]
            except KeyError as e:
                tool_resp_content = f"工具不存在: {tool_call['name']}"
            if tool_resp_content is None:
                try:
                    run_hooks(
                        HookEvent.PRE_TOOL_USE,
                        {
                            "tool_name": tool_call["name"],
                            "tool_call": tool_call,
                            "args": tool_call.get("args", {}),
                        },
                        config=config,
                        task=task,
                    )
                except HookError as e:
                    tool_resp_content = f"Hook blocked tool call: {e}"
            if tool_resp_content is None:
                permitted, llm_explanation = _check_permission(tool_call, config)
                if not permitted:
                    description = _permission_desc(tool_call)
                    try:
                        run_hooks(
                            HookEvent.PERMISSION_REQUEST,
                            {
                                "tool_name": tool_call["name"],
                                "tool_call": tool_call,
                                "args": tool_call.get("args", {}),
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
                        permitted = self.send_event_to_user(task, req)
                    except HookError as e:
                        permitted = f"Hook blocked permission request: {e}"
                    run_hooks(
                        HookEvent.PERMISSION_RESPONSE,
                        {
                            "tool_name": tool_call["name"],
                            "tool_call": tool_call,
                            "args": tool_call.get("args", {}),
                            "permitted": permitted is True,
                            "response": permitted,
                        },
                        config=config,
                        task=task,
                    )
                if permitted is True:
                    task.tool_cancel_event.clear()
                    config["tool_cancel_event"] = task.tool_cancel_event
                    self.send_event_to_user(
                        task,
                        ToolStartEvent(tool_call["name"], dict(tool_call["args"])),
                    )
                    try:
                        if "config" in tool.args:
                            tool_resp_content = tool.func(
                                **tool_call["args"], config=config
                            )
                        else:
                            tool_resp_content = tool.func(**tool_call["args"])
                    except Exception as e:
                        import traceback

                        logger.error(
                            f"工具调用失败 [{tool_call['name']}]\n参数: {tool_call['args']}\n{traceback.format_exc()}"
                        )
                        tool_resp_content = f"工具调用失败: {e}"
                else:
                    tool_resp_content = (
                        "用户拒绝: " + permitted
                        if isinstance(permitted, str) and permitted.strip()
                        else "用户拒绝执行"
                    )
            # 提取纯文本用于 UI 显示
            run_hooks(
                HookEvent.POST_TOOL_USE,
                {
                    "tool_name": tool_call["name"],
                    "tool_call": tool_call,
                    "args": tool_call.get("args", {}),
                    "result": _extract_text(tool_resp_content),
                },
                config=config,
                task=task,
            )
            display_content = (
                tool_resp_content
                if isinstance(tool_resp_content, str)
                else _extract_text(tool_resp_content)
            )
            self.send_event_to_user(
                task,
                ToolEvent(
                    name=tool_call["name"],
                    content=display_content,
                    tool_call_id=tool_call["id"],
                    args=tool_call.get("args", {}),
                ),
            )
            # 检查是否为多模态内容(如图片),需要特殊处理
            if isinstance(tool_resp_content, list) and any(
                isinstance(b, dict)
                and b.get("type") in ("image_url", "input_audio", "video_url")
                for b in tool_resp_content
            ):
                # 提取文本部分作为 tool 回复
                text_parts = [
                    b["text"]
                    for b in tool_resp_content
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
                ]
                task.messages.append(
                    {
                        "role": MessageRole.TOOL,
                        "name": tool_call["name"],
                        "content": (
                            "\n".join(text_parts) if text_parts else "(见下方图片)"
                        ),
                        "tool_call_id": tool_call["id"],
                    }
                )
                # 将多模态内容作为 user 消息,让 LLM 能看到图片
                task.messages.append(
                    {
                        "role": MessageRole.USER,
                        "content": tool_resp_content,
                    }
                )
            else:
                task.messages.append(
                    {
                        "role": MessageRole.TOOL,
                        "name": tool_call["name"],
                        "content": tool_resp_content,
                        "tool_call_id": tool_call["id"],
                    }
                )
            if task.cancel_event.is_set():
                task.status = AgentStatus.CANCELLED
                self.send_event_to_user(task, InterruptedEvent())
                return True
        return False

    def _run_cleanup(self, task, config):
        """设置最终状态,触发 SESSION_END 钩子,发送 EndEvent。"""
        if task.status == AgentStatus.RUNNING:
            task.status = AgentStatus.COMPLETED
        run_hooks(
            HookEvent.SESSION_END,
            {"status": task.status, "depth": config["depth"]},
            config=config,
            task=task,
        )
        self.send_event_to_user(task, EndEvent(depth=config["depth"]))

    @error_catch(logger)
    def run(
        self,
        user_message: str,
        system_message: Optional[str] = None,
        config: Optional[dict] = None,
        task: AgentTask = None,
        allowed_tools: Optional[list] = None,
    ):
        init_result = self._run_init(user_message, config, task)
        if init_result is None:
            return
        task.cancel_event.clear()
        if system_message is None:
            system_message = build_system_prompt(config)
        all_tools = get_tools()
        if allowed_tools:
            tools = [t for t in all_tools if t.name in allowed_tools]
        else:
            tools = all_tools
        name2tool = {tool.name: tool for tool in tools}
        while True:
            while True:
                if task.cancel_event.is_set():
                    task.status = AgentStatus.CANCELLED
                    self.send_event_to_user(task, InterruptedEvent())
                    break

                self.send_event_to_user(task, ThinkingStartEvent())

                resp = self._stream_response(task, system_message, config, tools)
                if resp is None:
                    break

                tool_calls = self._process_response(resp, task, config)
                content = task.drain_user_queue(self)
                if not tool_calls:
                    if content:
                        continue
                    break

                if task.cancel_event.is_set():
                    task.status = AgentStatus.CANCELLED
                    self.send_event_to_user(task, InterruptedEvent())
                    break
                if self._execute_tool_calls(tool_calls, name2tool, task, config):
                    break
                content = task.drain_user_queue(self)
            incomplete = TodoList.get_instance().get_incomplete()
            if (
                config.get("taskmaster_enabled")
                and not task.cancel_event.is_set()
                and incomplete
            ):
                msg = "[system]还有以下任务未完成,请继续:\n" + "\n".join(
                    f"- {item}" for item in incomplete
                )
                msg += f"\n\n请查看TodoList当前任务列表并继续完成剩余任务。如需与用户交流,请使用 {AskUserQuestion.name} 工具。"
                task.user_queue.put_nowait(msg)
                content = task.drain_user_queue(self)
                continue
            else:
                break

        self._run_cleanup(task, config)
        return
