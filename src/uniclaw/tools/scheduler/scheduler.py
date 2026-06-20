"""定时任务调度器 — 后台守护线程,定期检查并执行到期任务"""

import contextlib
import io
import json
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from croniter import croniter

from uniclaw.console.ui import info, warn, err
from uniclaw.context import get_app_dir, Scope


@dataclass
class Task:
    """定时任务数据"""

    name: str
    schedule: str
    action: str
    root_dir: str  # 创建任务时的会话工作目录(必填)
    enabled: bool = True
    last_run: str | None = None
    created: str | None = None
    updated: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(
            name=data.get("name", ""),
            schedule=data.get("schedule", ""),
            action=data.get("action", ""),
            root_dir=data.get("root_dir", ""),
            enabled=data.get("enabled", True),
            last_run=data.get("last_run"),
            created=data.get("created"),
            updated=data.get("updated"),
        )


def _parse_cron(cron_str: str) -> croniter:
    """解析 Cron 表达式

    支持标准 5 字段格式: 分 时 日 月 周
    最小粒度为 1 分钟,不支持秒级调度

    Returns:
        croniter: 解析后的 croniter 对象

    Raises:
        ValueError: 当 Cron 表达式无效时
    """
    s = cron_str.strip()
    try:
        return croniter(s)
    except (ValueError, KeyError) as e:
        raise ValueError(f"无效的 Cron 表达式: '{cron_str}'") from e


