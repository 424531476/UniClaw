import base64
import mimetypes
import asyncio
import queue
import shutil
import threading
import time
from pathlib import Path
from agent import MultiAgent
from commands import handle_slash, COMMANDS

_COMMANDS_LIST = list(COMMANDS.keys())
from compaction import estimate_tokens, get_context_limit
from config import Permissions
from console.ui import C, clr, ok, err, info, warn, colorize_diff
from tools.shell import Bash
from agent import (
    AgentTask,
    ThinkingStartEvent,
    ThinkingChunkEvent,
    TextChunkEvent,
    AssistantEvent,
    TooStartlEvent,
    ToolEvent,
    EndEvent,
    PermissionRequestEvent,
)

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu

_PERMISSION_CYCLE = [
    Permissions.AUTO,
    Permissions.MANUAL,
    Permissions.ACCEPT_ALL,
    Permissions.PLAN,
]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"}


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


def _prompt_text(pct: float) -> str:
    cwd = Path.cwd().name
    return f"[{cwd}] {pct:.0f}% "


def ask_permission_interactive(desc: str, config: dict, tool_call: dict = None):
    if tool_call and tool_call.get("name") == "Bash":
        from tools.security import bash_desc
        command = tool_call.get("args", {}).get("command", "")
        if command:
            bash_info = bash_desc(command, config)
            if bash_info:
                desc = f"{desc}\n   {bash_info}"

    print(f"\n{clr('⚠️  需要您的授权:', C.YELLOW)}")
    print(f"{desc}")

    if tool_call and tool_call.get("name") == "Bash":
        from tools.security import extract_bash_prefix
        _cmd = tool_call.get("args", {}).get("command", "")
        _pattern = extract_bash_prefix(_cmd)
        _allow_label = f"始终允许 '{_pattern}'"
    elif tool_call:
        _allow_label = f"始终允许 '{tool_call.get('name', '')}'"
    else:
        _allow_label = "全部接受"

    prompt = f"是否允许? [y/N/a({_allow_label})] "
    try:
        from prompt_toolkit import prompt as pt_prompt
        text = pt_prompt(HTML(f"\n<ansicyan>{prompt} </ansicyan>")).strip().lower()
    except (ImportError, EOFError):
        text = input(f"\n{prompt}").strip().lower()

    if text == "a":
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

    if text in ("y", "yes"):
        return True
    prompt = "拒绝原因（可选，回车跳过）: "
    try:
        reason = pt_prompt(HTML(f"<ansicyan>{prompt} </ansicyan>")).strip()
    except (NameError, EOFError):
        reason = input(f"{prompt}").strip()
    return reason if reason else "用户拒绝执行"


def _check_bg_notifications():
    from task_queue import BackgroundTaskQueue
    bq = BackgroundTaskQueue.get_instance()
    for task_id, status, summary in bq.check_notifications():
        if status == "completed":
            ok(f"\n[后台任务 {task_id[:8]} 已完成]")
            if summary:
                print(clr(f"  结果: {summary[:200]}", C.DIM))
            info(f"  使用 /task view {task_id} 查看完整输出")
        elif status == "failed":
            err(f"\n[后台任务 {task_id[:8]} 失败]")
            if summary:
                print(clr(f"  错误: {summary[:200]}", C.DIM))
        elif status == "lost":
            warn(f"\n[后台任务 {task_id[:8]} 已丢失]")
            if summary:
                print(clr(f"  {summary[:200]}", C.DIM))


# ── 分屏 UI ──────────────────────────────────────────────────

_output_lines: list[str] = []


def _get_output_text():
    """FormattedTextControl 回调，返回最新输出。"""
    rows = shutil.get_terminal_size((80, 24)).lines
    visible_rows = max(5, rows - 6)
    result: list[str] = []
    for item in reversed(_output_lines):
        lines = item.splitlines() or [""]
        for line in reversed(lines):
            result.append(line)
            if len(result) >= visible_rows:
                return "\n".join(reversed(result))
    return "\n".join(reversed(result))


