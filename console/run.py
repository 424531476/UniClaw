import sys
import base64
import select
import mimetypes
from pathlib import Path
import time
from agent import MultiAgent
from commands import handle_slash, COMMANDS
from compaction import estimate_tokens, get_context_limit
from config import Permissions
from console.ui import C, Spinner, clr, ok
from utils.truncation import truncate_text_by_lines
from tools.shell import Bash
from agent import (
    AgentState,
    ThinkingStartEvent,
    ThinkingChunkEvent,
    TextChunkEvent,
    AssistantEvent,
    TooStartlEvent,
    ToolEvent,
    EndEvent,
    PermissionRequestEvent,
)

# 命令补全
_COMMANDS_LIST = list(COMMANDS.keys())

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings

    _PERMISSION_CYCLE = [
        Permissions.AUTO,
        Permissions.MANUAL,
        Permissions.ACCEPT_ALL,
        Permissions.PLAN,
    ]

    class _CommandCompleter(Completer):
        def get_completions(self, document, _complete_event):
            text = document.text_before_cursor
            if text.startswith("/"):
                prefix = text[1:]
                for cmd in _COMMANDS_LIST:
                    if cmd.startswith(prefix):
                        yield Completion(f"/{cmd}", start_position=-len(text))

    _bindings = KeyBindings()

    @_bindings.add("s-tab")
    def _toggle_permission(event):
        cfg = event.app.config_ref
        cur = cfg.get("permission_mode", Permissions.AUTO)
        if isinstance(cur, str):
            cur = Permissions(cur)
        idx = _PERMISSION_CYCLE.index(cur) if cur in _PERMISSION_CYCLE else 0
        cfg["permission_mode"] = _PERMISSION_CYCLE[(idx + 1) % len(_PERMISSION_CYCLE)]
        event.app.invalidate()

    _session = PromptSession(completer=_CommandCompleter(), key_bindings=_bindings)

    def _prompt_input(prompt, bottom_toolbar=None, config_ref=None) -> str:
        app = _session.app
        if config_ref is not None:
            app.config_ref = config_ref
        return _session.prompt(prompt, bottom_toolbar=bottom_toolbar)

except ImportError:
    _session = None

    def _prompt_input(prompt, bottom_toolbar=None, config_ref=None) -> str:
        return input(str(prompt))


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"}


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
                        "input_audio": {"data": data, "format": mime.split("/", 1)[len(mime.split("/", 1)) - 1]},
                    }
                )
                has_media = True
            except Exception:
                content_blocks.append({"type": "text", "text": part})
        else:
            content_blocks.append({"type": "text", "text": part})

    if not has_media:
        return text

    # 合并相邻的 text 块
    merged = []
    for block in content_blocks:
        if block["type"] == "text" and merged and merged[len(merged) - 1]["type"] == "text":
            merged[len(merged) - 1]["text"] += " " + block["text"]
        else:
            merged.append(block)

    return merged


def token_usage_rate(state: AgentState, config: dict) -> float:
    """
    计算当前对话上下文中已使用的token占上下文限制的百分比。

    Args:
        state (AgentState): 代理状态对象，包含消息历史记录
        config (dict): 配置字典，包含 model_name 等信息

    Returns:
        float: 已使用token占上下文限制的百分比值（0-100之间）
    """
    model = config.get("model_name")
    used = estimate_tokens(state.messages, model)
    limit = get_context_limit(model)
    pct = used / limit * 100 if limit else 0
    return pct


def colored_input_prompt(pct: float, config_ref: dict):
    if pct >= 70:
        color = "ansired"
    elif pct >= 40:
        color = "ansiyellow"
    else:
        color = "ansiwhite"
    cwd = Path.cwd().name
    prompt = HTML(f"[<b>{cwd}</b>] <{color}>{pct:.2f}%</{color}> »")

    def _toolbar():
        mode = config_ref.get("permission_mode", Permissions.AUTO)
        label = mode.value if isinstance(mode, Permissions) else str(mode)
        return HTML(f" <ansigreen>permission: {label}</ansigreen>  (Shift+Tab 切换)")

    return prompt, _toolbar


def ask_permission_interactive(desc: str, config: dict):
    """交互式请求用户权限确认

    Args:
        desc: 操作描述信息（已格式化的多行字符串）
        config: 配置字典

    Returns:
        True 表示允许，字符串表示拒绝原因
    """
    print(f"\n{clr('⚠️  需要您的授权:', C.YELLOW)}")
    print(f"{desc}")
    prompt = "是否允许? [y/N/a(全部接受)] "
    try:
        from prompt_toolkit import prompt as pt_prompt
        from prompt_toolkit.formatted_text import HTML

        text = pt_prompt(HTML(f"\n<ansicyan>{prompt} </ansicyan>")).strip().lower()
    except ImportError:
        text = input(f"\n{clr(prompt, C.CYAN)}").strip().lower()

    if text == "a":
        config["permission_mode"] = Permissions.ACCEPT_ALL
        ok("✅ 权限模式已为此会话设置为全部接受。")
        return True

    if text in ("y", "yes"):
        return True
    prompt = "拒绝原因（可选，回车跳过）: "
    try:
        reason = pt_prompt(HTML(f"<ansicyan>{prompt} </ansicyan>")).strip()
    except NameError:
        reason = input(clr(prompt, C.CYAN)).strip()
    return reason if reason else "用户拒绝执行"


