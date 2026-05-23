"""微信消息处理模块，将 iLink Bot 消息桥接到 UniClaw Agent。"""

import base64
import io
import mimetypes
import re
from contextlib import redirect_stdout

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

from agent import (
    AgentTask,
    AgentStatus,
    MultiAgent,
    TextChunkEvent,
    AssistantEvent,
    ToolEvent,
    EndEvent,
    PermissionRequestEvent,
    ThinkingStartEvent,
    ThinkingChunkEvent,
    ToolStartEvent,
    UserEvent,
)
from commands import handle_slash
from config import Permissions
from tools.shell import Bash
from ilink_bot import IlinkBotClient, IncomingMessage
from ilink_bot.media import download_media, detect_ext
from context import build_system_prompt
from console.ui import C, Spinner, clr, info, ok, warn, err

# 每个用户独立的 Agent 任务
_user_tasks: dict[str, AgentTask] = {}


def _get_user_task(user_id: str) -> AgentTask:
    if user_id not in _user_tasks:
        _user_tasks[user_id] = AgentTask(id=f"wechat-{user_id}", name=f"wechat-{user_id}", prompt="")
    return _user_tasks[user_id]


def _build_user_message(msg: IncomingMessage, bot: IlinkBotClient) -> str | list:
    """构造用户消息，包含文本和图片的多模态内容。"""
    text = msg.text.strip()
    if not msg.images:
        return text or "(图片)"

    content_blocks: list[dict] = []
    for img in msg.images:
        try:
            data = download_media(img, bot=bot)
            ext = detect_ext(data, "image")
            mime = mimetypes.types_map.get(ext, "image/jpeg")
            b64 = base64.b64encode(data).decode()
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )
        except Exception as e:
            warn(f"图片下载失败: {e}")

    if text:
        content_blocks.append({"type": "text", "text": text})
    elif not content_blocks:
        return "(图片下载失败)"

    return content_blocks


def _format_tool_call(name: str, args: dict) -> str:
    """格式化工具调用为简洁的 'name arg' 形式。"""
    if not args:
        return name
    first_val = next(iter(args.values()), None)
    if first_val is None:
        return name
    s = str(first_val)
    if len(s) > 40:
        s = s[:37] + "..."
    return f"{name} {s}"


def _collect_response(
    multi_agent: MultiAgent,
    client: IlinkBotClient | None = None,
    msg: IncomingMessage | None = None,
) -> str:
    """从事件队列中收集 Agent 的文本回复。

    Args:
        multi_agent: MultiAgent 实例
        client: iLink Bot 客户端，用于实时发送工具调用通知
        msg: 原始消息，用于回复目标用户
    """
    parts: list[str] = []
    current_name = ""
    current_args: dict = {}
    thinking_stream = False
    text_stream = False
    while True:
        _agent_task, event = multi_agent.event_queue.get()
        Spinner.stop()
        if isinstance(event, ThinkingStartEvent):
            Spinner.start("Thinking...")
        elif isinstance(event, ThinkingChunkEvent):
            if not thinking_stream:
                print(clr("  [思考中]", C.DIM))
            thinking_stream = True
            print(clr(event.content, C.DIM), end="")
        elif isinstance(event, TextChunkEvent):
            if not text_stream:
                print(clr("  [回复]", C.WHITE))
            text_stream = True
            parts.append(event.content)
            print(clr(event.content, C.WHITE), end="")
        elif isinstance(event, AssistantEvent):
            thinking_stream = False
            text_stream = False
            print()
            if event.tool_calls:
                print(clr(f"  工具调用 x{len(event.tool_calls)}", C.CYAN))
                for tc in event.tool_calls:
                    print(
                        clr(
                            f"    - {tc.get('name', '?')}({tc.get('args', {})})", C.CYAN
                        )
                    )
            print(
                clr(
                    f"  模型:{event.model_name}  输入:{event.in_tokens} 输出:{event.out_tokens}",
                    C.DIM,
                )
            )
        elif isinstance(event, ToolStartEvent):
            current_name = event.name
            current_args = event.args
            label = _format_tool_call(event.name, event.args)
            Spinner.start(f"工具 '{label}' 执行中...")
            if client and msg:
                try:
                    client.reply_text(msg, f"🔧 {label}")
                except Exception:
                    pass
        elif isinstance(event, ToolEvent):
            print(
                clr(
                    f"  [工具] {_format_tool_call(current_name, current_args)}", C.GREEN
                )
            )
            print(clr(f"    {event.content}", C.DIM))
        elif isinstance(event, UserEvent):
            # 显示用户输入消息（微信模式下通常不需要显示，但保留用于调试）
            pass
        elif isinstance(event, PermissionRequestEvent):
            event.content = True
            event.return_event.set()
        elif isinstance(event, EndEvent):
            if event.depth == 0:
                break
    print()
    return "".join(parts)


