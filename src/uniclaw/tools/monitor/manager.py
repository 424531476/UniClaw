import re
import subprocess
import threading
import uuid
from datetime import datetime

from .models import Monitor, MonitorStatus


class MonitorManager:
    """全局进程监控管理器(单例)"""

    _instance: "MonitorManager | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._monitors: dict[str, Monitor] = {}
        self._max_concurrent: int = 10
        self._manager_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "MonitorManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def start_monitor(
        self,
        command: str,
        pattern: str,
        description: str,
        timeout: int,
        notify_model: bool = True,
        task=None,
        cwd: str = "",
    ) -> str:
        """启动新进程监控"""
        with self._manager_lock:
            if len(self._monitors) >= self._max_concurrent:
                return f"错误:已达到最大并发数({self._max_concurrent})"

            # 验证正则表达式(如果提供了 pattern)
            if pattern:
                try:
                    re.compile(pattern)
                except re.error as e:
                    return f"错误:无效的正则表达式 - {e}"

            monitor_id = uuid.uuid4().hex[:8]
            monitor = Monitor(
                monitor_id, command, pattern, description, timeout, notify_model, cwd
            )
            monitor._task = task

            try:
                monitor.process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    cwd=cwd if cwd else None,
                )
            except Exception as e:
                return f"错误:启动失败 - {e}"

            self._monitors[monitor_id] = monitor

        # 启动读取线程
        monitor.thread = threading.Thread(
            target=self._read_output,
            args=(monitor,),
            daemon=True,
        )
        monitor.thread.start()

        notify_info = ""
        if pattern:
            notify_info = "(匹配时通知模型+桌面)" if notify_model else "(匹配时仅通知桌面)"
        else:
            notify_info = "(仅记录输出)"

        desc_part = f" ({description})" if description else ""
        return (
            f"进程已启动\n"
            f"  ID: {monitor_id}\n"
            f"  命令: {command}{desc_part}\n"
            f"  匹配模式: {pattern or '无'}\n"
            f"  通知: {notify_info}"
        )

    def _read_output(self, monitor: Monitor):
        """读取进程输出并匹配模式"""
        import time

        deadline = None
        if monitor.timeout > 0:
            deadline = time.time() + monitor.timeout

        try:
            for line in monitor.process.stdout:
                line = line.rstrip()
                if not line:
                    continue

                # 保存输出
                monitor.output_lines.append(line)

                # 检查是否匹配(如果有 pattern)
                if monitor.pattern and re.search(monitor.pattern, line):
                    monitor.matched_lines.append(line)
                    monitor.match_time = datetime.now()
                    monitor.status = MonitorStatus.MATCHED
                    # 通知
                    self._notify_match(monitor, line)

                # 检查超时
                if deadline and time.time() > deadline:
                    monitor.status = MonitorStatus.TIMEOUT
                    break

            # 进程正常结束
            if monitor.status == MonitorStatus.RUNNING:
                monitor.status = MonitorStatus.STOPPED

        except Exception:
            if monitor.status == MonitorStatus.RUNNING:
                monitor.status = MonitorStatus.ERROR

        finally:
            # 确保进程已结束
            if monitor.process and monitor.process.poll() is None:
                try:
                    monitor.process.terminate()
                except Exception:
                    pass

    def _notify_match(self, monitor: Monitor, line: str):
        """匹配成功时通知用户和模型"""
        # 1. 发送桌面通知给用户
        try:
            from ..notify import push_notification
            desc = f" [{monitor.description}]" if monitor.description else ""
            msg = f"监控{desc}匹配到: {line[:100]}"
            push_notification.invoke({"message": msg, "title": "UniClaw 监控"})
        except Exception:
            pass

        # 2. 通知模型
        if monitor.notify_model and monitor._task:
            try:
                desc = (
                    f"[{monitor.description}]"
                    if monitor.description
                    else f"[监控 {monitor.id}]"
                )
                system_msg = (
                    f"[system](monitor) {desc} 监控匹配成功！\n"
                    f"  匹配模式: {monitor.pattern}\n"
                    f"  匹配内容: {line}\n"
                    f"  监控 ID: {monitor.id}\n"
                    f"请根据匹配结果继续处理。"
                )
                monitor._task.user_queue.put_nowait(system_msg)
            except Exception:
                pass

    def stop_monitor(self, monitor_id: str) -> str:
        """停止进程"""
        with self._manager_lock:
            monitor = self._monitors.get(monitor_id)
            if not monitor:
                return f"错误:进程 '{monitor_id}' 不存在"

            monitor.status = MonitorStatus.STOPPED
            if monitor.process:
                try:
                    monitor.process.terminate()
                except Exception:
                    pass
            del self._monitors[monitor_id]

        return f"进程已停止: {monitor_id}"

    def list_monitors(self) -> str:
        """列出所有进程"""
        with self._manager_lock:
            monitors = list(self._monitors.values())

        if not monitors:
            return "当前没有运行中的进程。"

        lines = [f"共 {len(monitors)} 个进程:"]
        for m in monitors:
            info = m.to_dict()
            uptime = f"{info['uptime_seconds']}s"
            lines.append(
                f"  [{info['status']}] {info['description'] or info['command'][:30]} "
                f"(ID:{info['id']} | 运行:{uptime} | 输出:{info['output_lines']}行)"
            )
        return "\n".join(lines)

    def get_output(self, monitor_id: str, lines: int = 50) -> str:
        """获取进程输出"""
        with self._manager_lock:
            monitor = self._monitors.get(monitor_id)
            if not monitor:
                return f"错误:进程 '{monitor_id}' 不存在"

            if not monitor.output_lines:
                return f"进程 {monitor_id} 暂无输出。"

            output = list(monitor.output_lines)[-lines:]
            return "\n".join(output)

    def send_input(self, monitor_id: str, input_text: str) -> str:
        """向进程发送输入"""
        with self._manager_lock:
            monitor = self._monitors.get(monitor_id)
            if not monitor:
                return f"错误:进程 '{monitor_id}' 不存在"

            if not monitor.process or monitor.process.poll() is not None:
                return f"错误:进程 {monitor_id} 已结束,无法发送输入"

            try:
                monitor.process.stdin.write(input_text + "\n")
                monitor.process.stdin.flush()
                return f"已向进程 {monitor_id} 发送输入: {input_text}"
            except Exception as e:
                return f"错误:发送输入失败 - {e}"

    def get_matched(self, monitor_id: str) -> str:
        """获取匹配结果"""
        with self._manager_lock:
            monitor = self._monitors.get(monitor_id)
            if not monitor:
                return f"错误:进程 '{monitor_id}' 不存在"

            if not monitor.matched_lines:
                return f"进程 {monitor_id} 尚未匹配到任何内容。"

            lines = [f"进程 {monitor_id} 匹配到 {len(monitor.matched_lines)} 行:"]
            for line in monitor.matched_lines[-20:]:
                lines.append(f"  {line}")
            return "\n".join(lines)
