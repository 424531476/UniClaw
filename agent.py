from concurrent.futures import Future, ThreadPoolExecutor
from enum import Enum
import os
import threading
import queue
import time
from typing import Any, Optional
import uuid
from llm import stream
from tools import get_tools
from dataclasses import dataclass, field
from context import build_system_prompt
from config import Permissions, get_config, get_config_dict
from tools.multi_agent.sub_agent import AgentDefinition
from utils.git import create_worktree, get_git_root, remove_worktree
from utils.truncation import truncate_text_by_lines
from utils.logger import get_logger
import traceback

logger = get_logger("agent")


class MessageRole(Enum):
    """
    消息角色枚举

    定义了对话中不同角色的类型:
        SYSTEM: 系统消息，用于设置助手的行为和背景
        USER: 用户消息，表示用户输入的内容
        ASSISTANT: 助手消息，表示助手的回复
        TOOL: 工具消息，表示工具调用的结果
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
class TooStartlEvent:
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


class PermissionRequestEvent(ReturnEvent):
    def __init__(self, description: str, tool_call: dict = None):
        super().__init__(False)
        self.description: str = description
        self.tool_call: dict = tool_call or {}


def _extract_text(content) -> str:
    """从多模态内容中提取纯文本，用于 UI 显示"""
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


def _check_permission(tc: dict, config: dict) -> bool:
    """检查工具调用是否需要用户权限确认。

    根据配置的权限模式和工具类型，判断是否自动批准该工具调用。
    某些安全操作或特定模式下的操作可以自动放行，其他操作需要用户手动确认。

    Args:
        tc (dict): 工具调用字典，包含以下键：
            - name (str): 工具名称，如 "Read", "Write", "Bash" 等
            - args (dict): 工具参数，不同工具有不同的参数字段
        config (dict): 配置字典，包含以下键：
            - permission_mode (str): 权限模式，可选值为 Permissions.ACCEPT_ALL,
              Permissions.MANUAL, Permissions.PLAN 等
            - cwd (str, optional): 当前工作目录路径

    Returns:
        bool: 如果操作可以自动批准（无需询问用户）返回 True，否则返回 False

    Note:
        - 计划模式切换工具始终自动批准
        - ACCEPT_ALL 模式下所有操作自动批准
        - MANUAL 模式下所有操作都需要用户确认
        - 只读类工具和记忆/技能列表工具自动批准
        - PLAN 模式下，写入计划目录的 Write 操作自动批准
        - Bash 命令通过安全检查后自动批准
        - 写入当前工作目录下文件的 Write 操作自动批准
        - 其他情况默认需要用户确认
    """
    perm_mode = config.get("permission_mode", Permissions.AUTO)
    name = tc["name"]

    # 计划模式工具始终自动批准
    if name in ("enter_plan_mode", "exit_plan_mode"):
        return True

    if perm_mode == Permissions.ACCEPT_ALL:
        return True
    if perm_mode == Permissions.MANUAL:
        return False  # 始终询问

    # 只读类工具和记忆/技能管理工具自动批准
    if name in (
        "Read",
        "ReadImage",
        "Glob",
        "Grep",
        "RunCode",
        "webfetch",
        "websearch",
        "memory_save",
        "memory_delete",
        "memory_list",
        "memory_search",
        "schedule_create",
        "schedule_list",
        "schedule_remove",
        "schedule_toggle",
        "skill_list",
        "sleep_timer",
    ):
        return True

    # PLAN 模式下的特殊处理
    if perm_mode == Permissions.PLAN:

        # Write 工具：写入计划目录自动放行
        if name == "Write":
            from pathlib import Path
            from context import get_app_dir, Scope

            file_path = tc["args"].get("file_path", "")
            plans_dir = get_app_dir(Scope.USER.value) / "plans"
            try:
                abs_file = Path(file_path).resolve()
                if abs_file.is_relative_to(plans_dir.resolve()):
                    return True
            except (ValueError, OSError):
                pass
        return False

    # Bash 命令安全检查（独立判断流程）
    if name == "Bash":
        from tools.security import is_safe_bash

        command = tc["args"].get("command", "")

        # 再检查系统内置的安全前缀白名单
        return is_safe_bash(command)

    # 其他工具的持久化规则检查
    from tools.security import check_saved_tool_rule

    if check_saved_tool_rule(name):
        return True

    # Write 工具：如果写入的是 cwd 目录下的文件，则自动放行
    if name == "Write":
        from pathlib import Path

        file_path = tc["args"].get("file_path", "")
        cwd = config.get("cwd", None)

        # 如果 cwd 为 None，保守处理，需要用户确认
        if isinstance(cwd, str) and cwd:
            try:
                # 将路径解析为绝对路径并检查是否在 cwd 下
                abs_file = Path(file_path).resolve()
                abs_cwd = Path(cwd).resolve()

                # 检查文件路径是否是 cwd 的子路径
                if abs_file.is_relative_to(abs_cwd):
                    return True
            except (ValueError, Exception):
                # 如果路径解析失败，保守处理，需要用户确认
                pass

    return False  # Write (非cwd目录), Edit → 询问


def _permission_desc(tc: dict) -> str:
    """生成权限请求的美观描述信息

    Args:
        tc: 工具调用字典，包含工具名称和参数

    Returns:
        格式化的权限请求描述字符串
    """
    name = tc["name"]
    inp = tc["args"]

    # Bash 命令执行
    if name == "Bash":
        command = inp.get("command", "")
        return f"🖥️  运行 Shell 命令:\n   {command}"

    # 文件写入操作
    if name == "Write":
        file_path = inp.get("file_path", "")
        return f"📝 写入文件:\n   {file_path}"

    # 文件编辑操作
    if name == "Edit":
        file_path = inp.get("file_path", "")
        return f"✏️  编辑文件:\n   {file_path}"

    # 其他工具调用
    return f"🔧 调用工具: {name}\n   参数: {list(inp.values())[:2]}"


class MessageQueue:
    """
    消息队列类，支持基于任务ID的消息缓冲和转发机制。

    该队列采用双层结构：
    - message_queue: 主队列，存储当前活跃任务的消息
    - temp_queue: 临时队列，缓存其他任务的消息

    当遇到边界事件（AssistantEvent/ToolEvent）且主队列为空时，
    会自动将临时队列的内容转发到主队列。

    注意：该类是线程安全的，使用 RLock 保护所有共享状态的访问。
    """

    def __init__(self):
        """初始化消息队列"""
        self.message_queue = queue.Queue()
        self.temp_queue: Optional[MessageQueue] = None
        self.last_task = None
        self._lock = threading.RLock()  # 使用可重入锁支持递归调用

    def put(self, data):
        """
        将消息放入队列。

        如果消息的任务ID与当前活跃任务相同，则放入主队列；
        否则放入临时队列进行缓冲。

        Args:
            data: 元组 (task, event)，其中 at 是任务ID对象引用，event 是事件对象
        """
        with self._lock:
            task, event = data

            # 使用对象引用比较（is），确保同一任务的消息进入同一队列
            if self.last_task is None or task is self.last_task:
                self.message_queue.put(data)
                # 更新当前活跃任务ID
                self.last_task = task
            else:
                # 不同任务ID，创建或使用临时队列
                if self.temp_queue is None:
                    self.temp_queue = MessageQueue()
                self.temp_queue.put(data)

    def get(self):
        """
        从主队列获取一条消息。

        如果获取到边界事件（AssistantEvent/ToolEvent）且主队列为空，
        则触发转发机制，将临时队列的内容转移到主队列。

        Returns:
            元组 (task, event)

        Raises:
            queue.Empty: 当队列为空时抛出
        """
        with self._lock:
            data = self.message_queue.get()
            task, event = data

            # 检查是否需要转发：主队列空且遇到边界事件
            if self.message_queue.empty() and isinstance(
                event, (AssistantEvent, ToolEvent)
            ):
                self._forward()

            return data

    def _forward(self):
        """
        将临时队列的内容转发到主队列。

        该方法会递归处理多层嵌套的临时队列，
        并将最内层队列的引用提升到当前层级。

        注意：此方法在调用时必须已持有锁（由 get() 或外部调用者保证）。
        """
        while self.temp_queue and self.temp_queue._size() > 0:
            # 将临时队列的主队列提升为当前队列
            while not self.temp_queue.message_queue.empty():
                self.message_queue.put(self.temp_queue.message_queue.get())
            # 同步更新 last_task
            self.last_task = self.temp_queue.last_task
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
        计算队列中的消息总数（包括主队列和所有临时队列）。

        Returns:
            int: 消息总数
        """
        with self._lock:
            main_size = self.message_queue.qsize()
            temp_size = self.temp_queue._size() if self.temp_queue else 0
            return main_size + temp_size


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
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
    status: str = AgentStatus.PENDING.value
    result: Optional[str] = None
    # depth: int = 0

    worktree_path: str = ""
    worktree_branch: str = ""
    cancel_event = threading.Event()
    future: Optional[Future] = field(default=None, repr=False)
    event_queue: Optional[queue.Queue] = field(default=None, repr=False)
    is_background: bool = field(default=False)

    def drain_user_queue(self) -> bool:
        """从 user_queue 取出所有待处理消息，合并为一条用户消息追加到 messages。"""
        extras = []
        while not self.user_queue.empty():
            try:
                extras.append(self.user_queue.get_nowait())
            except Exception:
                break
        if extras:
            self.messages.append(
                {"role": MessageRole.USER.value, "content": "\n\n".join(extras)}
            )
            return True
        return False


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
        self.pool = ThreadPoolExecutor(4)
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
            event.return_event.wait()
            return event.content

    def wait(self, task_id: str, timeout: float = None):
        """
        等待指定任务完成并返回任务对象。

        该方法会阻塞当前线程直到任务完成或超时。如果任务已经完成，立即返回；
        如果任务尚未完成，则等待其执行完毕。

        Args:
            task_id (str): 任务的唯一标识符，用于查找对应的任务对象。
            timeout (float, optional): 等待超时时间（秒）。如果为None，则无限期等待直到任务完成。
                                      如果指定了超时时间，超过该时间后任务仍未完成则抛出异常。

        Returns:
            AgentTask or None: 返回对应的任务对象。如果找不到指定的task_id，则返回None。
                              无论任务是否成功执行，都会返回任务对象（包含执行状态和结果）。

        Note:
            - 如果任务不存在（task_id无效），返回None。
            - 如果任务没有关联的future对象，直接返回任务对象（可能任务还未开始执行）。
            - 如果任务执行过程中发生异常，仍然返回任务对象，可以通过检查任务状态获取异常信息。
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
        task.status = AgentStatus.PENDING.value
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
            status=AgentStatus.PENDING.value,
        )
        self.id2AgentTask[task.id] = task
        config = dict(config)
        config["depth"] += 1
        if agent_def:
            if agent_def.model_name:
                config["model_name"] = agent_def.model_name
            if agent_def.system_prompt:
                system_prompt = (
                    agent_def.system_prompt.rstrip() + "\n\n" + system_prompt
                )
        cwd = config["cwd"] if config["cwd"] else os.getcwd()
        if isolation:
            git_root = get_git_root(cwd)
            if not git_root:
                task.status = AgentStatus.FAILED.value
                task.result = "isolation需要git仓库"
                return task
            try:
                worktree_path, worktree_branch = create_worktree(git_root)
            except Exception as e:
                task.status = AgentStatus.FAILED.value
                task.result = f"isolation创建工作树失败: {e}"
                return task
            task.worktree_path = worktree_path
            task.worktree_branch = worktree_branch
            notice = (
                f"\n\n[注意：你正在一个隔离的 git worktree 中工作，位于 "
                f"{worktree_path}（分支：{worktree_branch}）。"
                f"你的更改与主工作区 {git_root} 隔离。"
                f"在完成之前提交你的更改，以便可以审查/合并。]"
            )
            system_prompt = system_prompt + notice
            config["cwd"] = worktree_path

        def _run_proc(user_message, system_prompt, config, task: AgentTask):
            try:
                task.user_queue.put(user_message)
                while not task.user_queue.empty():
                    msg = task.user_queue.get()
                    self.run(msg, system_prompt, config, task)
                    if task.cancel_event.is_set():
                        task.result = "任务已取消。"
                        return
                task.result = self.get_assistant_messages(task.messages)
            except Exception as e:
                task.result = f"任务处理失败：{str(e)}"
                task.status = AgentStatus.FAILED.value
            finally:
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

    def list_tasks(self) -> AgentTask:
        return list(self.id2AgentTask.values())

    def send_message(self, task_id: str, message: str) -> bool:
        task = self.id2AgentTask.get(task_id)
        if task is None:
            return False
        if task.status not in (AgentStatus.RUNNING.value, AgentStatus.PENDING.value):
            return False
        task.user_queue.put_nowait(message)
        return True

    def run(
        self,
        user_message: str,
        system_message: Optional[str] = None,
        config: Optional[dict] = None,
        task: AgentTask = None,
    ):
        if config is None:
            config = get_config_dict(get_config())
        if config["depth"] >= config["max_agent_depth"]:
            task.status = AgentStatus.FAILED.value
            task.result = f"错误：超过最大深度 ({config["max_agent_depth"]})"
            return task
        task.status = AgentStatus.RUNNING.value
        if system_message is None:
            system_message = build_system_prompt(config)
        tools = get_tools()
        name2tool = {tool.name: tool for tool in tools}
        task.messages.append({"role": MessageRole.USER.value, "content": user_message})

        while True:
            if task.cancel_event.is_set():
                task.status = AgentStatus.CANCELLED.value
                break
            self.send_event_to_user(task, ThinkingStartEvent())

            messages = [
                {"role": MessageRole.SYSTEM.value, "content": system_message},
                *task.messages,
            ]

            try:
                resp = None
                for chunk in stream(
                    messages=messages,
                    model_name=config["model_name"],
                    temperature=config["temperature"],
                    max_tokens=config["max_tokens"],
                    top_p=config["top_p"],
                    tools=tools,
                ):
                    if resp is None:
                        resp = chunk
                    else:
                        resp += chunk
                    if chunk.content:
                        self.send_event_to_user(task, TextChunkEvent(chunk.content))
            except Exception as e:
                import traceback

                error_traceback = traceback.format_exc()
                logger.error(error_traceback)
                self.send_event_to_user(
                    task,
                    TextChunkEvent(f"\n⚠️ 模型请求失败：{str(e)}\n"),
                )
                
                task.status = AgentStatus.FAILED.value
                break
            task.messages.append(
                {
                    "role": MessageRole.ASSISTANT.value,
                    "content": resp.content if resp.content else "",
                    "tool_calls": resp.tool_calls,
                }
            )

            usage_meta = getattr(resp, "usage_metadata", None) or {}
            in_tokens = usage_meta.get("input_tokens", 0)
            out_tokens = usage_meta.get("output_tokens", 0)
            actual_model = (
                resp.response_metadata.get("model_name", config["model_name"])
                if hasattr(resp, "response_metadata")
                else config["model_name"]
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

            record_usage(in_tokens, out_tokens, len(resp.tool_calls))
            if len(resp.tool_calls) == 0:
                if task.drain_user_queue():
                    continue
                else:
                    break
            for tool_call in resp.tool_calls:
                tool = name2tool[tool_call["name"]]
                permitted = _check_permission(tool_call, config)
                if not permitted:
                    req = PermissionRequestEvent(
                        description=_permission_desc(tool_call),
                        tool_call=tool_call,
                    )
                    permitted = self.send_event_to_user(task, req)
                if permitted is True:
                    self.send_event_to_user(
                        task, TooStartlEvent(tool_call["name"], dict(tool_call["args"]))
                    )
                    if "config_param" in tool.args:
                        tool_call["args"]["config_param"] = config
                    try:
                        tool_resp = tool.invoke(tool_call)
                        if "config_param" in tool.args:
                            tool_call["args"].pop("config_param", None)
                        tool_resp_content = tool_resp.content
                    except Exception as e:
                        logger.error(
                            f"工具调用失败 [{tool_call['name']}]\n参数: {tool_call['args']}\n{traceback.format_exc()}"
                        )
                        tool_resp_content = f"工具调用失败: {e}"
                else:
                    tool_resp_content = (
                        permitted if isinstance(permitted, str) else "用户拒绝执行"
                    )
                # 提取纯文本用于 UI 显示
                display_content = (
                    tool_resp_content
                    if isinstance(tool_resp_content, str)
                    else _extract_text(tool_resp_content)
                )
                self.send_event_to_user(
                    task,
                    ToolEvent(
                        name=tool_call["name"],
                        content=truncate_text_by_lines(
                            display_content, max_chars=1000, keep_ratio=0.8
                        ),
                        tool_call_id=tool_call["id"],
                        args=tool_call.get("args", {}),
                    ),
                )

                task.messages.append(
                    {
                        "role": MessageRole.TOOL.value,
                        "name": tool_call["name"],
                        "content": tool_resp_content,
                        "tool_call_id": tool_call["id"],
                    }
                )
            task.drain_user_queue()
        self.send_event_to_user(task, EndEvent(depth=config["depth"]))
