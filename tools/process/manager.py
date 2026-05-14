import threading
import uuid

from .models import ProcessStatus
from .process import ManagedProcess


class ProcessManager:
    """全局子进程管理器（单例）"""

    _instance: "ProcessManager | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._processes: dict[str, ManagedProcess] = {}
        self._max_concurrent: int = 10
        self._monitor_thread: threading.Thread | None = None
        self._monitor_running: bool = False
        self._manager_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ProcessManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _ensure_monitor(self):
        """确保后台监控线程在运行"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True,
        )
        self._monitor_thread.start()

    def _monitor_loop(self):
        """后台监控：检测进程自然退出"""
        while self._monitor_running:
            with self._manager_lock:
                for proc in list(self._processes.values()):
                    if proc.status == ProcessStatus.RUNNING:
                        proc.update_status_from_poll()
            threading.Event().wait(10)

    def start_process(self, command: str, name: str = "", cwd: str = "") -> str:
        """启动新进程，返回进程 ID 或错误信息"""
        with self._manager_lock:
            if len(self._processes) >= self._max_concurrent:
                return f"错误：已达到最大并发进程数（{self._max_concurrent}）"

            process_id = uuid.uuid4().hex[:8]
            proc = ManagedProcess(process_id, command, cwd, name)

            try:
                proc.start()
            except Exception as e:
                return f"错误：进程启动失败 - {e}"

            self._processes[process_id] = proc

        self._ensure_monitor()

        return f"进程已启动\n  ID: {process_id}\n  名称: {proc.name}\n  PID: {proc.pid}\n  状态: {proc.status.value}"

    def stop_process(self, process_id: str, force: bool = False) -> str:
        """停止进程并删除记录"""
        with self._manager_lock:
            proc = self._processes.get(process_id)
            if not proc:
                return f"错误：进程 '{process_id}' 不存在"

            name = proc.name
            proc.stop(force=force)
            del self._processes[process_id]

        return f"进程已停止并移除: {name} (ID:{process_id})"

    def get_output(self, process_id: str, lines: int = 50) -> str:
        """获取进程输出"""
        proc = self._processes.get(process_id)
        if not proc:
            return f"错误：进程 '{process_id}' 不存在"
        return proc.get_output(lines)

    def send_input(self, process_id: str, input_text: str) -> str:
        """向进程发送输入"""
        proc = self._processes.get(process_id)
        if not proc:
            return f"错误：进程 '{process_id}' 不存在"
        if proc.send_input(input_text):
            return f"已向进程 {process_id} 发送输入"
        return f"错误：无法向进程 {process_id} 发送输入（进程可能已退出或 stdin 已关闭）"

    def list_processes(self) -> str:
        """列出所有进程"""
        with self._manager_lock:
            procs = list(self._processes.values())

        if not procs:
            return "当前没有管理的进程。"

        lines = [f"共 {len(procs)} 个进程:"]
        for p in procs:
            info = p.to_dict()
            uptime = f"{info['uptime_seconds']}s"
            lines.append(
                f"  [{info['status']}] {info['name']} (ID:{info['id']} | PID:{info['pid']} | "
                f"运行:{uptime} | 输出:{info['output_lines']}行)"
            )
        return "\n".join(lines)

    def cleanup_finished(self) -> str:
        """清理已自然退出的进程"""
        removed = 0
        with self._manager_lock:
            to_remove = [
                pid for pid, proc in self._processes.items()
                if proc.status in (ProcessStatus.STOPPED, ProcessStatus.FAILED)
            ]
            for pid in to_remove:
                del self._processes[pid]
                removed += 1

        if removed == 0:
            return "没有需要清理的进程。"
        return f"已清理 {removed} 个进程"

    def shutdown(self):
        """关闭所有进程并停止监控"""
        self._monitor_running = False
        with self._manager_lock:
            for proc in self._processes.values():
                proc.stop(force=True)
            self._processes.clear()
