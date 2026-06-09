import shutil
import unicodedata

from uniclaw.config import AppConfig


def _get_display_width(text: str) -> int:
    """计算字符串在终端中的显示宽度。"""
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


class OutputRenderer:
    """管理 TUI 输出区域:行数据、滚动、文本换行与渲染。"""

    def __init__(self, config: AppConfig, tui_ref=None):
        self.output_lines: list[list[tuple[str, str]]] = []
        self.verbose_indices: set[int] = set()
        self.normal_indices: set[int] = set()
        self.scroll_offset: int = 0
        self._sep_height: int = 1
        self._todo_chrome: int = 3
        self._chrome_height: int = 5
        self.config = config
        self._tui = tui_ref

    # ── 输出管理 ──────────────────────────────────────────────

    def clear(self):
        self.output_lines.clear()
        self.verbose_indices.clear()
        self.normal_indices.clear()

    def print(
        self,
        text: str | list[tuple[str, str]],
        style: str = "",
        *,
        verbose: bool = False,
        normal: bool = False,
    ):
        idx = len(self.output_lines)
        if verbose:
            self.verbose_indices.add(idx)
        if normal:
            self.normal_indices.add(idx)
        if isinstance(text, str):
            self.output_lines.append([(style, text)])
        else:
            self.output_lines.append(text)
        if self._tui and self._tui.app:
            self._tui.app.invalidate()

    def print_verbose(self, text: str | list[tuple[str, str]], style: str = "fg:gray"):
        self.print(text, style, verbose=True)

    def print_normal(self, text: str | list[tuple[str, str]], style: str = ""):
        self.print(text, style, normal=True)

    def print_styled(self, text: str | list[tuple[str, str]], style: str):
        self.print(text, style)

    # ── 文本工具(静态/类方法)────────────────────────────────

    @staticmethod
    def count_fragments_lines(fragments: list[tuple[str, str]]) -> int:
        return 1 + sum(t.count("\n") for _, t in fragments)

    @staticmethod
    def split_fragments_lines(
        fragments: list[tuple[str, str]],
    ) -> list[list[tuple[str, str]]]:
        lines: list[list[tuple[str, str]]] = [[]]
        for style, text in fragments:
            parts = text.split("\n")
            for idx, part in enumerate(parts):
                if idx > 0:
                    lines.append([])
                if part:
                    lines[-1].append((style, part))
        return lines

    @staticmethod
    def char_display_width(char: str) -> int:
        return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1

    @classmethod
    def wrap_fragment_line(
        cls, line: list[tuple[str, str]], width: int
    ) -> list[list[tuple[str, str]]]:
        width = max(1, width)
        wrapped: list[list[tuple[str, str]]] = [[]]
        current_width = 0

        for style, text in line:
            buf = ""
            for char in text:
                char_width = cls.char_display_width(char)
                if current_width > 0 and current_width + char_width > width:
                    if buf:
                        wrapped[-1].append((style, buf))
                        buf = ""
                    wrapped.append([])
                    current_width = 0
                buf += char
                current_width += char_width
            if buf:
                wrapped[-1].append((style, buf))

        return wrapped

    @classmethod
    def wrap_fragment_lines(
        cls, lines: list[list[tuple[str, str]]], width: int
    ) -> list[list[tuple[str, str]]]:
        wrapped: list[list[tuple[str, str]]] = []
        for line in lines:
            wrapped.extend(cls.wrap_fragment_line(line, width))
        return wrapped or [[]]

    # ── 输出渲染 ──────────────────────────────────────────────

    def main_output_width(self) -> int:
        columns = shutil.get_terminal_size((80, 24)).columns
        if self._tui and self._tui.session_panel_visible:
            columns -= 35
        return max(10, columns)

    def get_output_text(self):
        """FormattedTextControl 回调,返回 prompt_toolkit 格式化片段。"""
        verbose = self.config.verbose

        styled_lines: list[list[tuple[str, str]]] = []
        for idx, item in enumerate(self.output_lines):
            if idx in self.verbose_indices and not verbose:
                continue
            if idx in self.normal_indices and verbose:
                continue
            styled_lines.append(item)

        spinner_display = self.config.spinner.get_display()
        if not styled_lines and not spinner_display:
            return [("", "")]

        rendered_lines: list[list[tuple[str, str]]] = []
        for line in styled_lines:
            rendered_lines.extend(self.split_fragments_lines(line))
        rendered_lines = self.wrap_fragment_lines(
            rendered_lines, self.main_output_width()
        )
        spinner_lines = (
            self.wrap_fragment_lines(
                self.split_fragments_lines([("", spinner_display)]),
                self.main_output_width(),
            )
            if spinner_display
            else []
        )

        rows = shutil.get_terminal_size((80, 24)).lines
        todo = self.config.current_agent.todolist
        todo_height = (
            0
            if todo is None or todo.is_empty()
            else len(todo.items) + self._todo_chrome + self._sep_height
        )
        visible_rows = max(1, rows - self._chrome_height - todo_height)
        history_rows = max(1, visible_rows - len(spinner_lines))
        max_offset = max(0, len(rendered_lines) - history_rows)
        self.scroll_offset = min(self.scroll_offset, max_offset)

        end = len(rendered_lines) - self.scroll_offset
        start = max(0, end - history_rows)
        visible = rendered_lines[start:end]
        visible.extend(spinner_lines)

        fragments = []
        for i, line_fragments in enumerate(visible):
            if i > 0:
                fragments.append(("", "\n"))
            fragments.extend(line_fragments)
        return fragments or [("", "")]

    def count_visible_lines(self) -> int:
        """计算当前模式下可见的实际行数。"""
        verbose = self.config.verbose
        count = 0
        width = self.main_output_width()
        for idx in range(len(self.output_lines)):
            if idx in self.verbose_indices and not verbose:
                continue
            if idx in self.normal_indices and verbose:
                continue
            logical_lines = self.split_fragments_lines(self.output_lines[idx])
            count += len(self.wrap_fragment_lines(logical_lines, width))
        return count
