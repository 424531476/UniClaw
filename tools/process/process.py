import os
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime

from .models import ProcessStatus


class ManagedProcess:
    """封装单个子进程的生命周期管理"""

    def __init__(self, process_id: str, command: str, cwd: str, name: str = ""):
        self.process_id = process_id
        self.command = command
        self.cwd = cwd
        self.name = name or command[:50]
        self.status = ProcessStatus.PENDING
        self.pid: int | None = None
        self.returncode: int | None = None
        self.start_time: float = 0.0

        self._proc: subprocess.Popen | None = None
        self._stdout_buffer: deque = deque(maxlen=2000)
        self._stderr_buffer: deque = deque(maxlen=2000)
        self._lock = threading.Lock()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def start(self):
        """启动进程"""
        kwargs = dict(
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            cwd=self.cwd,
            shell=True,
        )
        if sys.platform != "win32":
            kwargs["start_new_session"] = True

        self._proc = subprocess.Popen(self.command, **kwargs)
        self.pid = self._proc.pid
        self.start_time = time.time()
        self.status = ProcessStatus.RUNNING

        # 启动 stdout 读取线程
        self._stdout_thread = threading.Thread(
            target=self._reader, args=(self._proc.stdout, self._stdout_buffer),
            daemon=True,
        )
        self._stdout_thread.start()

        # 启动 stderr 读取线程
        self._stderr_thread = threading.Thread(
            target=self._reader, args=(self._proc.stderr, self._stderr_buffer),
            daemon=True,
        )
        self._stderr_thread.start()

    def _reader(self, stream, buffer: deque):
        """后台线程持续读取进程输出"""
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n\r")
                timestamp = time.time()
                buffer.append((timestamp, text))
        except (ValueError, OSError):
            # stream 已关闭
            pass

        # 流结束，检查进程退出码
        if self._proc and self._proc.poll() is not None:
            with self._lock:
                if self.status == ProcessStatus.RUNNING:
                    self.returncode = self._proc.returncode
                    self.status = (
                        ProcessStatus.STOPPED if self.returncode == 0
                        else ProcessStatus.FAILED
                    )

    def stop(self, force: bool = False):
        """停止进程"""
        if self.status not in (ProcessStatus.RUNNING, ProcessStatus.PENDING):
            return

        with self._lock:
            self.status = ProcessStatus.STOPPING

        if self._proc and self._proc.poll() is None:
            if force:
                self._kill_proc_tree(self._proc.pid)
            else:
                # 先尝试温和终止
                try:
                    if sys.platform == "win32":
                        self._kill_proc_tree(self._proc.pid)
                    else:
                        import signal
                        os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

                # 等待退出，超时后强制终止
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._kill_proc_tree(self._proc.pid)
                    try:
                        self._proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass

        # 等待读取线程结束
        if self._stdout_thread and self._stdout_thread.is_alive():
            self._stdout_thread.join(timeout=2)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2)

        with self._lock:
            if self._proc:
                self.returncode = self._proc.returncode
            self.status = ProcessStatus.STOPPED

    @staticmethod
    def _kill_proc_tree(pid: int):
        """终止进程及其子进程树"""
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

    def is_alive(self) -> bool:
        """检查进程是否仍在运行"""
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def update_status_from_poll(self):
        """通过 poll 检测进程是否已自然退出，更新状态"""
        if self._proc and self.status == ProcessStatus.RUNNING:
            rc = self._proc.poll()
            if rc is not None:
                with self._lock:
                    self.returncode = rc
                    self.status = (
                        ProcessStatus.STOPPED if rc == 0
                        else ProcessStatus.FAILED
                    )

    def get_output(self, n: int = 50) -> str:
        """获取最近 n 行输出，stdout 和 stderr 合并按时间排序"""
        with self._lock:
            all_lines = list(self._stdout_buffer) + list(self._stderr_buffer)

        if not all_lines:
            return "(无输出)"

        # 按时间排序
        all_lines.sort(key=lambda x: x[0])

        # 取最后 n 行
        recent = all_lines[-n:]
        formatted = []
        for ts, text in recent:
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            formatted.append(f"{time_str} | {text}")

        return "\n".join(formatted)

    def send_input(self, text: str) -> bool:
        """向进程发送标准输入"""
        if self.status not in (ProcessStatus.RUNNING,):
            return False
        if not self._proc or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write((text + "\n").encode("utf-8"))
            self._proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def to_dict(self) -> dict:
        """返回进程摘要信息"""
        uptime = time.time() - self.start_time if self.start_time else 0
        with self._lock:
            output_count = len(self._stdout_buffer) + len(self._stderr_buffer)
        return {
            "id": self.process_id,
            "name": self.name,
            "command": self.command,
            "status": self.status,
            "pid": self.pid,
            "uptime_seconds": round(uptime, 1),
            "output_lines": output_count,
            "returncode": self.returncode,
        }
