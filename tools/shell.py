import fnmatch
import os
import subprocess
import sys
from pathlib import Path
from langchain_core.tools import tool

# 标准错误输出标记前缀，用于标识错误信息
STDERR_MARKER = "[stderr]\n"


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
def Bash(command: str, timeout: int = 30, config_param: dict = None) -> str:
    """
    执行 shell 命令并返回输出结果。

    该函数通过 subprocess 执行指定的 shell 命令。
    在 Windows 上使用 cmd.exe，在 Unix/Linux/macOS 上使用 /bin/sh。
    如果命令执行超时，会自动终止进程及其子进程树。
    如果命令执行超时，会自动终止进程及其子进程树。

    Args:
        command (str): 要执行的 shell 命令字符串。
        timeout (int): 命令执行的超时时间（秒），默认为 30 秒。
        config_param (dict): 内部使用参数，由系统自动注入，请勿传递。

    Returns:
        str: 命令的标准输出内容。如果存在标准错误输出，会追加在标准输出之后。
             如果超时，返回超时错误信息。如果发生异常，返回[stderr]开头的异常信息。
             如果没有输出内容，返回 "(没有输出)"。
    """
    # 配置 subprocess 的执行参数 - 使用二进制模式
    kwargs = dict(
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=config_param["cwd"] if config_param["cwd"] else os.getcwd(),
    )
    # 在非 Windows 平台上启用新会话，便于进程组管理
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(command.strip(), **kwargs)
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
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


tools = [Bash]

_grep_err = _check_grep()
if _grep_err:
    print(f"[shell] Grep 不可用: {_grep_err}，Grep 工具已禁用。")
else:
    tools.append(Grep)

_es_err = _check_es()
if _es_err:
    print(f"[shell] Everything 不可用: {_es_err}，search_files_with_everything 工具已禁用。")
else:
    tools.append(search_files_with_everything)
