import sys
from pathlib import Path
import time
from agent import MultiAgent
from commands import handle_slash
from compaction import estimate_tokens, get_context_limit
from config import Permissions, get_config
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


def token_usage_rate(state: AgentState) -> float:
    """
    计算当前对话上下文中已使用的token占上下文限制的百分比。

    Args:
        state (AgentState): 代理状态对象，包含消息历史记录

    Returns:
        float: 已使用token占上下文限制的百分比值（0-100之间）
    """
    used = estimate_tokens(state.messages)
    limit = get_context_limit()
    pct = used / limit * 100 if limit else 0
    return pct


def colored_input_prompt(pct: float) -> str:
    """
    根据token使用率显示带颜色提示的交互式输入提示符。

    该函数根据当前上下文中已使用的token百分比，以不同颜色显示使用率提示：
    - 红色（>=70%）：表示token使用率较高，接近限制
    - 黄色（>=40%）：表示token使用率中等
    - 灰色（<40%）：表示token使用率较低

    Args:
        pct (float): 已使用token占上下文限制的百分比值（0-100之间）

    Returns:
        str: 用户输入的文本内容
    """
    if pct >= 70:
        ctx_hint = clr(f" {pct:.2f}%", C.RED)
    elif pct >= 40:
        ctx_hint = clr(f" {pct:.2f}%", C.YELLOW)
    else:
        ctx_hint = clr(f" {pct:.2f}%", C.DIM)
    prompt = f"[{Path.cwd().name}] {ctx_hint} »"
    return prompt


def ask_permission_interactive(desc: str, config: dict) -> bool:
    """交互式请求用户权限确认

    Args:
        desc: 操作描述信息（已格式化的多行字符串）
        config: 配置字典

    Returns:
        用户是否授权执行该操作
    """
    print(f"\n{clr('⚠️  需要您的授权:', C.YELLOW)}")
    print(f"{desc}")
    text = input(f"\n{clr('是否允许? [y/N/a(全部接受)] ', C.CYAN)}").strip().lower()

    if text == "a":
        config["permission_mode"] = Permissions.ACCEPT_ALL
        ok("✅ 权限模式已为此会话设置为全部接受。")
        return True

    return text in ("y", "yes")


def _user_input(prompt: str) -> str:
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
    first = input(prompt)
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
            deadline = 0.06
            chunk_to = 0.025
            t0 = _time.monotonic()
            while (_time.monotonic() - t0) < deadline:
                ready = _sel.select([sys.stdin], [], [], chunk_to)[0]
                if not ready:
                    break
                raw = sys.stdin.readline()
                if not raw:
                    break
                stripped = raw.rstrip("\n")
                if _PASTE_END in stripped:
                    break
                lines.append(stripped)
                t0 = _time.monotonic()

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
        pct = token_usage_rate(state)
        user_input = _user_input(colored_input_prompt(pct=pct)).strip()
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
        at = multi_agent.start(user_input, state=state, config=config)
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
                break
            else:
                print(f"⚠️ 未知事件类型: {type(event)}")
                print("")