class Scheduler:
    """定时任务调度器(单例)"""

    _instance: "Scheduler | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._config_path: Path = get_app_dir(Scope.USER) / "scheduler.json"
        self._tasks: dict[str, Task] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="sched-task"
        )

    @classmethod
    def get_instance(cls) -> "Scheduler":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 配置 CRUD ──────────────────────────────────────────────────

    def load_config(self, config=None):
        """从 JSON 文件加载任务,转为 Task 对象"""
        if not self._config_path.exists():
            self._tasks = {}
            return
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
            tasks_raw = raw.get("tasks", {})
        except (json.JSONDecodeError, IOError) as e:
            warn(f"[scheduler] 加载配置失败: {e}", config)
            tasks_raw = {}
        self._tasks = {tid: Task.from_dict(data) for tid, data in tasks_raw.items()}

    def save_config(self):
        """将 Task 对象序列化为 JSON 写入文件"""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"tasks": {tid: task.to_dict() for tid, task in self._tasks.items()}}
        self._config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_task(
        self, name: str, schedule: str, action: str, root_dir: str, unique_by_name: bool = False, config=None
    ) -> str:
        """添加任务,自动生成 UUID 作为任务 ID

        schedule 格式为 Cron 表达式,例如:
        - '* * * * *' — 每分钟
        - '*/5 * * * *' — 每 5 分钟
        - '0 9 * * *' — 每天 9:00
        - '0 9 * * 1-5' — 工作日 9:00

        Returns:
            str: 成功时返回任务 ID

        Raises:
            ValueError: 当 Cron 表达式无效时
        """
        self.load_config(config)
        _parse_cron(schedule)
        now = datetime.now().isoformat(timespec="seconds")

        if unique_by_name and name:
            matches = [tid for tid, t in self._tasks.items() if t.name == name]
            if matches:
                primary = matches[0]
                task = self._tasks[primary]
                task.name = name
                task.schedule = schedule
                task.action = action
                task.root_dir = root_dir
                task.enabled = True
                task.updated = now
                for duplicate in matches[1:]:
                    del self._tasks[duplicate]
                self.save_config()
                return primary

        task_id = uuid.uuid4().hex[:8]
        self._tasks[task_id] = Task(
            name=name or task_id,
            schedule=schedule,
            action=action,
            root_dir=root_dir,
            enabled=True,
            last_run=now if unique_by_name else None,
            created=now,
        )
        self.save_config()
        return task_id

    def remove_task(self, task_id: str, config=None) -> bool:
        self.load_config(config)
        if task_id not in self._tasks:
            return False
        del self._tasks[task_id]
        self.save_config()
        return True

    def list_tasks(self, config=None) -> list[dict]:
        self.load_config(config)
        return [{"id": tid, **task.to_dict()} for tid, task in self._tasks.items()]

    def toggle_task(self, task_id: str, enabled: bool, config=None) -> bool:
        self.load_config(config)
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.enabled = enabled
        self.save_config()
        return True

    # ── 后台调度 ──────────────────────────────────────────────────

    def start(self, config=None):
        """启动后台守护线程"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, args=(config,), daemon=True, name="scheduler"
        )
        self._thread.start()
        info("[scheduler] 定时任务调度器已启动", config)

    def stop(self):
        """停止调度器"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._executor.shutdown(wait=False)

    def _run_loop(self, config=None):
        """后台循环:每 10 秒检查一次到期任务"""
        while not self._stop_event.is_set():
            try:
                self._check_and_run_tasks(config)
            except Exception as e:
                err(f"[scheduler] 调度器检查失败: {e}", config)
            self._stop_event.wait(10)

    def _check_and_run_tasks(self, config=None):
        """检查所有任务,执行到期的任务"""
        self.load_config(config)
        now = datetime.now()
        changed = False

        for task_id, task in self._tasks.items():
            if not task.enabled:
                continue

            cron = _parse_cron(task.schedule)
            if cron is None:
                continue

            if task.last_run is None:
                # 首次运行,计算上一次应该运行的时间
                prev_time = cron.get_prev(datetime)
                should_run = prev_time <= now
            else:
                last_dt = datetime.fromisoformat(task.last_run)
                next_time = cron.get_next(datetime, start_time=last_dt)
                should_run = next_time <= now

            if should_run:
                self._executor.submit(self._execute_task, task_id, task, config)
                task.last_run = now.isoformat(timespec="seconds")
                changed = True

        if changed:
            self.save_config()

    def _execute_task(self, task_id: str, task: Task, config=None):
        """执行单个任务"""
        action = task.action
        name = task.name or task_id
        info(f"[scheduler] 执行任务: {name}", config)

        try:
            if action.startswith("shell:"):
                cmd = action[6:].strip()
                cwd = task.root_dir if task.root_dir else None
                r = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    cwd=cwd,
                )
                if r.stdout.strip():
                    info(r.stdout.strip(), config)
                if r.stderr.strip():
                    warn(f"[stderr] {r.stderr.strip()}", config)

            elif action.startswith("agent:"):
                rest = action[6:].strip()
                # 解析 agent:type:message 格式
                if ":" in rest:
                    agent_type, message = rest.split(":", 1)
                    agent_type = agent_type.strip()
                    message = message.strip()
                else:
                    agent_type = "general-purpose"
                    message = rest

                from uniclaw.config import create_sub_agent_config
                from uniclaw.agent import MultiAgent
                from uniclaw.tools.multi_agent.sub_agent import load_agent_definitions

                root_dir = Path(task.root_dir) if task.root_dir else Path.cwd()
                config = create_sub_agent_config(
                    root_dir=root_dir,
                    name=f"scheduler:{name}",
                    prompt=message,
                )
                multi_agent = MultiAgent.get_instance()
                agent_def = load_agent_definitions(root_dir).get(agent_type)

                async def _run_agent():
                    sub_task = await multi_agent.start_sub_agent(
                        user_message=message,
                        system_prompt=None,
                        config=config,
                        agent_def=agent_def,
                    )
                    await multi_agent.wait(sub_task.id, timeout=300)
                    if sub_task.result:
                        info(str(sub_task.result), config)

                import asyncio
                main_loop = multi_agent.loop
                if main_loop and main_loop.is_running():
                    # 主事件循环已运行,调度到主循环
                    future = asyncio.run_coroutine_threadsafe(_run_agent(), main_loop)
                    future.result(timeout=310)
                else:
                    # 无主循环(如独立运行),创建新的
                    asyncio.run(_run_agent())

            elif action.startswith("py:"):
                code = action[3:].strip()
                stdout = io.StringIO()
                env = {"__builtins__": __builtins__}
                with contextlib.redirect_stdout(stdout):
                    try:
                        result = eval(code, env, env)
                    except SyntaxError:
                        exec(code, env, env)
                        result = env.get("result")
                output = stdout.getvalue().strip()
                if output:
                    info(output, config)
                if result is not None:
                    info(str(result), config)

            else:
                warn(f"[scheduler] 未知的 action 类型: {action}", config)

        except Exception as e:
            err(f"[scheduler] 任务 {name} 执行失败: {e}", config)
