from enum import Enum


class ProcessStatus(str, Enum):
    """子进程状态枚举"""
    PENDING = "pending"       # 已创建，尚未启动
    RUNNING = "running"       # 正在运行
    STOPPING = "stopping"     # 正在停止
    STOPPED = "stopped"       # 已正常停止（进程自然退出，exit code 0）
    FAILED = "failed"         # 异常退出（非零 exit code）或被强制终止
