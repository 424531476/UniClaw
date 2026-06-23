"""微信消息处理模块,将 iLink Bot 消息桥接到 UniClaw Agent。"""

import asyncio
import base64
import io
import mimetypes
import queue
import re
from contextlib import redirect_stdout
from pathlib import Path

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

from uniclaw.agent import (
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
    ToolPreparingEvent,
    ToolStartEvent,
    UserEvent,
    SlashCommandEvent,
    ShellCommandEvent,
)
from uniclaw.commands import handle_slash
from uniclaw.config import Permissions, load_config, AppConfig
from uniclaw.tools.shell import Bash
from uniclaw.ilink_bot import IlinkBotClient, IncomingMessage
from uniclaw.ilink_bot.media import download_media, detect_ext
from uniclaw.context import build_system_prompt
from uniclaw.console.ui import C, clr, info, ok, warn, err

# 每个用户独立的配置(含 session 和 agent)
_user_configs: dict[str, AppConfig] = {}


def _get_user_config(user_id: str) -> AppConfig:
    """获取或创建用户的 AppConfig(含独立的 session 和 agent)。"""
    if user_id not in _user_configs:
        from uniclaw.spinner import NoopSpinner

        config = load_config(root_dir=Path.cwd(), spinner=NoopSpinner())
        config.interactive = False
        config.current_agent.name = f"wechat-{user_id}"
        _user_configs[user_id] = config
    return _user_configs[user_id]


async def _build_user_message(
    msg: IncomingMessage, bot: IlinkBotClient, config: AppConfig
) -> str | list:
    """构造用户消息,包含文本和图片的多模态内容。"""
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
            await warn(f"图片下载失败: {e}", config)

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


async def _collect_response(
    config: AppConfig,
    client: IlinkBotClient | None = None,
    msg: IncomingMessage | None = None,
) -> str:
    """从事件队列中收集 Agent 的文本回复。

    Args:
        config: 用户的 AppConfig(含 current_agent)
        client: iLink Bot 客户端,用于实时发送工具调用通知
        msg: 原始消息,用于回复目标用户
    """
    task = config.current_agent
    spinner = config.spinner
    spinner_wait_id: str | None = None
    parts: list[str] = []
    current_name = ""
    current_args: dict = {}
    thinking_stream = False
    text_stream = False
    while True:
        _agent_task, event = await asyncio.to_thread(task.event_queue.get)
        if spinner_wait_id:
            spinner.stop(spinner_wait_id)
            spinner_wait_id = None
        if isinstance(event, ThinkingStartEvent):
            spinner_wait_id = spinner.start("Thinking...")
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
                    fn = tc.get("function", {})
                    print(
                        clr(
                            f"    - {fn.get('name', '?')}({fn.get('arguments', '')})",
                            C.CYAN,
                        )
                    )
            print(
                clr(
                    f"  模型:{event.model_name}  输入:{event.in_tokens} 输出:{event.out_tokens}",
                    C.DIM,
                )
            )
        elif isinstance(event, ToolPreparingEvent):
            label = _format_tool_call(event.name, event.args)
            spinner_wait_id = spinner.start(f"准备调用 '{label}'...")
        elif isinstance(event, ToolStartEvent):
            current_name = event.name
            current_args = event.args
            label = _format_tool_call(event.name, event.args)
            spinner_wait_id = spinner.start(f"工具 '{label}' 执行中...")
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
            # 显示用户输入消息(微信模式下通常不需要显示,但保留用于调试)
            pass
        elif isinstance(event, PermissionRequestEvent):
            event.content = "微信不支持权限请求交互,默认拒绝。"
            event.return_event.set()
        elif isinstance(event, ShellCommandEvent):
            await info(f"[微信] 用户执行Shell命令: {event.command}", config)
            result = await Bash.func(event.command, config=config)
            output = _ANSI_RE.sub("", result).strip()
            print(clr(f"  $ {event.command}", C.CYAN))
            print(clr(output or "(无输出)", C.DIM))
            event.content = output
            event.return_event.set()
        elif isinstance(event, SlashCommandEvent):
            await info(f"[微信] 用户执行斜杠命令: {event.command}", config)
            buf = io.StringIO()
            with redirect_stdout(buf):
                await handle_slash(event.command, config)
            output = _ANSI_RE.sub("", buf.getvalue()).strip()
            if output:
                print(clr(output, C.WHITE))
            event.content = ""
            event.return_event.set()
        elif isinstance(event, EndEvent):
            if event.depth == 0:
                break
    print()
    return "".join(parts)


def make_handler():
    """创建消息处理函数,注册到 BotManager。

    Returns:
        ManagerHandler 签名的处理函数 (bot, msg)
    """

    multi_agent = MultiAgent.get_instance()

    async def handler(bot: IlinkBotClient, msg: IncomingMessage):
        user_id = msg.user_id
        text = msg.text.strip()
        if not text and not msg.images:
            return

        config = _get_user_config(user_id)
        task = config.current_agent

        await info(f"[微信] 收到消息 [{user_id}]: {text or '(图片)'}", config)

        # /命令处理
        if text.startswith("/"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = await handle_slash(text, config)
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
                await info(f"[微信] 执行命令: {shell_cmd}", config)
                result = await Bash.func(shell_cmd, config=config)
                output = _ANSI_RE.sub("", result).strip()
                bot.reply_text(msg, output.replace("\n", "\n\n") or "(无输出)")
            return

        user_message = await _build_user_message(msg, bot, config)

        # 检查该用户是否有正在运行的 agent 任务
        task_name = f"wechat-{user_id}"
        for t in multi_agent.id2AgentTask.values():
            if t.name == task_name and t.status == AgentStatus.RUNNING:
                t.user_queue.put_nowait(
                    user_message if isinstance(user_message, str) else str(user_message)
                )
                await info(f"[微信] 用户 {user_id} 的 agent 正在运行,消息已排队", config)
                bot.reply_text(msg, "⏳ 已排队,将在当前任务处理间隙自动补充。")
                return

        try:
            bot.send_typing(user_id, context_token=msg.context_token)
        except Exception:
            pass

        try:
            system_prompt = build_system_prompt(config)

            multi_agent.start_agent(
                user_message,
                config=config,
                system_prompt=system_prompt,
            )
            reply = await _collect_response(config, client=bot, msg=msg)

            if not reply:
                reply = "(Agent 未产生回复)"

            # 微信需要 \n+空格 才能正确换行
            bot.reply_text(msg, reply.replace("\n", "\n "))
            await ok(f"[微信] 已回复 [{user_id}]: {reply[:50]}...", config)

        except Exception as e:
            await err(f"[微信] 处理消息失败: {e}", config)
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
