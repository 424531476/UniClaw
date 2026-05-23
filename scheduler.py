"""定时任务调度器 — 后台守护线程，定期检查并执行到期任务"""
import json
import logging
import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

from context import get_app_dir, Scope

logger = logging.getLogger(__name__)


def _parse_schedule(schedule_str: str) -> timedelta | datetime | None:
    """解析调度字符串

    支持格式:
        every Ns/m/h/d — 重复执行间隔
        at YYYY-MM-DD HH:MM — 一次性执行时间

    Returns:
        timedelta: 重复执行间隔
        datetime: 一次性执行时间
        None: 解析失败
    """
    s = schedule_str.strip()

    # every Ns/m/h/d
    m = re.match(r"^every\s+(\d+)\s*([smhd])$", s, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        unit_map = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
        return timedelta(**{unit_map[unit]: n})

    # at YYYY-MM-DD HH:MM
    m = re.match(r"^at\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})$", s)
    if m:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")

    return None


class Scheduler:
    """定时任务调度器（单例）"""

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
            logger.warning(f"加载调度配置失败: {e}")
            self._config = {"tasks": {}}
        return self._config

    def save_config(self):
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_task(self, task_id: str, name: str, schedule: str, action: str):
        """添加任务。如果 task_id 已存在则抛 ValueError"""
        self.load_config()
        if task_id in self._config["tasks"]:
            raise ValueError(f"任务 '{task_id}' 已存在")
        if _parse_schedule(schedule) is None:
            raise ValueError(f"无效的调度格式: '{schedule}'，支持 'every Ns/m/h/d' 或 'at YYYY-MM-DD HH:MM'")
        self._config["tasks"][task_id] = {
            "name": name or task_id,
            "schedule": schedule,
            "action": action,
            "enabled": True,
            "last_run": None,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        self.save_config()

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
        logger.info("定时任务调度器已启动")

    def stop(self):
        """停止调度器"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _run_loop(self):
        """后台循环：每 30 秒检查一次到期任务"""
        while not self._stop_event.is_set():
            try:
                self._check_and_run_tasks()
            except Exception as e:
                logger.error(f"调度器检查失败: {e}")
            self._stop_event.wait(10)

    def _check_and_run_tasks(self):
        """检查所有任务，执行到期的任务"""
        self.load_config()
        now = datetime.now()
        changed = False

        for task_id, task in self._config["tasks"].items():
            if not task.get("enabled", True):
                continue

            parsed = _parse_schedule(task["schedule"])
            if parsed is None:
                continue

            should_run = False

            if isinstance(parsed, timedelta):
                # 重复任务：last_run + interval <= now
                last_run = task.get("last_run")
                if last_run is None:
                    should_run = True
                else:
                    last_dt = datetime.fromisoformat(last_run)
                    if last_dt + parsed <= now:
                        should_run = True
            elif isinstance(parsed, datetime):
                # 一次性任务：now >= target 且未执行过
                if task.get("last_run") is None and now >= parsed:
                    should_run = True

            if should_run:
                self._execute_task(task_id, task)
                task["last_run"] = now.isoformat(timespec="seconds")
                # 一次性任务执行后自动禁用
                if isinstance(parsed, datetime):
                    task["enabled"] = False
                changed = True

        if changed:
            self.save_config()

    def _execute_task(self, task_id: str, task: dict):
        """执行单个任务"""
        action = task["action"]
        name = task.get("name", task_id)
        logger.info(f"执行定时任务: {name} ({action})")
        print(f"\n[scheduler] 执行任务: {name}")

        try:
            if action.startswith("shell:"):
                cmd = action[6:].strip()
                r = subprocess.run(
                    cmd, shell=True, capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    timeout=60,
                )
                if r.stdout.strip():
                    print(r.stdout.strip())
                if r.stderr.strip():
                    print(f"[stderr] {r.stderr.strip()}")

            elif action.startswith("agent:"):
                message = action[6:].strip()
                from config import get_config, get_config_dict
                from agent import MultiAgent, AgentTask
                config = get_config_dict(get_config())
                multi_agent = MultiAgent.get_instance()
                task = AgentTask(id=f"scheduler-{task_id}", name=f"scheduler:{task_id}", prompt=message)
                multi_agent.start(message, task, config=config)

            else:
                print(f"[scheduler] 未知的 action 类型: {action}")

        except Exception as e:
            logger.error(f"任务 {task_id} 执行失败: {e}")
            print(f"[scheduler] 任务 {name} 执行失败: {e}")
