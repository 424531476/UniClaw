import re
import shutil
import threading

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Float
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.widgets import Frame
from prompt_toolkit.filters import Condition

from uniclaw.console.output_renderer import OutputRenderer, _get_display_width
from uniclaw.config import AppConfig

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class DialogManager:
    """管理 TUI 对话框:状态、渲染、输入等待、快捷键。"""

    def __init__(self, tui_ref):
        self._tui = tui_ref
        self.active: bool = False
        self.title: str = "输入"
        self.prompt: str = ""
        self.prompt_fragments_list: list[tuple[str, str]] = []
        self.event: threading.Event | None = None
        self.result: str | None = None
        self.scroll_offset: int = 0
        self.chrome_height: int = 6
        self.content_width: int = 20
        self.buffer: Buffer | None = None
        self.input_win: Window | None = None

    # ── 静态/类方法 ──────────────────────────────────────────

    @staticmethod
    def ansi_fragments(text: str) -> list[tuple[str, str]]:
        """将 ANSI 着色文本转为 prompt_toolkit 片段。"""
        from prompt_toolkit.formatted_text import ANSI

        ansi_obj = ANSI(text)
        fragments = list(ansi_obj.__pt_formatted_text__())
        merged: list[tuple[str, str]] = []
        for style, txt in fragments:
            if merged and merged[-1][0] == style:
                merged[-1] = (style, merged[-1][1] + txt)
            else:
                merged.append((style, txt))
        return merged

    @staticmethod
    def diff_fragments(diff_text: str) -> list[tuple[str, str]]:
        """Render a unified diff with prompt_toolkit styles."""
        fragments: list[tuple[str, str]] = []
        for line in diff_text.splitlines(keepends=True):
            line_body = line[:-1] if line.endswith("\n") else line
            newline = "\n" if line.endswith("\n") else ""
            if line_body.startswith(("---", "+++")):
                style = "dim"
            elif line_body.startswith("@@"):
                style = "fg:cyan"
            elif line_body.startswith("-"):
                style = "fg:red"
            elif line_body.startswith("+"):
                style = "fg:green"
            else:
                style = ""
            fragments.append((style, line_body + newline))
        return fragments or [("", "")]

    @classmethod
    def prompt_fragments(cls, text: str) -> list[tuple[str, str]]:
        """Render prompt text, preserving ANSI colors and coloring embedded diffs."""
        if "\x1b[" in text:
            return cls.ansi_fragments(text)
        if "--- " in text and "+++ " in text:
            return cls.diff_fragments(text)
        return [("", text)]

    # ── 对话框宽度与文本渲染 ──────────────────────────────────

    def get_dialog_width(self) -> int:
        console_w = shutil.get_terminal_size((80, 24)).columns
        return max(40, min(self.content_width, console_w * 2 // 3))

    def get_dialog_text(self):
        if not self.active or not self.prompt:
            return [("", "")]
        all_lines = OutputRenderer.wrap_fragment_lines(
            OutputRenderer.split_fragments_lines(self.prompt_fragments_list),
            self.get_dialog_width(),
        )
        rows = shutil.get_terminal_size((80, 24)).lines
        visible_rows = max(5, rows - self.chrome_height)
        total = len(all_lines)
        end = max(0, total - self.scroll_offset)
        start = max(0, end - visible_rows)
        visible = all_lines[start:end]
        fragments: list[tuple[str, str]] = []
        for i, line_fragments in enumerate(visible):
            if i > 0:
                fragments.append(("", "\n"))
            fragments.extend(line_fragments)
        return fragments or [("", "")]

    # ── 对话框 Float 构建 ────────────────────────────────────

    def build_float(self, input_buffer: Buffer, main_input_win: Window):
        """构建对话框 Float 层和 input_win,返回 (Float, dialog_input_win)。"""
        dialog_text_win = Window(
            content=FormattedTextControl(text=self.get_dialog_text),
            wrap_lines=False,
            width=self.get_dialog_width,
        )

        dialog_input_win = Window(
            content=BufferControl(buffer=input_buffer),
            height=2,
            width=self.get_dialog_width,
            get_line_prefix=lambda _a, _b: HTML("<b>输入 > </b>"),
        )
        self.input_win = dialog_input_win

        dialog_float = Float(
            content=ConditionalContainer(
                content=Frame(
                    HSplit(
                        [
                            dialog_text_win,
                            Window(height=1, char="─", style="class:separator"),
                            dialog_input_win,
                        ]
                    ),
                    title=lambda: self.title,
                ),
                filter=Condition(lambda: self.active),
            ),
            top=0,
            bottom=0,
        )

        return dialog_float, dialog_input_win

    # ── 对话框输入 ────────────────────────────────────────────

    def tui_input(self, prompt: str, title: str, config: AppConfig, buffer: Buffer, main_input_win: Window) -> str:
        """显示多行提示并等待用户输入。阻塞当前线程,不阻塞 TUI 事件循环。"""
        tui = self._tui
        if not tui.app:
            return ""
        plain_prompt = _ANSI_RE.sub("", prompt)
        max_line = (
            max(plain_prompt.splitlines(), key=_get_display_width)
            if plain_prompt
            else ""
        )
        dialog_event = threading.Event()

        def _open_dialog():
            self.scroll_offset = 0
            self.prompt = prompt
            self.title = title
            self.prompt_fragments_list = self.prompt_fragments(prompt)
            self.content_width = _get_display_width(max_line) + 4
            self.event = dialog_event
            self.result = None
            if self.buffer is not None:
                self.buffer.reset()
            self.active = True
            tui._focus_window(self.input_win)

        tui._run_on_ui_thread(_open_dialog, wait=True)
        timeout = config.permission_timeout

        # 倒计时线程
        countdown_done = threading.Event()
        countdown_paused = threading.Event()
        countdown_stopped = threading.Event()

        def _on_dialog_text_changed(_):
            if not countdown_stopped.is_set():
                countdown_paused.set()

        if self.buffer:
            self.buffer.on_text_changed += _on_dialog_text_changed

        def _countdown():
            remaining = timeout
            while remaining > 0 and not countdown_done.is_set():
                if countdown_paused.is_set():
                    self.title = title
                    tui.app.invalidate()
                    countdown_done.wait()
                    return
                minutes, seconds = divmod(remaining, 60)
                self.title = f"{title} ({minutes:02d}:{seconds:02d})"
                tui.app.invalidate()
                countdown_done.wait(1)
                remaining -= 1
            if not countdown_done.is_set():
                self.title = title
                tui.app.invalidate()

        if timeout > 0:
            countdown_thread = threading.Thread(target=_countdown, daemon=True)
            countdown_thread.start()

        answered = dialog_event.wait(timeout if timeout > 0 else None)
        countdown_stopped.set()
        countdown_done.set()
        if self.buffer:
            self.buffer.on_text_changed -= _on_dialog_text_changed
        if not answered:
            self.result = "已经超时,用户这会可能不在"

        result = self.result or ""
        self.active = False
        self.event = None

        def _close_dialog():
            self.active = False
            self.prompt = ""
            self.prompt_fragments_list = []
            self.event = None
            if self.buffer is not None:
                self.buffer.reset()
            tui._focus_window(main_input_win)

        tui._run_on_ui_thread(_close_dialog, wait=True)
        return result

    # ── 快捷键 ────────────────────────────────────────────────

    def bind_keys(self, bindings: KeyBindings, input_buffer: Buffer):
        """注册对话框相关的快捷键到 bindings。"""
        _is_dialog = Condition(lambda: self.active)

        @bindings.add("up", filter=Condition(lambda: not input_buffer.complete_state) & _is_dialog, eager=True)
        def _dialog_scroll_up(event):
            all_lines = OutputRenderer.wrap_fragment_lines(
                OutputRenderer.split_fragments_lines(self.prompt_fragments_list),
                self.get_dialog_width(),
            )
            rows = shutil.get_terminal_size((80, 24)).lines
            visible_rows = max(5, rows - self.chrome_height)
            max_offset = max(0, len(all_lines) - visible_rows)
            self.scroll_offset = min(self.scroll_offset + 1, max_offset)
            event.app.invalidate()

        @bindings.add("down", filter=Condition(lambda: not input_buffer.complete_state) & _is_dialog, eager=True)
        def _dialog_scroll_down(event):
            self.scroll_offset = max(0, self.scroll_offset - 1)
            event.app.invalidate()
