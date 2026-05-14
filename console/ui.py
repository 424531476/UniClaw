import sys
from enum import Enum
import threading
import time

_PT_STYLE_MAP = {
    "\033[30m": "fg:black",
    "\033[31m": "fg:red",
    "\033[32m": "fg:green",
    "\033[33m": "fg:yellow",
    "\033[34m": "fg:blue",
    "\033[35m": "fg:magenta",
    "\033[36m": "fg:cyan",
    "\033[37m": "fg:white",
    "\033[91m": "fg:brightred",
    "\033[92m": "fg:brightgreen",
    "\033[93m": "fg:brightyellow",
    "\033[94m": "fg:brightblue",
    "\033[95m": "fg:brightmagenta",
    "\033[96m": "fg:brightcyan",
    "\033[97m": "fg:brightwhite",
    "\033[1m": "bold",
    "\033[2m": "dim",
    "\033[3m": "italic",
    "\033[4m": "underline",
    "\033[7m": "reverse",
    "\033[90m": "fg:gray",
}


class C(str, Enum):
    """终端颜色代码枚举

    定义了常用的 ANSI 转义序列颜色代码，用于在终端中输出彩色文本。
    每个枚举值对应一个 ANSI 颜色代码字符串。
    """

    # 基础颜色
    BLACK = "\033[30m"  # 黑色 (ANSI 30)
    RED = "\033[31m"  # 红色 (ANSI 31)
    GREEN = "\033[32m"  # 绿色 (ANSI 32)
    YELLOW = "\033[33m"  # 黄色 (ANSI 33)
    BLUE = "\033[34m"  # 蓝色 (ANSI 34)
    MAGENTA = "\033[35m"  # 洋红色 (ANSI 35)
    CYAN = "\033[36m"  # 青色 (ANSI 36)
    WHITE = "\033[37m"  # 白色 (ANSI 37)

    # 亮色
    LIGHT_RED = "\033[91m"  # 亮红色 (ANSI 91)
    LIGHT_GREEN = "\033[92m"  # 亮绿色 (ANSI 92)
    LIGHT_YELLOW = "\033[93m"  # 亮黄色 (ANSI 93)
    LIGHT_BLUE = "\033[94m"  # 亮蓝色 (ANSI 94)
    LIGHT_MAGENTA = "\033[95m"  # 亮洋红色 (ANSI 95)
    LIGHT_CYAN = "\033[96m"  # 亮青色 (ANSI 96)
    LIGHT_WHITE = "\033[97m"  # 亮白色 (ANSI 97)

    # 样式修饰
    BOLD = "\033[1m"  # 加粗样式 (ANSI 1)
    DIM = "\033[2m"  # 暗淡样式 (ANSI 2)
    ITALIC = "\033[3m"  # 斜体样式 (ANSI 3)
    UNDERLINE = "\033[4m"  # 下划线样式 (ANSI 4)
    REVERSE = "\033[7m"  # 反显样式 (ANSI 7)
    GRAY = "\033[90m"  # 灰色 (ANSI 90)

    # 重置
    RESET = "\033[0m"  # 重置所有样式 (ANSI 0)

    @property
    def pt_style(self) -> str:
        """对应的 prompt_toolkit 样式字符串"""
        return _PT_STYLE_MAP.get(self.value, "")


def clr(text: str, *keys: C) -> str:
    """为文本添加 ANSI 颜色（终端模式）。"""
    return "".join(k.value for k in keys) + str(text) + C.RESET.value


def tui_clr(text: str, *keys: C) -> list[tuple[str, str]]:
    """为文本添加 prompt_toolkit 片段（TUI 模式）。"""
    style = " ".join(k.pt_style for k in keys if k.pt_style)
    return [(style, str(text))]


def _get_tui():
    from console.run import TUIApp

    return TUIApp.get_instance()


def info(msg: str):
    tui = _get_tui()
    if tui:
        tui.print(tui_clr(msg, C.CYAN))
    else:
        print(clr(msg, C.CYAN))


def ok(msg: str):
    tui = _get_tui()
    if tui:
        tui.print(tui_clr(msg, C.GREEN))
    else:
        print(clr(msg, C.GREEN))


def warn(msg: str):
    tui = _get_tui()
    if tui:
        tui.print(tui_clr(f"Warning: {msg}", C.YELLOW))
    else:
        print(clr(f"Warning: {msg}", C.YELLOW))


def err(msg: str):
    tui = _get_tui()
    if tui:
        tui.print(tui_clr(f"Error: {msg}", C.RED))
    else:
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
    current_text = "waiting..."

    @classmethod
    def start(cls, text: str = "waiting..."):
        cls.current_text = text
        if cls.thread and cls.thread.is_alive():
            return
        cls.stop_flag.clear()
        cls.thread = threading.Thread(target=cls.run, daemon=True, name="Spinner")
        cls.thread.start()

    @classmethod
    def stop(cls):
        if cls.thread and cls.thread.is_alive():
            cls.stop_flag.set()
            cls.thread.join(timeout=1)
            print("\r", " " * 70, end="\r")
        cls.thread = None

    @classmethod
    def run(cls):
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        while not cls.stop_flag.is_set():
            for char in chars:
                print(clr(f"\r{char} {cls.current_text}", C.BLUE), end="", flush=True)
                cls.stop_flag.wait(0.1)
                if cls.stop_flag.is_set():
                    break


class TUISpinner:
    """TUI 模式下的旋转器，通过回调更新显示"""

    _active: bool = False
    _frame: int = 0
    _text: str = "waiting..."
    _chars: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    _invalidate_callback = None

    @classmethod
    def set_invalidate_callback(cls, callback):
        """设置 invalidate 回调，用于通知 TUI 刷新显示"""
        cls._invalidate_callback = callback

    @classmethod
    def start(cls, text: str = "waiting..."):
        cls._active = True
        cls._text = text
        cls._frame = 0

    @classmethod
    def stop(cls):
        cls._active = False

    @classmethod
    def is_active(cls) -> bool:
        return cls._active

    @classmethod
    def get_display(cls) -> str:
        """获取当前旋转器显示文本"""
        if not cls._active:
            return ""
        char = cls._chars[cls._frame % len(cls._chars)]
        return f"  {char} {cls._text}"

    @classmethod
    def update_frame(cls):
        """更新帧并通知 TUI 刷新"""
        if cls._active:
            cls._frame += 1
            if cls._invalidate_callback:
                cls._invalidate_callback()