def _build_app(config: dict, on_submit):
    """构建 prompt_toolkit Application: 上方滚动输出 + 下方固定输入框。"""

    output_control = FormattedTextControl(text=_get_output_text)

    output_window = Window(
        content=output_control,
        always_hide_cursor=True,
        wrap_lines=True,
    )

    def _get_prompt():
        pct = config.get("_token_pct", 0)
        return HTML(f"<b>{_prompt_text(pct)}</b>»")

    def _accept_input(buf):
        text = buf.text
        if text.strip():
            on_submit(text)
        buf.reset()
        return True

    input_buffer = Buffer(
        completer=_CommandCompleter(),
        accept_handler=_accept_input,
        complete_while_typing=True,
        multiline=True,
    )

    def _get_input_line_prefix(_line_number, _wrap_count):
        return _get_prompt()

    input_window = Window(
        content=BufferControl(buffer=input_buffer),
        height=3,
        dont_extend_height=False,
        get_line_prefix=_get_input_line_prefix,
    )

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

    body_content = HSplit([
        output_window,
        Window(height=1, char="─", style="class:separator"),
        input_window,
        Window(height=1, char="─", style="class:separator"),
        status_bar,
    ])

    body = FloatContainer(
        content=body_content,
        floats=[
            Float(
                xcursor=True,
                ycursor=True,
                content=CompletionsMenu(max_height=8, scroll_offset=1),
            )
        ],
    )

    bindings = KeyBindings()

    @bindings.add("s-tab")
    def _toggle_permission(event):
        cfg = config
        cur = cfg.get("permission_mode", Permissions.AUTO)
        if isinstance(cur, str):
            cur = Permissions(cur)
        idx = _PERMISSION_CYCLE.index(cur) if cur in _PERMISSION_CYCLE else 0
        cfg["permission_mode"] = _PERMISSION_CYCLE[(idx + 1) % len(_PERMISSION_CYCLE)]
        event.app.invalidate()

    @bindings.add("escape")
    def _clear_input(event):
        input_buffer.text = ""

    @bindings.add("tab")
    def _complete(event):
        buffer = event.app.current_buffer
        if buffer.complete_state:
            buffer.complete_next()
        else:
            buffer.start_completion(select_first=False)

    return Application(
        layout=Layout(body, focused_element=input_window),
        key_bindings=bindings,
        full_screen=True,
    )


async def drain_events(
    multi_agent: MultiAgent,
    agent_task: AgentTask,
    app: Application,
    config: dict,
):
    """从事件队列读取并更新输出区域，直到 EndEvent(depth=0)。"""
    thinking_stream = False
    text_stream = False
    last_wait_notice = time.monotonic()
    last_invalidate = 0.0

    def _invalidate(force: bool = False):
        nonlocal last_invalidate
        now = time.monotonic()
        if force or now - last_invalidate >= 0.05:
            app.invalidate()
            last_invalidate = now

    while True:
        try:
            queued_task, event = await asyncio.to_thread(
                multi_agent.event_queue.get, True, 1.0
            )
        except queue.Empty:
            if agent_task.future is not None and agent_task.future.done():
                exc = agent_task.future.exception()
                if exc is not None:
                    _output_lines.append(f"\n❌ Agent 线程异常退出: {exc}")
                else:
                    _output_lines.append("\n⚠️ Agent 已结束，但没有收到结束事件。")
                _invalidate(force=True)
                break
            now = time.monotonic()
            if now - last_wait_notice >= 10:
                _output_lines.append("\n⏳ 仍在等待模型响应...")
                _invalidate(force=True)
                last_wait_notice = now
            continue

        if queued_task is not agent_task:
            multi_agent.event_queue.put((queued_task, event))
            await asyncio.sleep(0.05)
            continue

        if isinstance(event, ThinkingStartEvent):
            _output_lines.append("💭 Thinking...")
        elif isinstance(event, ThinkingChunkEvent):
            if not thinking_stream:
                _output_lines.append("💭 [Thinking]")
            thinking_stream = True
            _output_lines.append(event.content)
        elif isinstance(event, TextChunkEvent) and event.content:
            if not text_stream:
                _output_lines.append("")
            text_stream = True
            _output_lines[-1] += event.content
        elif isinstance(event, AssistantEvent):
            thinking_stream = False
            text_stream = False
            if event.tool_calls:
                _output_lines.append(f"   工具调用数量: {len(event.tool_calls)}")
                for i, tc in enumerate(event.tool_calls, 1):
                    name = tc.get("name", "unknown")
                    args = tc.get("args", {})
                    _output_lines.append(f"   工具 {i}: {name}")
                    if args:
                        _output_lines.append(f"      参数: {args}")
            _output_lines.append(f"   模型: {event.model_name}")
            _output_lines.append(f"   Token - 输入: {event.in_tokens}, 输出: {event.out_tokens}")
        elif isinstance(event, TooStartlEvent):
            _output_lines.append(f"🔧 运行工具 '{event.name}({event.args})'...")
        elif isinstance(event, ToolEvent):
            _output_lines.append(f"🔧 [工具] {event.name}")
            if event.name in ("Edit", "Write") and "---" in event.content:
                _output_lines.append(colorize_diff(event.content))
            else:
                _output_lines.append(event.content[:500])
        elif isinstance(event, PermissionRequestEvent):
            _invalidate(force=True)
            event.content = ask_permission_interactive(
                event.description, config, event.tool_call
            )
            event.return_event.set()
            continue
        elif isinstance(event, EndEvent):
            if event.depth == 0:
                break
        else:
            _output_lines.append(f"⚠️ 未知事件: {type(event)}")

        _invalidate(isinstance(event, EndEvent))


