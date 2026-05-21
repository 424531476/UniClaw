import fnmatch
import os
import subprocess
import sys
import time
from pathlib import Path
from langchain_core.tools import tool
from cachetools import cached, TTLCache

# 标准错误输出标记前缀，用于标识错误信息
STDERR_MARKER = "[stderr]"


def smart_decode(data: bytes) -> str:
    """尝试多种编码方式解码"""
    if not data:
        return ""

    # 首先尝试 UTF-8
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # 在 Windows 上尝试 GBK
    if sys.platform == "win32":
        try:
            return data.decode("gbk")
        except UnicodeDecodeError:
            pass

        # 尝试 GB18030
        try:
            return data.decode("gb18030")
        except UnicodeDecodeError:
            pass

    # 最后使用 replace 模式
    return data.decode("utf-8", errors="replace")


def _find_git_bash() -> str | None:
    """在 Windows 上查找 Git 自带的 bash.exe，返回路径或 None"""
    if sys.platform != "win32":
        return None

    # 常见安装路径
    candidates = [
        os.path.join(
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            "Git",
            "bin",
            "bash.exe",
        ),
        os.path.join(
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            "Git",
            "bin",
            "bash.exe",
        ),
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Programs", "Git", "bin", "bash.exe"
        ),
    ]

    # 从 PATH 中的 git 推断
    git_path = subprocess.run(
        ["where", "git"], capture_output=True, text=True, shell=True
    )
    if git_path.returncode == 0:
        for line in git_path.stdout.strip().splitlines():
            git_exe = line.strip()
            if git_exe:
                git_dir = os.path.dirname(os.path.dirname(git_exe))
                bash_candidate = os.path.join(git_dir, "bin", "bash.exe")
                candidates.insert(0, bash_candidate)

    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


_GIT_BASH_PATH = _find_git_bash()