def make_handler(config: dict):
    """创建消息处理函数，注册到 BotManager。

    Args:
        config: UniClaw 配置字典

    Returns:
        ManagerHandler 签名的处理函数 (bot, msg)
    """

    # 微信模式强制使用 ACCEPT_ALL 权限，无需交互确认
    # 拷贝配置时排除带 "_" 前缀的内部键
    config = {k: v for k, v in config.items() if not k.startswith("_")}
    config["permission_mode"] = Permissions.ACCEPT_ALL
    config["interactive"] = False

    multi_agent = MultiAgent()

    def handler(bot: IlinkBotClient, msg: IncomingMessage):
        user_id = msg.user_id
        text = msg.text.strip()
        if not text and not msg.images:
            return

        info(f"[微信] 收到消息 [{user_id}]: {text or '(图片)'}")

        # /命令处理
        if text.startswith("/"):
            task = _get_user_task(user_id)
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = handle_slash(text, task, config)
            output = _ANSI_RE.sub("", buf.getvalue()).strip()
            if isinstance(result, str):
                bot.reply_text(msg, result)
            elif output:
                bot.reply_text(msg, output.replace("\n", "\n\n"))
            elif result:
                bot.reply_text(msg, "命令已执行。")
            else:
                bot.reply_text(msg, "命令没找到")
            return

        # !命令处理 - 直接执行 shell 命令
        if text.startswith("!"):
            shell_cmd = text[1:].strip()
            if shell_cmd:
                info(f"[微信] 执行命令: {shell_cmd}")
                result = Bash.func(shell_cmd, config=config)
                output = _ANSI_RE.sub("", result).strip()
                bot.reply_text(msg, output.replace("\n", "\n\n") or "(无输出)")
            return

        user_message = _build_user_message(msg, bot)
        task = _get_user_task(user_id)

        # 检查该用户是否有正在运行的 agent 任务
        task_name = f"wechat-{user_id}"
        for t in multi_agent.id2AgentTask.values():
            if t.name == task_name and t.status == AgentStatus.RUNNING:
                task.user_queue.put_nowait(
                    user_message if isinstance(user_message, str) else str(user_message)
                )
                info(f"[微信] 用户 {user_id} 的 agent 正在运行，消息已排队")
                bot.reply_text(msg, "⏳ 已排队，将在当前任务处理间隙自动补充。")
                return

        try:
            bot.send_typing(user_id, context_token=msg.context_token)
        except Exception:
            pass

        try:
            system_prompt = build_system_prompt(config)

            multi_agent.start(
                user_message,
                task,
                system_prompt=system_prompt,
                config=config,
            )
            reply = _collect_response(multi_agent, client=bot, msg=msg)

            if not reply:
                reply = "(Agent 未产生回复)"

            # 微信需要 \n+空格 才能正确换行
            bot.reply_text(msg, reply.replace("\n", "\n "))
            ok(f"[微信] 已回复 [{user_id}]: {reply[:50]}...")

        except Exception as e:
            err(f"[微信] 处理消息失败: {e}")
            try:
                bot.reply_text(msg, f"处理出错: {e}")
            except Exception:
                pass
        finally:
            try:
                bot.stop_typing(user_id, context_token=msg.context_token)
            except Exception:
                pass

    return handler
