import base64
import contextlib
import io
import mimetypes
import re
import asyncio
import queue
import shutil
import threading
import time
from pathlib import Path

from agent import MultiAgent
from commands import handle_slash, COMMANDS
from tools.fs import Edit, Write
from utils.logger import get_logger

_COMMANDS_LIST = list(COMMANDS.keys())
from compaction import estimate_tokens, get_context_limit
from config import Permissions
from console.ui import C, ok, err, info, warn, TUISpinner
from tools.shell import Bash
from agent import (
    AgentTask,
    ThinkingStartEvent,
    ThinkingChunkEvent,
    TextChunkEvent,
    AssistantEvent,
    ToolStartEvent,
    ToolEvent,
    EndEvent,
    PermissionRequestEvent,
    UserEvent,
    InterruptedEvent,
)

from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.widgets import Frame
from prompt_toolkit.filters import Condition

logger = get_logger("run")


def _format_args_for_display(args: dict) -> str:
    """格式化参数字典为显示字符串,处理多行和超长情况。

    Args:
        args: 参数字典

    Returns:
        格式化后的参数字符串,单个参数值超过100字符时截断并添加"..."
    """
    if not args:
        return ""

    # 生成参数列表,对每个参数值进行处理
    formatted_args = []
    for k, v in args.items():
        # 将值转换为字符串
        v_str = str(v)

        # 标记是否需要添加省略号
        needs_ellipsis = False

        # 如果值包含换行符(多行),只取第一行并标记需要省略号
        if "\n" in v_str:
            v_str = v_str.split("\n")[0]
            needs_ellipsis = True

        # 检查长度是否超过100字符
        if len(v_str) > 100:
            v_str = v_str[:100]
            needs_ellipsis = True

        # 如果需要,添加省略号
        if needs_ellipsis:
            v_str += "..."

        formatted_args.append(f"{k}={v_str}")

    return ", ".join(formatted_args)


# ── 常量 ──────────────────────────────────────────────────────

_PERMISSION_CYCLE = [
    Permissions.AUTO,
    Permissions.MANUAL,
    Permissions.ACCEPT_ALL,
    Permissions.PLAN,
]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# ── 独立工具 ──────────────────────────────────────────────────


class _CommandCompleter(Completer):
    def get_completions(self, document, _complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            prefix = text[1:]
            for cmd in _COMMANDS_LIST:
                if cmd.startswith(prefix):
                    yield Completion(f"/{cmd}", start_position=-len(text))


def _build_user_message(text: str):
    """检测用户输入中的图片/音频路径，构造多模态内容或纯文本。"""
    parts = text.split()
    content_blocks = []
    has_media = False

    for part in parts:
        p = Path(part)
        if p.exists() and p.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                mime = mimetypes.guess_type(str(p))[0] or "image/png"
                data = base64.b64encode(p.read_bytes()).decode()
                content_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"},
                    }
                )
                has_media = True
            except Exception:
                content_blocks.append({"type": "text", "text": part})
        elif p.exists() and p.suffix.lower() in AUDIO_EXTENSIONS:
            try:
                mime = mimetypes.guess_type(str(p))[0] or "audio/mpeg"
                data = base64.b64encode(p.read_bytes()).decode()
                content_blocks.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": data,
                            "format": mime.split("/", 1)[len(mime.split("/", 1)) - 1],
                        },
                    }
                )
                has_media = True
            except Exception:
                content_blocks.append({"type": "text", "text": part})
        else:
            content_blocks.append({"type": "text", "text": part})

    if not has_media:
        return text

    merged = []
    for block in content_blocks:
        if (
            block["type"] == "text"
            and merged
            and merged[len(merged) - 1]["type"] == "text"
        ):
            merged[len(merged) - 1]["text"] += " " + block["text"]
        else:
            merged.append(block)

    return merged


def token_usage_rate(task: AgentTask, config: dict) -> float:
    model = config.get("model_name")
    used = estimate_tokens(task.messages, model)
    limit = get_context_limit(model)
    pct = used / limit * 100 if limit else 0
    return pct