def _kill_proc_tree(pid: int) -> None:
    """Kill a process and all its children."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        import signal

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


@tool
def Bash(command: str, timeout: int = 30, config: dict = None) -> str:
    """
    执行 shell 命令并返回输出结果。

    该函数通过 subprocess 执行指定的 shell 命令。
    在 Windows 上优先使用 Git bash,未找到时回退到 cmd.exe。
    在 Unix/Linux/macOS 上使用 /bin/sh。
    如果命令执行超时，会自动终止进程及其子进程树。

    注意：某些命令可能触发分页器（如 git log、man)，导致阻塞等待用户交互。建议添加禁用分页参数：
    - git:`git --no-pager <subcommand>`(--no-pager 必须在 git 和子命令之间）
    - man:`MANPAGER=cat man <command>` 或 `man <command> | cat`

    重要提示：如果需要启动长期运行的后台服务（如 Web 服务器、数据库等），请使用 process_start 工具而非本函数，否则总是超时。
    process_start 提供了更好的进程管理功能，包括进程监控、日志捕获和生命周期管理。

    Args:
        command (str): 要执行的 shell 命令字符串。
        timeout (int): 命令执行的超时时间（秒），默认为 30 秒。
                       小于等于 0 时进入异步模式，命令在后台运行，立即返回进程 ID。
        config (dict): 内部使用参数，由系统自动注入，请勿传递。

    Returns:
        str: 同步模式：命令的标准输出内容。如果存在标准错误输出，会追加在标准输出之后。
             如果超时，返回超时错误信息。如果发生异常，返回[stderr]开头的异常信息。
             如果没有输出内容，返回 "(没有输出)"。
             异步模式(timeout<=0)：返回 "[async] 进程已启动,PID: {pid}" 格式的消息。
    """
    # 配置 subprocess 的执行参数 - 使用二进制模式
    cwd = config["cwd"] if isinstance(config,dict) and config["cwd"] else os.getcwd()

    # 构建通用的 subprocess 参数
    kwargs = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
    )
    if timeout <= 0:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    # 根据平台准备命令参数
    if _GIT_BASH_PATH:
        # Windows 下找到 Git bash，使用 bash 执行命令
        cmd_args = [_GIT_BASH_PATH, "-c", command.strip()]
    else:
        # Unix/Linux/macOS 或未找到 Git bash 时的默认行为
        kwargs["shell"] = True
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        cmd_args = command.strip()

    proc = subprocess.Popen(cmd_args, **kwargs)

    # 异步模式：立即返回进程信息
    if timeout <= 0:
        return f"[async] 进程已启动，PID: {proc.pid}"

    cancel_event = config.get("tool_cancel_event") if isinstance(config, dict) else None
    
    # 记录开始时间用于计算执行时长
    start_time = time.monotonic()

    try:
        try:
            # 轮询等待进程完成，每 0.5 秒检查一次取消信号
            deadline = time.monotonic() + timeout
            while True:
                try:
                    proc.wait(timeout=0.5)
                    break  # 进程已结束
                except subprocess.TimeoutExpired:
                    pass
                # 检查超时
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(cmd_args, timeout)
                # 检查取消信号
                if cancel_event is not None and cancel_event.is_set():
                    _kill_proc_tree(proc.pid)
                    try:
                        stdout_bytes, stderr_bytes = proc.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        stdout_bytes = b""
                        stderr_bytes = b""
                        proc.kill()
                        proc.wait()
                    stdout = smart_decode(stdout_bytes)
                    stderr = smart_decode(stderr_bytes)
                    out = stdout
                    if stderr:
                        out += ("\n" if out else "") + f"{STDERR_MARKER}" + stderr
                    elapsed_time = time.monotonic() - start_time
                    cancel_msg = f"{STDERR_MARKER}用户中断（进程已终止，用时 {elapsed_time:.1f} 秒）"
                    return (out.strip() + "\n" + cancel_msg).strip()

            stdout_bytes, stderr_bytes = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            # 超时后终止进程，再读取缓冲区中的输出
            _kill_proc_tree(proc.pid)
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                stdout_bytes = b""
                stderr_bytes = b""
                proc.kill()
                proc.wait()

            stdout = smart_decode(stdout_bytes)
            stderr = smart_decode(stderr_bytes)
            out = stdout
            if stderr:
                out += ("\n" if out else "") + f"{STDERR_MARKER}" + stderr
            timeout_msg = f"{STDERR_MARKER}在 {timeout} 秒后超时（进程已终止）"
            return (out.strip() + "\n" + timeout_msg).strip()

        # 解码输出
        stdout = smart_decode(stdout_bytes)
        stderr = smart_decode(stderr_bytes)

        # 合并标准输出和标准错误输出
        out = stdout
        if stderr:
            out += ("\n" if out else "") + f"{STDERR_MARKER}" + stderr
        return out.strip() or "(没有输出)"
    except Exception as e:
        return f"{STDERR_MARKER}{e}"


# ── Grep ──────────────────────────────────────────────────────────────────


def _has_rg() -> bool:
    try:
        subprocess.run(
            ["rg", "--version"],
            capture_output=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return True
    except Exception:
        return False


def _check_grep() -> str | None:
    """检查 rg 或 grep 是否可用，返回错误信息或 None"""
    if _has_rg():
        return None
    try:
        subprocess.run(["grep", "--version"], capture_output=True, timeout=5)
        return None
    except FileNotFoundError:
        return "未找到 rg (ripgrep) 或 grep 命令，请安装 ripgrep"
    except Exception as e:
        return str(e)


@tool
def Grep(
    pattern: str,
    path: str = None,
    glob: str = None,
    output_mode: str = "files_with_matches",
    case_insensitive: bool = False,
    context: int = 0,
    cwd: str = None,
) -> str:
    """
    在文件中搜索匹配的模式，支持使用 rg (ripgrep) 或 grep 工具。

    Args:
        pattern: 要搜索的正则表达式模式
        path: 搜索的文件或目录路径，如果未指定则使用 cwd 或当前工作目录
        glob: 文件匹配模式，用于过滤要搜索的文件类型（如 "*.py"）
        output_mode: 输出模式，可选值：
            - "files_with_matches": 仅返回匹配的文件列表（默认）
            - "count": 返回每个文件的匹配行数
            - 其他值: 返回带行号的匹配内容
        case_insensitive: 是否忽略大小写进行搜索，默认为 False
        context: 上下文行数，显示匹配行前后指定行数的内容，默认为 0
        cwd: 当前工作目录，当 path 未指定时使用

    Returns:
        str: 搜索结果字符串。如果找到匹配项，返回结果（最多20000字符）；
             如果没有匹配项，返回 "No matches found"；
             如果发生错误，返回 "Error: {错误信息}"
    """
    # 检测系统是否安装了 ripgrep，优先使用性能更好的 rg
    use_rg = _has_rg()
    cmd = ["rg" if use_rg else "grep", "--no-heading"]

    # 根据参数构建命令选项
    if case_insensitive:
        cmd.append("-i")
    if output_mode == "files_with_matches":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("-c")
    else:
        cmd.append("-n")
        if context:
            cmd += ["-C", str(context)]

    # 添加文件过滤模式和搜索模式
    if glob:
        cmd += ["--glob", glob] if use_rg else ["--include", glob]
    cmd.append(pattern)
    cmd.append(path or cwd or str(Path.cwd()))

    # 执行搜索命令并处理结果
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        out = r.stdout.strip()
        return out[:20000] if out else "No matches found"
    except Exception as e:
        return f"Error: {e}"


@tool
def get_current_time():
    """
    获取当前系统时间

    Returns:
        str: 格式化的当前时间字符串，格式为 "YYYY-MM-DD HH:MM:SS"
    """
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _check_es() -> str | None:
    """检查 Everything (es.exe) 是否可用，返回错误信息或 None"""
    try:
        r = subprocess.run(["es", "test_sandbox_check"], capture_output=True, timeout=5)
        stderr = smart_decode(r.stderr).strip()
        if stderr:
            return stderr
    except FileNotFoundError:
        return "未找到 es.exe 命令，请安装 Everything 并确保 es.exe 在 PATH 中"
    except subprocess.TimeoutExpired:
        return "es.exe 响应超时"
    except Exception as e:
        return str(e)
    return None


@tool
def search_files_with_everything(
    query: str,
    max_results: int = 0,
    path_filter: str = None,
) -> str:
    """
    使用 Everything 搜索引擎的文件名搜索工具（es 命令行）

    该函数通过调用 es.exe 命令行工具来执行快速文件名搜索。Everything 是一款高效的 Windows 文件搜索工具，
    能够实时索引文件系统并提供毫秒级的搜索响应。

    Args:
        query (str): 搜索关键词或查询字符串
            - 支持通配符：*（任意字符）、?（单个字符）
            - 支持逻辑运算符：AND、OR、NOT
            - 示例："report"、"*.pdf"、"document AND 2024"

        max_results (int): 最大返回结果数量限制
            - 默认值 0 表示不限制返回数量
            - 设置为正整数可限制返回结果条数，提高响应速度
            - 建议对于大型搜索结果设置合理的限制值（如 50-100）

        path_filter (str): 路径过滤器，用于限定搜索范围到特定目录
            - 可以是绝对路径或相对路径
            - 示例："C:/Users/Documents"、"./src"
            - 使用正斜杠 / 以避免转义问题

    Returns:
        str: 搜索结果字符串
            - 成功时：返回匹配的文件列表，每行一个文件路径
              例如："C:/Users/file1.txt\nC:/Users/file2.txt"
            - 失败时：返回以 "[stderr]" 开头的错误信息字符串
              例如："[stderr]es command not found" 或 "[stderr]Permission denied"
            - 常见错误场景：
              * es 命令未安装或未配置到系统 PATH
              * 指定的路径不存在或无访问权限
              * 搜索查询语法错误

    Note:
        - 使用前需确保系统已安装 Everything 并正确配置 es.exe 命令行工具
        - 如果检测到 es 命令不可用，函数会自动返回 "[stderr]" 开头的错误提示
        - 路径参数建议使用正斜杠格式以避免 Unicode 转义问题
        - 返回值判断：检查字符串是否以 "[stderr]" 开头来判断是否执行成功

    Example:
        >>> # 基本搜索
        >>> result = search_files_with_everything("readme")
        >>> if not result.startswith("[stderr]"):
        ...     print(result)

        >>> # 限制结果数量
        >>> result = search_files_with_everything("*.py", max_results=10)

        >>> # 在指定路径下搜索
        >>> result = search_files_with_everything("config", path_filter="D:/Projects")

        >>> # 组合使用
        >>> result = search_files_with_everything("test_*.py", max_results=20, path_filter="./tests")
    """

    # 构建带参数的完整搜索命令
    search_cmd = "es"

    if path_filter:
        search_cmd += f' -p "{path_filter}"'
    if max_results:
        search_cmd += f" -n {max_results}"
    search_cmd += f' "{query}"'

    result = Bash.func(search_cmd)
    return result


# 工具检测结果缓存（3分钟过期）
_tools_cache = TTLCache(maxsize=1, ttl=60 * 3)


@cached(_tools_cache)
def get_tools() -> list:
    """获取Shell工具列表（带10分钟缓存，避免重复检测依赖）"""
    from console.ui import warn

    tools = [Bash]

    _grep_err = _check_grep()
    if _grep_err:
        warn(f"[shell] Grep 不可用: {_grep_err}，Grep 工具已禁用。")
    else:
        tools.append(Grep)

    _es_err = _check_es()
    if _es_err:
        warn(
            f"[shell] Everything 不可用: {_es_err}，search_files_with_everything 工具已禁用。"
        )
    else:
        tools.append(search_files_with_everything)

    return tools


def get_all_tools() -> list:
    """获取所有Shell工具(无条件返回)"""
    return [Bash, Grep, search_files_with_everything]
