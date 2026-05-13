import sys
from enum import Enum
import threading
import time


_PT_STYLE_MAP = {
    "\033[36m": "fg:cyan",
    "\033[32m": "fg:green",
    "\033[33m": "fg:yellow",
    "\033[31m": "fg:red",
    "\033[34m": "fg:blue",
    "\033[35m": "fg:magenta",
    "\033[37m": "fg:white",
    "\033[1m": "bold",
    "\033[2m": "dim",
    "\033[90m": "fg:gray",
}


class C(str, Enum):
    """终端颜色代码枚举"""

    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    WHITE = "\033[37m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GRAY = "\033[90m"
    RESET = "\033[0m"

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
        cls.thread = threading.Thread(
            target=cls.run, daemon=True, name="Spinner"
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