async def repl_run_async(config: dict, initial_output: list[str] | None = None):
    task = AgentTask(id="main", name="main", prompt="")
    multi_agent = MultiAgent()
    config["_task"] = task

    submitted_queue: asyncio.Queue[str] = asyncio.Queue()

    def on_submit(text: str):
        submitted_queue.put_nowait(text)
        app.invalidate()

    app = _build_app(config, on_submit)

    if initial_output:
        for line in initial_output:
            _output_lines.append(line)

    app_task = asyncio.create_task(app.run_async())

    try:
        while True:
            result = await submitted_queue.get()
            user_input = (result or "").strip()

            if not user_input:
                continue

            if user_input.startswith("!"):
                shell_cmd = user_input[1:].strip()
                if shell_cmd:
                    _output_lines.append(f"  $ {shell_cmd}")
                    app.invalidate()
                    out = await asyncio.to_thread(Bash.func, shell_cmd, config_param=config)
                    _output_lines.append(out)
                    app.invalidate()
                continue

            slash_result = handle_slash(user_input, task, config)
            if isinstance(slash_result, str):
                user_input = slash_result
            elif slash_result:
                app.invalidate()
                continue

            user_message = _build_user_message(user_input)
            _output_lines.append(f"\n🧑 {user_input}\n")
            app.invalidate()

            try:
                agent_task = multi_agent.start(user_message, task=task, config=config)
                await drain_events(multi_agent, agent_task, app, config)
            except Exception as e:
                _output_lines.append(f"\n❌ 错误: {e}")

            _check_bg_notifications()
            _output_lines.append("")
            config["_token_pct"] = token_usage_rate(task, config)
            app.invalidate()
    finally:
        if not app_task.done():
            app.exit()
        await app_task


def repl_run(config: dict, initial_output: list[str] | None = None):
    
    asyncio.run(repl_run_async(config, initial_output))
    
    # try:
    #     asyncio.get_running_loop()
    # except RuntimeError:
    #     asyncio.run(repl_run_async(config, initial_output))
    #     return

    # error: list[BaseException] = []

    # def _run_in_thread():
    #     try:
    #         asyncio.run(repl_run_async(config, initial_output))
    #     except BaseException as exc:
    #         error.append(exc)

    # thread = threading.Thread(target=_run_in_thread, name="uniclaw-console-repl")
    # thread.start()
    # thread.join()
    # if error:
    #     raise error[0]
