"""定时任务调度器 — 后台守护线程,定期检查并执行到期任务"""
import contextlib
import io
import json
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path

from croniter import croniter

from console.ui import info, warn, err
from context import get_app_dir, Scope


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
        self._config: dict = {"tasks": {}}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @classmethod
    def get_instance(cls) -> "Scheduler":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 配置 CRUD ──────────────────────────────────────────────────

    def load_config(self) -> dict:
        if not self._config_path.exists():
            self._config = {"tasks": {}}
            return self._config
        try:
            self._config = json.loads(self._config_path.read_text(encoding="utf-8"))
            if "tasks" not in self._config:
                self._config["tasks"] = {}
        except (json.JSONDecodeError, IOError) as e:
            warn(f"[scheduler] 加载配置失败: {e}")
            self._config = {"tasks": {}}
        return self._config

    def save_config(self):
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_task(
        self, name: str, schedule: str, action: str, unique_by_name: bool = False
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
        self.load_config()
        _parse_cron(schedule)
        now = datetime.now().isoformat(timespec="seconds")

        if unique_by_name and name:
            matches = [
                task_id
                for task_id, task in self._config["tasks"].items()
                if task.get("name") == name
            ]
            if matches:
                primary = matches[0]
                self._config["tasks"][primary].update(
                    {
                        "name": name,
                        "schedule": schedule,
                        "action": action,
                        "enabled": True,
                        "updated": now,
                    }
                )
                for duplicate in matches[1:]:
                    del self._config["tasks"][duplicate]
                self.save_config()
                return primary

        task_id = uuid.uuid4().hex[:8]
        self._config["tasks"][task_id] = {
            "name": name or task_id,
            "schedule": schedule,
            "action": action,
            "enabled": True,
            "last_run": now if unique_by_name else None,
            "created": now,
        }
        self.save_config()
        return task_id

    def remove_task(self, task_id: str) -> bool:
        self.load_config()
        if task_id not in self._config["tasks"]:
            return False
        del self._config["tasks"][task_id]
        self.save_config()
        return True

    def list_tasks(self) -> list[dict]:
        self.load_config()
        tasks = []
        for tid, task in self._config["tasks"].items():
            tasks.append({"id": tid, **task})
        return tasks

    def toggle_task(self, task_id: str, enabled: bool) -> bool:
        self.load_config()
        if task_id not in self._config["tasks"]:
            return False
        self._config["tasks"][task_id]["enabled"] = enabled
        self.save_config()
        return True

    # ── 后台调度 ──────────────────────────────────────────────────

    def start(self):
        """启动后台守护线程"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="scheduler")
        self._thread.start()
        info("[scheduler] 定时任务调度器已启动")

    def stop(self):
        """停止调度器"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _run_loop(self):
        """后台循环：每 10 秒检查一次到期任务"""
        while not self._stop_event.is_set():
            try:
                self._check_and_run_tasks()
            except Exception as e:
                err(f"[scheduler] 调度器检查失败: {e}")
            self._stop_event.wait(10)

    def _check_and_run_tasks(self):
        """检查所有任务,执行到期的任务"""
        self.load_config()
        now = datetime.now()
        changed = False

        for task_id, task in self._config["tasks"].items():
            if not task.get("enabled", True):
                continue

            cron = _parse_cron(task["schedule"])
            if cron is None:
                continue

            last_run = task.get("last_run")
            if last_run is None:
                # 首次运行,计算上一次应该运行的时间
                prev_time = cron.get_prev(datetime)
                if prev_time <= now:
                    should_run = True
                else:
                    should_run = False
            else:
                last_dt = datetime.fromisoformat(last_run)
                next_time = cron.get_next(datetime, start_time=last_dt)
                should_run = next_time <= now

            if should_run:
                self._execute_task(task_id, task)
                task["last_run"] = now.isoformat(timespec="seconds")
                changed = True

        if changed:
            self.save_config()

    def _execute_task(self, task_id: str, task: dict):
        """执行单个任务"""
        action = task["action"]
        name = task.get("name", task_id)
        info(f"[scheduler] 执行任务: {name}")

        try:
            if action.startswith("shell:"):
                cmd = action[6:].strip()
                r = subprocess.run(
                    cmd, shell=True, capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    timeout=60,
                )
                if r.stdout.strip():
                    info(r.stdout.strip())
                if r.stderr.strip():
                    warn(f"[stderr] {r.stderr.strip()}")

            elif action.startswith("agent:"):
                message = action[6:].strip()
                from config import load_config
                from agent import MultiAgent, AgentTask
                config = load_config()
                multi_agent = MultiAgent.get_instance()
                agent_task = AgentTask(id=f"scheduler-{task_id}", name=f"scheduler:{task_id}", prompt=message)
                multi_agent.start_agent(message, agent_task, config=config)

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
                    info(output)
                if result is not None:
                    info(str(result))

            else:
                warn(f"[scheduler] 未知的 action 类型: {action}")

        except Exception as e:
            err(f"[scheduler] 任务 {name} 执行失败: {e}")