def _user_input(prompt: str | HTML, bottom_toolbar=None, config_ref=None) -> str:
    """
    智能读取用户输入，支持多行粘贴检测。

    该函数能够检测用户是否粘贴了多行文本，并在检测到粘贴时自动收集所有行。
    针对不同操作系统使用不同的底层机制来实现精确定时和多行检测：
    - Windows: 使用 msvcrt.kbhit() 检测键盘缓冲区
    - Unix: 使用 select() 进行文件描述符监听

    Args:
        prompt (str): 显示给用户的输入提示符

    Returns:
        str: 用户输入的文本。如果检测到多行粘贴，返回合并后的完整文本；
             否则返回单行输入
    """
    first = _prompt_input(prompt, bottom_toolbar=bottom_toolbar, config_ref=config_ref)
    if sys.stdin.isatty():
        lines = [first]
        if sys.platform == "win32":
            # Windows平台的多行粘贴检测逻辑
            # 使用msvcrt.kbhit()检测缓冲的粘贴数据
            import msvcrt

            deadline = 0.12  # 更宽的Windows粘贴延迟窗口
            chunk_to = 0.03
            t0 = time.monotonic()
            while (time.monotonic() - t0) < deadline:
                time.sleep(chunk_to)
                if not msvcrt.kbhit():
                    break
                raw = sys.stdin.readline()
                if not raw:
                    break
                stripped = raw.rstrip("\n").rstrip("\r")
                lines.append(stripped)
                t0 = time.monotonic()  # 数据持续到达时延长
        else:
            # Unix平台的多行粘贴检测逻辑
            # 使用select()进行精确定时
            _PASTE_START = "\x1b[200~"
            _PASTE_END = "\x1b[201~"
            deadline = 0.06
            chunk_to = 0.025
            t0 = time.monotonic()
            while (time.monotonic() - t0) < deadline:
                ready = select.select([sys.stdin], [], [], chunk_to)[0]
                if not ready:
                    break
                raw = sys.stdin.readline()
                if not raw:
                    break
                stripped = raw.rstrip("\n")
                if _PASTE_END in stripped:
                    break
                lines.append(stripped)
                t0 = time.monotonic()

        # 如果检测到多行输入，则合并并返回
        if len(lines) > 1:
            result = "\n".join(lines).strip()
            print(f"  (粘贴了 {len(lines)} 行)")
            return result

    return first


def repl_run(config):
    """
    启动 REPL (Read-Eval-Print Loop) 交互式会话

    持续接收用户输入,运行 Agent 并处理各种事件类型:
    - ThinkingEvent: 显示思考过程
    - TextEvent: 显示文本回复
    - AssistantEvent: 显示助手元数据(工具调用、Token使用等)
    - ToolEvent: 显示工具执行结果

    Returns:
        None: 该函数为无限循环,不会返回
    """

    state = AgentState()
    multi_agent = MultiAgent()
    while True:
        pct = token_usage_rate(state, config)
        prompt, toolbar = colored_input_prompt(pct=pct, config_ref=config)
        user_input = _user_input(
            prompt, bottom_toolbar=toolbar, config_ref=config
        ).strip()
        if user_input == "":
            continue
        if user_input.startswith("!"):
            shell_cmd = user_input[1:].strip()
            if shell_cmd:
                print(clr(f"  $ {shell_cmd}", C.DIM))
                result = Bash.func(shell_cmd)
                print(clr(result, C.WHITE))
            continue
        result = handle_slash(user_input, state=state, config=config)
        if isinstance(result, str):
            user_input = result
        elif result:
            continue

        text_stream = False
        thinking_stream = False
        user_message = _build_user_message(user_input)
        at = multi_agent.start(user_message, state=state, config=config)
        while True:
            agent_task, event = multi_agent.event_queue.get()
            Spinner.stop()
            if isinstance(event, ThinkingStartEvent):
                Spinner.start("Thinking...")
            elif isinstance(event, ThinkingChunkEvent):
                if not thinking_stream:
                    print("💭 [思考中]")
                thinking_stream = True
                print(clr(event.content, C.DIM), end="")
            elif isinstance(event, TextChunkEvent):
                if not text_stream:
                    print("📝 [回复]")
                text_stream = True
                print(clr(event.content, C.WHITE), end="")
            elif isinstance(event, AssistantEvent):
                thinking_stream = False
                text_stream = False
                print("")
                print("🤖 [助手元数据]")
                if event.tool_calls:
                    print(f"   工具调用数量: {len(event.tool_calls)}")
                    for i, tool_call in enumerate(event.tool_calls, 1):
                        tool_name = tool_call.get("name", "unknown")
                        tool_args = tool_call.get("args", {})
                        print(f"   工具 {i}: {tool_name}")
                        if tool_args:
                            print(f"      参数: {tool_args}")
                print(f"   模型:{event.model_name}")
                print(
                    f"   Token使用 - 输入: {event.in_tokens}, 输出: {event.out_tokens}"
                )
                print("")
            elif isinstance(event, TooStartlEvent):
                Spinner.start(f"正在运行工具 '{event.name}({event.args})'...")
            elif isinstance(event, ToolEvent):
                print("🔧 [工具执行]")
                print(f"   工具名称: {event.name}")
                print(f"   调用ID: {event.tool_call_id}")
                print(
                    # f"   执行结果: {clr(truncate_text_by_lines(event.content,max_chars=1000),C.DIM)}"
                    f"   执行结果: {clr(event.content,C.DIM)}"
                )
                print("")
            elif isinstance(event, PermissionRequestEvent):
                event.content = ask_permission_interactive(event.description, config)
                event.return_event.set()
            elif isinstance(event, EndEvent):
                if event.depth == 0:
                    break
            else:
                print(f"⚠️ 未知事件类型: {type(event)}")
                print("")
