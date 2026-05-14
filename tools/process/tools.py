import os

from langchain_core.tools import tool


@tool
def process_start(
    command: str,
    name: str = "",
    cwd: str = "",
    config_param: dict = None,
) -> str:
    """
    在后台启动一个新进程并跟踪其状态。

    Args:
        command: 要执行的命令
        name: 人类可读的进程名称（如 "开发服务器"、"数据处理"），用于在进程列表中展示。不填则使用命令前50字符。
        cwd: 工作目录（可选，默认使用当前工作目录）
        config_param: 内部使用参数，由系统自动注入，请勿传递。

    Returns:
        str: 进程启动结果，包含进程 ID、PID 和状态
    """
    if not command.strip():
        return "错误：命令不能为空"

    if not cwd and config_param:
        cwd = config_param.get("cwd", "")
    if not cwd:
        cwd = os.getcwd()

    from .manager import ProcessManager
    manager = ProcessManager.get_instance()
    return manager.start_process(command.strip(), name, cwd)


@tool
def process_stop(process_id: str, force: bool = False) -> str:
    """
    终止指定进程并移除其记录。

    Args:
        process_id: 进程 ID
        force: 是否强制终止（直接 SIGKILL），默认 False（先尝试 SIGTERM）

    Returns:
        str: 操作结果消息
    """
    from .manager import ProcessManager
    manager = ProcessManager.get_instance()
    return manager.stop_process(process_id, force)


@tool
def process_output(process_id: str, lines: int = 50) -> str:
    """
    获取进程的最新输出（stdout 和 stderr 合并，按时间排序）。

    Args:
        process_id: 进程 ID
        lines: 返回最后 N 行，默认 50

    Returns:
        str: 进程输出内容
    """
    from .manager import ProcessManager
    manager = ProcessManager.get_instance()
    return manager.get_output(process_id, lines)


@tool
def process_input(process_id: str, input_text: str) -> str:
    """
    向运行中的进程发送标准输入。

    Args:
        process_id: 进程 ID
        input_text: 要发送的文本（自动添加换行符）

    Returns:
        str: 操作结果消息
    """
    from .manager import ProcessManager
    manager = ProcessManager.get_instance()
    return manager.send_input(process_id, input_text)


@tool
def process_list() -> str:
    """
    列出所有管理的进程及其状态。

    Returns:
        str: 格式化的进程列表，包含 ID、命令、状态、运行时长等信息
    """
    from .manager import ProcessManager
    manager = ProcessManager.get_instance()
    return manager.list_processes()


@tool
def process_cleanup() -> str:
    """
    清理已自然退出的进程记录，释放资源。

    Returns:
        str: 清理结果消息
    """
    from .manager import ProcessManager
    manager = ProcessManager.get_instance()
    return manager.cleanup_finished()


def get_tools() -> list:
    """获取进程管理工具列表"""
    return [
        process_start,
        process_stop,
        process_output,
        process_input,
        process_list,
        process_cleanup,
    ]