def ask_permission_interactive(desc: str, config: dict, tool_call: dict = None):
    tui: TUIApp | None = TUIApp.get_instance()
    if not tui:
        return "无 TUI 实例"

    if tool_call and tool_call.get("name") == "Bash":
        from tools.security import bash_desc

        command = tool_call.get("args", {}).get("command", "")
        if command:
            TUISpinner.start("Analyzing...")
            bash_info = bash_desc(command, config)
            TUISpinner.stop()
            if bash_info:
                desc = f"{desc}\n\n{bash_info}"

    if tool_call and tool_call.get("name") == "Bash":
        from tools.security import extract_bash_prefix

        _cmd = tool_call.get("args", {}).get("command", "")
        _pattern = extract_bash_prefix(_cmd)
        _allow_label = f"始终允许 '{_pattern}'"
    elif tool_call:
        _allow_label = f"始终允许 '{tool_call.get('name', '')}'"
    else:
        _allow_label = "全部接受"

    prompt_text = (
        f"⚠️  需要您的授权:\n{desc}\n\ny 同意 | a {_allow_label} | 其他输入为拒绝理由"
    )
    text = tui.tui_input(prompt_text, title="权限确认").strip()

    if text.lower() == "a":
        from tools.security import add_permission_rule, extract_bash_prefix

        tool_name = tool_call.get("name", "") if tool_call else ""
        if tool_name == "Bash":
            command = tool_call.get("args", {}).get("command", "")
            pattern = extract_bash_prefix(command)
            add_permission_rule("bash", pattern)
            ok(f"✅ 已保存规则: 始终允许 Bash '{pattern}'")
        elif tool_name:
            add_permission_rule("tool", tool_name)
            ok(f"✅ 已保存规则: 始终允许工具 '{tool_name}'")
        return True

    if text.lower() == "y":
        return True
    return text if text else "用户拒绝执行"


# ── TUIApp ────────────────────────────────────────────────────


