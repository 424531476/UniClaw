import sys
from enum import Enum
import threading
import time


class C(str, Enum):
    """终端颜色代码枚举"""

    CYAN = "\033[36m"  # 青色
    GREEN = "\033[32m"  # 绿色
    YELLOW = "\033[33m"  # 黄色
    RED = "\033[31m"  # 红色
    BLUE = "\033[34m"  # 蓝色
    MAGENTA = "\033[35m"  # 品红色
    WHITE = "\033[37m"  # 白色
    BOLD = "\033[1m"  # 加粗
    DIM = "\033[2m"  # 暗淡
    RESET = "\033[0m"  # 重置


def clr(text: str, *keys: C) -> str:
    """为文本添加颜色装饰

    Args:
        text: 要着色的文本内容
        *keys: 一个或多个颜色枚举值

    Returns:
        带有ANSI颜色代码的文本字符串
    """
    return "".join(k.value for k in keys) + str(text) + C.RESET.value


def info(msg: str):
    print(clr(msg, C.CYAN))


def ok(msg: str):
    print(clr(msg, C.GREEN))


def warn(msg: str):
    print(clr(f"Warning: {msg}", C.YELLOW))


def err(msg: str):
    print(clr(f"Error: {msg}", C.RED), file=sys.stderr)


def colorize_diff(diff_text: str) -> str:
    """为 unified diff 文本着色"""
    lines = diff_text.split("\n")
    result = []
    for line in lines:
        if line.startswith("---") or line.startswith("+++"):
            result.append(clr(line, C.DIM))
        elif line.startswith("@@"):
            result.append(clr(line, C.CYAN))
        elif line.startswith("-"):
            result.append(clr(line, C.RED))
        elif line.startswith("+"):
            result.append(clr(line, C.GREEN))
        else:
            result.append(line)
    return "\n".join(result)


class Spinner:
    thread = None
    stop_flag = threading.Event()

    @classmethod
    def start(cls, text: str = "waiting..."):
        if cls.thread and cls.thread.is_alive():
            return
        cls.stop_flag.clear()
        cls.thread = threading.Thread(
            target=cls.run, args=(text,), daemon=True, name="Spinner"
        )
        cls.thread.start()

    @classmethod
    def stop(cls):
        if cls.thread and cls.thread.is_alive():
            cls.stop_flag.set()
            cls.thread.join(timeout=1)
            print("\r", " " * 70, end="\r")
        cls.thread = None

    @classmethod
    def run(cls, text):
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        while not cls.stop_flag.is_set():
            for char in chars:
                print(clr(f"\r{char} {text}", C.BLUE), end="", flush=True)
                cls.stop_flag.wait(0.1)
                if cls.stop_flag.is_set():
                    break