class TUIApp:
    """prompt_toolkit 全屏 TUI 应用封装（单例模式）。"""

    _instance: "TUIApp | None" = None

    def __new__(cls, config: dict | None = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: dict | None = None):
        # 防止重复初始化
        if self._initialized:
            return

        if config is None:
            raise ValueError("首次创建 TUIApp 实例时必须提供 config 参数")

        self.config = config
        self._initialized = True

        # 输出管理
        self.output_lines: list[list[tuple[str, str]]] = []
        self.verbose_indices: set[int] = set()
        self.normal_indices: set[int] = set()

        # 滚动
        self.scroll_offset: int = 0
        self.dialog_scroll_offset: int = 0
        self.dialog_width: int = 80
        self.command_history: list[str] = []
        self.history_index: int | None = None
        self.history_pending_text: str = ""

        # 对话框
        self.dialog_active: bool = False
        self.dialog_title: str = "输入"
        self.dialog_prompt: str = ""
        self.dialog_prompt_fragments: list[tuple[str, str]] = []
        self.dialog_event: threading.Event | None = None
        self.dialog_result: str | None = None

        # ESC中断：跟踪当前运行的agent任务
        self.current_task: AgentTask | None = None

        # prompt_toolkit 引用
        self.app: Application | None = None
        self.dialog_input_win: Window | None = None
        self.main_input_win: Window | None = None

        # 事件循环引用（用于线程安全的焦点切换）
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get_instance(cls) -> "TUIApp | None":
        """获取 TUIApp 单例实例。"""
        return cls._instance

    def _schedule_focus(self, window: Window | None):
        """从非事件循环线程安全地切换焦点。"""
        if not window or not self.app:
            return
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(self.app.layout.focus, window)

    # ── 输出管理 ──────────────────────────────────────────────
    def clear(self):
        """清空输出。"""
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
        """追加一行输出。text 可以是 str 或 prompt_toolkit 片段列表。"""
        idx = len(self.output_lines)
        if verbose:
            self.verbose_indices.add(idx)
        if normal:
            self.normal_indices.add(idx)
        if isinstance(text, str):
            self.output_lines.append([(style, text)])
        else:
            self.output_lines.append(text)
        self.app.invalidate()

    def print_verbose(self, text: str | list[tuple[str, str]], style: str = "fg:gray"):
        """追加仅详细模式显示的行。"""
        self.print(text, style, verbose=True)

    def print_normal(self, text: str | list[tuple[str, str]], style: str = ""):
        """追加仅普通模式显示的行。"""
        self.print(text, style, normal=True)

    def print_styled(self, text: str | list[tuple[str, str]], style: str):
        """追加带样式但两种模式都显示的行。"""
        self.print(text, style)

    @staticmethod
    def ansi_fragments(text: str) -> list[tuple[str, str]]:
        """将 ANSI 着色文本转为 prompt_toolkit 片段。"""
        from prompt_toolkit.formatted_text import ANSI

        # 创建 ANSI 对象来解析 ANSI 转义码
        ansi_obj = ANSI(text)
        # 获取原始片段（每个字符可能被分开）
        fragments = list(ansi_obj.__pt_formatted_text__())
        # 合并相邻的相同样式的片段
        merged: list[tuple[str, str]] = []
        for style, txt in fragments:
            if merged and merged[-1][0] == style:
                # 如果样式相同，合并文本
                merged[-1] = (style, merged[-1][1] + txt)
            else:
                # 否则添加新片段
                merged.append((style, txt))
        return merged

    # ── 对话框输入 ────────────────────────────────────────────

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

    def tui_input(self, prompt: str, title: str = "输入") -> str:
        """显示多行提示并等待用户输入。阻塞当前线程，不阻塞 TUI 事件循环。"""
        self.dialog_scroll_offset = 0
        self.dialog_prompt = prompt
        self.dialog_title = title
        self.dialog_prompt_fragments = self.prompt_fragments(prompt)

        plain_prompt = _ANSI_RE.sub("", prompt)
        max_line = max(plain_prompt.splitlines(), key=len) if plain_prompt else ""
        content_width = len(max_line) + 4
        console_w = shutil.get_terminal_size((80, 24)).columns
        self.dialog_width = min(content_width, console_w)

        self.dialog_event = threading.Event()
        self.dialog_result = None
        self.dialog_active = True

        # 线程安全：通过事件循环调度焦点切换
        self._schedule_focus(self.dialog_input_win)
        self.app.invalidate()
        self.dialog_event.wait()

        result = self.dialog_result or ""
        self.dialog_active = False
        self.dialog_prompt = ""
        self.dialog_prompt_fragments = []
        self.dialog_event = None

        # 线程安全：通过事件循环调度焦点切换
        self._schedule_focus(self.main_input_win)
        self.app.invalidate()
        return result

    # ── 输出渲染 ──────────────────────────────────────────────

    @staticmethod
    def _count_fragments_lines(fragments: list[tuple[str, str]]) -> int:
        """片段列表占据的实际行数（按 \\n 计算）。"""
        return 1 + sum(t.count("\n") for _, t in fragments)

    @staticmethod
    def _split_fragments_lines(
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

    def _get_output_text(self):
        """FormattedTextControl 回调，返回 prompt_toolkit 格式化片段。"""
        verbose = self.config.get("verbose", False)

        styled_lines: list[list[tuple[str, str]]] = []
        for idx, item in enumerate(self.output_lines):
            if idx in self.verbose_indices and not verbose:
                continue
            if idx in self.normal_indices and verbose:
                continue
            styled_lines.append(item)

        spinner_display = TUISpinner.get_display()
        if spinner_display:
            styled_lines.append([("", spinner_display)])

        if not styled_lines:
            return [("", "")]

        rendered_lines: list[list[tuple[str, str]]] = []
        for line in styled_lines:
            rendered_lines.extend(self._split_fragments_lines(line))

        total_lines = len(rendered_lines)
        rows = shutil.get_terminal_size((80, 24)).lines
        # 基础 chrome: input(2) + separator(1) + status(1) = 4
        # todolist 非空时额外: todo_window(items+3) + separator(1)
        from tools.todolist import TodoList

        todo = TodoList.get_instance()
        todo_height = (
            0 if todo.is_empty() else len(todo.items) + 4
        )  # +4 for todo_window and separator
        visible_rows = max(5, rows - 4 - todo_height)
        max_offset = max(0, total_lines - visible_rows)
        self.scroll_offset = min(self.scroll_offset, max_offset)

        end = total_lines - self.scroll_offset
        start = max(0, end - visible_rows)
        visible = rendered_lines[start:end]

        fragments = []
        for i, line_fragments in enumerate(visible):
            if i > 0:
                fragments.append(("", "\n"))
            fragments.extend(line_fragments)
        return fragments or [("", "")]

    def _count_visible_lines(self) -> int:
        """计算当前模式下可见的实际行数（含 spinner、按 \\n 计算）。"""
        verbose = self.config.get("verbose", False)
        count = 0
        for idx in range(len(self.output_lines)):
            if idx in self.verbose_indices and not verbose:
                continue
            if idx in self.normal_indices and verbose:
                continue
            count += self._count_fragments_lines(self.output_lines[idx])
        if TUISpinner.get_display():
            count += 1
        return count

    # ── 构建 Application ──────────────────────────────────────

    def build_app(self, on_submit) -> Application:
        """构建 prompt_toolkit Application: 上方滚动输出 + 下方固定输入框。"""
        config = self.config

        output_control = FormattedTextControl(text=self._get_output_text)

        output_window = Window(
            content=output_control,
            always_hide_cursor=True,
            wrap_lines=True,
        )

        def _get_prompt():
            pct = config.get("_token_pct", 0)
            cwd = Path.cwd().name
            return HTML(f"<b>[{cwd}] {pct:.0f}% </b>»")

        def _accept_input(buf):
            text = buf.text
            buf.reset()
            if text.strip():
                if not self.command_history or self.command_history[-1] != text:
                    self.command_history.append(text)
                self.history_index = None
                self.history_pending_text = ""
                on_submit(text)
            return True

        input_buffer = Buffer(
            completer=_CommandCompleter(),
            accept_handler=_accept_input,
            complete_while_typing=True,
            multiline=False,
        )

        input_window = Window(
            content=BufferControl(buffer=input_buffer),
            height=2,
            dont_extend_height=False,
            get_line_prefix=lambda _n, _w: _get_prompt(),
        )
        self.main_input_win = input_window

        def _get_status_bar():
            mode = config.get("permission_mode", Permissions.AUTO)
            label = mode.value if isinstance(mode, Permissions) else str(mode)
            return HTML(
                f" <ansigreen>permission: {label}</ansigreen>"
                f"  <ansidim>(Shift+Tab 切换)</ansidim>"
            )

        status_bar = Window(
            content=FormattedTextControl(text=_get_status_bar),
            height=1,
            dont_extend_height=True,
            style="class:statusbar",
        )

        # todolist 显示区域
        from tools.todolist import TodoList

        def _get_todo_text():
            todo = TodoList.get_instance()
            if todo.is_empty():
                return [("", "")]
            from console.ui import tui_clr, C

            return tui_clr(todo.get_list(), C.CYAN)

        def _todo_height():
            todo = TodoList.get_instance()
            if todo.is_empty():
                return 0
            return len(todo.items) + 3

        todo_window = Window(
            content=FormattedTextControl(text=_get_todo_text),
            height=_todo_height,
            dont_extend_height=True,
            style="class:todolist",
        )

        _is_todo_empty = Condition(lambda: TodoList.get_instance().is_empty())

        body_content = HSplit(
            [
                output_window,
                todo_window,
                Window(height=1, char="─", style="class:separator"),
                input_window,
                Window(height=1, char="─", style="class:separator"),
                status_bar,
            ]
        )

        # 对话框
        _is_dialog_active = Condition(lambda: self.dialog_active)

        def _get_dialog_text():
            if not self.dialog_active or not self.dialog_prompt:
                return [("", "")]
            all_lines = self._split_fragments_lines(self.dialog_prompt_fragments)
            rows = shutil.get_terminal_size((80, 24)).lines
            # 对话框可用高度：终端行数减去对话框自身的 chrome
            visible_rows = max(5, rows - 6)
            total = len(all_lines)
            end = max(0, total - self.dialog_scroll_offset)
            start = max(0, end - visible_rows)
            visible = all_lines[start:end]
            fragments: list[tuple[str, str]] = []
            for i, line_fragments in enumerate(visible):
                if i > 0:
                    fragments.append(("", "\n"))
                fragments.extend(line_fragments)
            return fragments or [("", "")]

        dialog_text_win = Window(
            content=FormattedTextControl(text=_get_dialog_text),
            wrap_lines=True,
            width=lambda: self.dialog_width,
        )

        def _dialog_accept(buf):
            self.dialog_result = buf.text
            buf.reset()
            if self.dialog_event:
                self.dialog_event.set()
            return True

        dialog_buffer = Buffer(accept_handler=_dialog_accept, multiline=False)

        dialog_input_win = Window(
            content=BufferControl(buffer=dialog_buffer),
            height=2,
            width=lambda: self.dialog_width,
            get_line_prefix=lambda _a, _b: HTML("<b>输入 > </b>"),
        )
        self.dialog_input_win = dialog_input_win

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
                    title=lambda: self.dialog_title,
                ),
                filter=_is_dialog_active,
            ),
            top=0,
            bottom=0,
        )

        body = FloatContainer(
            content=body_content,
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=8, scroll_offset=1),
                ),
                dialog_float,
            ],
        )

        # ── 快捷键 ────────────────────────────────────────────

        bindings = KeyBindings()

        @bindings.add("s-tab")
        def _toggle_permission(event):
            cur = config.get("permission_mode", Permissions.AUTO)
            if isinstance(cur, str):
                cur = Permissions(cur)
            idx = _PERMISSION_CYCLE.index(cur) if cur in _PERMISSION_CYCLE else 0
            config["permission_mode"] = _PERMISSION_CYCLE[
                (idx + 1) % len(_PERMISSION_CYCLE)
            ]
            event.app.invalidate()

        @bindings.add("f2")
        def _toggle_verbose(event):
            config["verbose"] = not config.get("verbose", False)
            self.scroll_offset = 0
            event.app.invalidate()

        @bindings.add("escape")
        def _clear_input(event):
            if self.dialog_active and self.dialog_event is not None:
                dialog_buffer.text = ""
            elif input_buffer.text:
                # 编辑框有内容时，只清空编辑框
                input_buffer.text = ""
            else:
                # 编辑框为空时，执行取消操作（中断agent）
                if self.current_task is not None:
                    self.current_task.cancel_event.set()
            self.history_index = None
            self.history_pending_text = ""

        _no_completion = Condition(lambda: not input_buffer.complete_state)
        _is_dialog = Condition(lambda: self.dialog_active)
        _is_normal = Condition(lambda: not self.dialog_active)

        @bindings.add("c-up", filter=_no_completion & _is_normal, eager=True)
        def _history_previous(event):
            if not self.command_history:
                return
            if self.history_index is None:
                self.history_pending_text = input_buffer.text
                self.history_index = len(self.command_history) - 1
            else:
                self.history_index = max(0, self.history_index - 1)
            input_buffer.text = self.command_history[self.history_index]
            input_buffer.cursor_position = len(input_buffer.text)

        @bindings.add("c-down", filter=_no_completion & _is_normal, eager=True)
        def _history_next(event):
            if self.history_index is None:
                return
            if self.history_index >= len(self.command_history) - 1:
                input_buffer.text = self.history_pending_text
                self.history_index = None
                self.history_pending_text = ""
            else:
                self.history_index += 1
                input_buffer.text = self.command_history[self.history_index]
            input_buffer.cursor_position = len(input_buffer.text)

        @bindings.add("up", filter=_no_completion & _is_normal, eager=True)
        def _scroll_up(event):
            self.scroll_offset += 1
            event.app.invalidate()

        @bindings.add("down", filter=_no_completion & _is_normal, eager=True)
        def _scroll_down(event):
            self.scroll_offset = max(0, self.scroll_offset - 1)
            event.app.invalidate()

        @bindings.add("up", filter=_no_completion & _is_dialog, eager=True)
        def _dialog_scroll_up(event):
            all_lines = self._split_fragments_lines(self.dialog_prompt_fragments)
            rows = shutil.get_terminal_size((80, 24)).lines
            visible_rows = max(5, rows - 6)
            max_offset = max(0, len(all_lines) - visible_rows)
            self.dialog_scroll_offset = min(self.dialog_scroll_offset + 1, max_offset)
            event.app.invalidate()

        @bindings.add("down", filter=_no_completion & _is_dialog, eager=True)
        def _dialog_scroll_down(event):
            self.dialog_scroll_offset = max(0, self.dialog_scroll_offset - 1)
            event.app.invalidate()

        # @bindings.add("tab")
        # def _complete(event):
        #     buffer = event.app.current_buffer
        #     if buffer.complete_state:
        #         buffer.complete_next()
        #     else:
        #         buffer.start_completion(select_first=False)

        app = Application(
            layout=Layout(body, focused_element=input_window),
            key_bindings=bindings,
            full_screen=True,
            mouse_support=False,
            enable_page_navigation_bindings=False,
        )

        TUISpinner.set_invalidate_callback(app.invalidate)

        async def _spinner_task():
            while True:
                await asyncio.sleep(0.1)
                TUISpinner.update_frame()

        app.create_background_task(_spinner_task())
        return app

    # ── 事件处理 ──────────────────────────────────────────────

    async def drain_events(self, multi_agent: MultiAgent, agent_task: AgentTask):
        """从事件队列读取并更新输出区域，直到 EndEvent(depth=0)。"""
        thinking_stream = False
        text_stream = False
        event_queue = agent_task.event_queue or multi_agent.event_queue

        while True:
            try:
                queued_task, event = await asyncio.to_thread(event_queue.get, True, 1.0)
            except queue.Empty:
                if agent_task.future is not None and agent_task.future.done():
                    TUISpinner.stop()
                    exc = agent_task.future.exception()
                    if exc is not None:
                        import traceback

                        error_traceback = traceback.format_exc()
                        logger.error(error_traceback)
                        self.print(f"\n❌ Agent 线程异常退出: {exc}")
                    else:
                        self.print("\n⚠️ Agent 已结束，但没有收到结束事件。")
                    break
                continue

            # if queued_task is not agent_task:
            #     multi_agent.event_queue.put((queued_task, event))
            #     await asyncio.sleep(0.05)
            #     continue

            if isinstance(event, ThinkingStartEvent):
                TUISpinner.start("Thinking...")
            elif isinstance(event, ThinkingChunkEvent):
                if not thinking_stream:
                    self.print_verbose("💭 [Thinking]")
                    self.print_verbose("")
                    thinking_stream = True
                think = self.output_lines[-1]
                think[0] = (
                    think[0][0],
                    think[0][1] + event.content,
                )
                verbose = self.config.get("verbose", False)
                if verbose:
                    TUISpinner.stop()
                else:
                    TUISpinner.start("Thinking...")
                self.app.invalidate()
            elif isinstance(event, TextChunkEvent) and event.content:
                TUISpinner.stop()
                if not text_stream:
                    self.print("")
                thinking_stream = False
                text_stream = True
                self.output_lines[-1].append(("", event.content))
                self.app.invalidate()
            elif isinstance(event, AssistantEvent):
                TUISpinner.stop()
                thinking_stream = False
                text_stream = False
                self.print_verbose(f"   Token: {event.in_tokens}→{event.out_tokens}")
                if event.tool_calls:
                    self.print_verbose(f"   工具调用数量: {len(event.tool_calls)}")
                    for i, tc in enumerate(event.tool_calls, 1):
                        name = tc.get("name", "unknown")
                        args = tc.get("args", {})
                        self.print_verbose(f"   工具 {i}: {name}")
                        if args:
                            self.print_verbose(f"      参数: {args}")
                self.print_verbose(f"   模型: {event.model_name}")
            elif isinstance(event, ToolStartEvent):
                args_display = _format_args_for_display(event.args)
                if args_display:
                    TUISpinner.start(f"🔧 运行工具 '{event.name}({args_display})'...")
                else:
                    TUISpinner.start(f"🔧 运行工具 '{event.name}'...")
            elif isinstance(event, ToolEvent):
                TUISpinner.stop()
                # 构建工具调用显示文本：工具名 + 参数
                args_display = _format_args_for_display(event.args)
                if args_display:
                    self.print(f"🔧 {event.name}({args_display})")
                else:
                    self.print(f"🔧 {event.name}")
                preview = event.content.split("\n", 1)[0]
                if len(preview) > 100 or len(event.content) > len(preview):
                    preview = preview[:100] + "..."
                self.print_normal(preview, "fg:gray")
                if event.name in (Edit.name, Write.name) and "---" in event.content:
                    diff_fragments = TUIApp.diff_fragments(event.content)
                    self.print_verbose(diff_fragments)
                else:
                    self.print_verbose(event.content[:500])
            elif isinstance(event, UserEvent):
                # 显示用户输入消息
                self.print(f"\n👤 {event.content}", style="fg:white")
            elif isinstance(event, PermissionRequestEvent):
                event.content = await asyncio.to_thread(
                    ask_permission_interactive,
                    event.description,
                    self.config,
                    event.tool_call,
                )
                event.return_event.set()
                continue
            elif isinstance(event, InterruptedEvent):
                TUISpinner.stop()
                from console.ui import tui_clr

                self.print(tui_clr(f"\n⏹️  {event.message}", C.YELLOW))
            elif isinstance(event, EndEvent):
                TUISpinner.stop()
                if event.depth == 0:
                    break
            else:
                self.print(f"⚠️ 未知事件: {type(event)}")
        from console.ui import C, tui_clr

        self.print(tui_clr("." * 60, C.GRAY))

    # ── 事件循环 ──────────────────────────────────────────────

    async def _run_async(self, initial_output: list[str] | None = None):
        self._loop = asyncio.get_running_loop()
        task = AgentTask(id="main", name="main", prompt="")
        task.event_queue = queue.Queue()
        multi_agent = MultiAgent()
        self.config["_task"] = task
        self.config["_tui"] = self

        def on_submit(text: str):
            task.user_queue.put_nowait(text)
            self.app.invalidate()

        self.app = self.build_app(on_submit)

        if initial_output:
            for line in initial_output:
                self.print(line)

        app_task = asyncio.create_task(self.app.run_async())

        try:
            while True:
                result = await asyncio.to_thread(task.user_queue.get)
                user_input = (result or "").strip()

                if not user_input:
                    continue

                if user_input.startswith("!"):
                    shell_cmd = user_input[1:].strip()
                    if shell_cmd:
                        self.print(f"  $ {shell_cmd}")
                        out = await asyncio.to_thread(
                            Bash.func, shell_cmd, config_param=self.config
                        )
                        self.print(out)
                    continue
                if user_input.startswith("/"):
                    slash_result = await asyncio.to_thread(
                        handle_slash, user_input, task, self.config
                    )
                    if isinstance(slash_result, str):
                        user_input = slash_result
                    elif slash_result:
                        self.app.invalidate()
                        continue
                    else:
                        continue

                user_message = _build_user_message(user_input)
                task.cancel_event.clear()  # 启动前重置取消信号
                self.current_task = task
                try:
                    agent_task = multi_agent.start(
                        user_message, task=task, config=self.config
                    )
                    await self.drain_events(multi_agent, task)
                except Exception as e:
                    import traceback

                    error_traceback = traceback.format_exc()
                    logger.error(error_traceback)
                    self.print(f"\n❌ 错误: {e}")
                finally:
                    self.current_task = None

                self.print("")
                self.config["_token_pct"] = token_usage_rate(task, self.config)
                self.app.invalidate()
        finally:
            if not app_task.done():
                self.app.exit()
            await app_task

    def run(self, initial_output: list[str] | None = None):
        """同步入口。"""
        asyncio.run(self._run_async(initial_output))


# ── 模块级便捷接口（供 commands/ 导入）──────────────────────


def tui_input(prompt: str, title: str = "输入") -> str:
    """模块级便捷函数，委托给当前 TUIApp 实例。"""
    instance = TUIApp.get_instance()
    if instance:
        return instance.tui_input(prompt, title=title)
    return ""


def repl_run(config: dict, initial_output: list[str] | None = None):
    """启动 REPL（兼容 launcher.py 调用）。"""
    tui = TUIApp(config)
    tui.run(initial_output)
