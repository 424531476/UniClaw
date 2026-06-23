"""WebSocket 管理器：连接、事件桥接、权限交互。"""

from __future__ import annotations

import asyncio
import queue
import traceback
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from cachetools import LRUCache

from uniclaw.agent import (
    AgentStatus,
    EndEvent,
    InterruptedEvent,
    MultiAgent,
    PermissionRequestEvent,
    ShellCommandEvent,
    TextChunkEvent,
    ThinkingChunkEvent,
    ThinkingStartEvent,
    ToolPreparingEvent,
    ToolStartEvent,
    ToolEvent,
    AssistantEvent,
    UserEvent,
)
from uniclaw.config import AppConfig, load_config
from uniclaw.tools.session.session_manager import SessionManager
from uniclaw.tools.base import tc_name, tc_args
from uniclaw.tools.shell import Bash
from uniclaw.webui.spinner import WebSpinner
from uniclaw.utils.constants import SYSTEM_PREFIX
from uniclaw.utils.logger import get_logger
from uniclaw.utils.message import MessageRole
from pathlib import Path

# 会话 LRU 缓存：session_id → AppConfig
session_cache: LRUCache[str, AppConfig] = LRUCache(maxsize=10)

# 所有已连接的 WebSocket(广播用)
_connected_ws: set[WebSocket] = set()
_connected_ws_lock = asyncio.Lock()

# 挂起的权限请求：req_id → asyncio.Future(需要锁保护)
pending_permissions: dict[str, asyncio.Future] = {}
_permissions_lock = asyncio.Lock()

# 挂起的输入请求：req_id → asyncio.Future(需要锁保护)
pending_inputs: dict[str, asyncio.Future] = {}
_inputs_lock = asyncio.Lock()

# 正在运行的 bridge_events 任务：(ws, session_id) → asyncio.Task(需要锁保护)
_bridge_tasks: dict[tuple, asyncio.Task] = {}
_bridge_tasks_lock = asyncio.Lock()

# 正在运行的 _watch_user_queue 任务：(ws, session_id) → asyncio.Task
_watch_tasks: dict[tuple, asyncio.Task] = {}
_watch_tasks_lock = asyncio.Lock()


@dataclass
class PendingRequest:
    """会话级待处理请求,跨 WebSocket 连接存活。"""
    msg_type: str            # "permission_request" | "input_request"
    msg_data: dict           # 发给前端的完整消息(用于重发)
    future: asyncio.Future   # 等待前端响应的 Future


# session_id → {req_id → PendingRequest},不随 WS 断开清除
pending_session_requests: dict[str, dict[str, PendingRequest]] = {}
_pending_session_lock = asyncio.Lock()


async def get_or_load_session(session_id: str) -> AppConfig:
    """从缓存获取 AppConfig,缓存未命中则从磁盘加载。"""
    if session_id in session_cache:
        config = session_cache[session_id]
        # 确保 event_queue 已初始化
        if config.current_agent.event_queue is None:
            config.current_agent.event_queue = queue.Queue()
        return config
    # 从磁盘加载
    session = SessionManager.load_session(session_id)
    if not session:
        raise ValueError(f"会话 {session_id} 不存在")
    spinner = WebSpinner()
    config = load_config(root_dir=session.root_dir, spinner=spinner)
    config.current_agent.session = session
    # 初始化 event_queue
    config.current_agent.event_queue = queue.Queue()
    session_cache[session_id] = config
    return config


async def _register_pending(session_id: str, req_id: str, req: PendingRequest):
    """注册待处理请求到会话级注册表。"""
    async with _pending_session_lock:
        if session_id not in pending_session_requests:
            pending_session_requests[session_id] = {}
        pending_session_requests[session_id][req_id] = req
    # 通知所有连接的前端：该会话有待处理请求
    await _broadcast_attention(session_id, req.msg_type)


async def _unregister_pending(session_id: str, req_id: str):
    """从注册表移除已处理的请求。"""
    async with _pending_session_lock:
        session_reqs = pending_session_requests.get(session_id)
        if session_reqs:
            session_reqs.pop(req_id, None)
            if not session_reqs:
                del pending_session_requests[session_id]
    # 检查该会话是否还有其他待处理请求
    async with _pending_session_lock:
        has_remaining = session_id in pending_session_requests
    if not has_remaining:
        await _broadcast_attention_clear(session_id)


async def _broadcast_attention(session_id: str, reason: str):
    """广播 session_attention 事件。"""
    await _broadcast({
        "event": "session_attention",
        "session_id": session_id,
        "reason": reason,
        "message": "会话有待处理的请求",
    })


async def _broadcast_attention_clear(session_id: str):
    """广播 session_attention_clear 事件。"""
    await _broadcast({
        "event": "session_attention_clear",
        "session_id": session_id,
    })


async def _broadcast(data: dict):
    """向所有已连接的 WebSocket 广播消息(前端按 session_id 过滤)。"""
    async with _connected_ws_lock:
        targets = list(_connected_ws)
    for w in targets:
        await _safe_send(w, data)


async def _resend_pending_requests(session_id: str):
    """当 set_active 或 chat 时,重新发送该会话的所有待处理请求。"""
    async with _pending_session_lock:
        reqs = dict(pending_session_requests.get(session_id, {}))
    if reqs:
        get_logger("webui", Path.cwd()).info(
            f"[{session_id}] 重发 {len(reqs)} 个待处理请求: {list(reqs.keys())}"
        )
    for req_id, req in reqs.items():
        if not req.future.done():
            await _broadcast(req.msg_data)


async def handle_permission_response(req_id: str, approved: bool, reason: str = "", always: bool = False):
    """处理权限响应,唤醒等待的 bridge_events。"""
    async with _permissions_lock:
        future = pending_permissions.get(req_id)
    if future and not future.done():
        future.set_result({"approved": approved, "reason": reason, "always": always})


async def handle_input_response(req_id: str, value: str = ""):
    """处理输入响应,唤醒等待的命令。"""
    async with _inputs_lock:
        future = pending_inputs.get(req_id)
    if future and not future.done():
        future.set_result(value)


async def bridge_events(session_id: str, ws: WebSocket, config: AppConfig):
    """读取 agent 的 event_queue,将事件广播给所有订阅该会话的连接。"""
    task = config.current_agent
    get_logger("webui", Path.cwd()).info(f"[{session_id}] bridge_events 启动")
    # 通知前端 agent 状态
    await _broadcast({"event": "status", "session_id": session_id, "status": "running"})
    loop = asyncio.get_event_loop()
    while True:
        try:
            # queue.Queue.get() 是阻塞调用,用 run_in_executor 避免阻塞事件循环
            _, event = await loop.run_in_executor(None, task.event_queue.get)
            get_logger("webui", Path.cwd()).info(f"[{session_id}] 收到事件: {type(event).__name__}")
        except Exception as e:
            get_logger("webui", Path.cwd()).error(f"[{session_id}] bridge_events 异常: {e}")
            break

        # === 生命周期事件 ===
        if isinstance(event, EndEvent):
            config.spinner.stop(wait_id=task.id)
            # 保存 session 到磁盘(与 console 模式一致)
            if event.depth == 0:
                try:
                    await SessionManager.save_session(task, config)
                except Exception:
                    get_logger("webui", Path.cwd()).error("会话保存失败", exc_info=True)
            # 发送最终 TodoList 状态
            await _send_todolist(session_id, task)
            await _broadcast({"event": "status", "session_id": session_id, "status": "completed"})
            await _broadcast({"event": "end", "session_id": session_id, "depth": event.depth})
            break

        # === 阻塞事件：需要等待前端响应 ===
        elif isinstance(event, PermissionRequestEvent):
            req_id = f"perm_{id(event)}"
            _tn = tc_name(event.tool_call)
            _ta = tc_args(event.tool_call)
            get_logger("webui", Path.cwd()).info(
                f"[{session_id}] 权限请求: tool={_tn}, args={_ta}, raw_tool_call_keys={list(event.tool_call.keys())}"
            )
            permission_msg = {
                "event": "permission_request",
                "id": req_id,
                "session_id": session_id,
                "tool_name": _tn,
                "args": _ta,
                "description": event.description,
                "explanation": event.explanation,
            }

            # 创建 Future 并注册到会话级注册表(跨 WS 连接存活)
            perm_future: asyncio.Future = asyncio.get_event_loop().create_future()
            pending_req = PendingRequest(
                msg_type="permission_request",
                msg_data=permission_msg,
                future=perm_future,
            )
            async with _permissions_lock:
                pending_permissions[req_id] = perm_future
            await _register_pending(session_id, req_id, pending_req)

            # 广播给所有订阅该会话的连接
            await _broadcast(permission_msg)

            try:
                response = await asyncio.wait_for(perm_future, timeout=300)
            except asyncio.TimeoutError:
                response = {"approved": False, "reason": "权限请求超时"}
            finally:
                async with _permissions_lock:
                    pending_permissions.pop(req_id, None)
                await _unregister_pending(session_id, req_id)

            if response["approved"]:
                event.content = True
                # "始终允许"：将规则持久化
                if response.get("always") and config.root_dir:
                    try:
                        from uniclaw.tools.security.security import add_permission_rule
                        tool_name = tc_name(event.tool_call)
                        add_permission_rule("tool", tool_name, Path(config.root_dir))
                    except Exception:
                        pass
            else:
                event.content = response["reason"] if response["reason"] else False
            event.return_event.set()

        # === 流式事件 ===
        elif isinstance(event, ThinkingStartEvent):
            config.spinner.start("Thinking...", wait_id=task.id)
            await _broadcast({"event": "thinking_start", "session_id": session_id})

        elif isinstance(event, ThinkingChunkEvent):
            config.spinner.start("Thinking...", wait_id=task.id)
            await _broadcast({"event": "thinking", "session_id": session_id, "content": event.content})

        elif isinstance(event, TextChunkEvent):
            config.spinner.stop(wait_id=task.id)
            await _broadcast({"event": "text", "session_id": session_id, "content": event.content})

        elif isinstance(event, ToolPreparingEvent):
            config.spinner.start(f"'{event.name}'...", wait_id=task.id)
            await _broadcast({
                "event": "tool_preparing",
                "session_id": session_id,
                "name": event.name,
                "args": event.args,
            })

        # === 批量事件 ===
        elif isinstance(event, UserEvent):
            await _broadcast({"event": "user", "session_id": session_id, "content": event.content})

        elif isinstance(event, AssistantEvent):
            config.spinner.stop(wait_id=task.id)
            await _broadcast({
                "event": "assistant",
                "session_id": session_id,
                "content": event.content,
                "tool_calls": event.tool_calls,
                "in_tokens": event.in_tokens,
                "out_tokens": event.out_tokens,
                "model_name": event.model_name,
            })

        elif isinstance(event, ToolStartEvent):
            config.spinner.stop(wait_id=task.id)
            config.spinner.start(f"'{event.name}' 执行中...", wait_id=task.id)
            await _broadcast({
                "event": "tool_start",
                "session_id": session_id,
                "name": event.name,
                "args": event.args,
                "tool_call_id": event.tool_call_id,
            })

        elif isinstance(event, ToolEvent):
            config.spinner.stop(wait_id=task.id)
            await _broadcast({
                "event": "tool_end",
                "session_id": session_id,
                "name": event.name,
                "content": event.content,
                "tool_call_id": event.tool_call_id,
                "args": event.args,
            })
            # 工具执行后,同步 TodoList 状态到前端
            await _send_todolist(session_id, task)

        # === 用户 Shell 命令(agent 运行时) ===
        elif isinstance(event, ShellCommandEvent):
            config.spinner.stop(wait_id=task.id)
            await _broadcast({"event": "shell_running", "session_id": session_id, "command": event.command})
            try:
                out = await Bash.func(event.command, config=config)
            except Exception as e:
                out = f"命令执行失败: {e}"
            await _broadcast({
                "event": "shell_result",
                "session_id": session_id,
                "command": event.command,
                "output": out,
                "success": True,
                "source": event.source,
            })
            event.content = out
            event.return_event.set()
            continue

        # === 状态事件 ===
        elif isinstance(event, InterruptedEvent):
            config.spinner.stop(wait_id=task.id)
            await _broadcast({"event": "interrupted", "session_id": session_id, "message": event.message})

        else:
            get_logger("webui", Path.cwd()).warning(f"未知事件类型: {type(event).__name__}")


async def _safe_send(ws: WebSocket, data: dict):
    """安全发送 WebSocket 消息,忽略断开异常。"""
    try:
        await ws.send_json(data)
    except Exception:
        pass


def _make_output_callback(ws: WebSocket, session_id: str):
    """创建 info/ok/warn/err 的输出回调,实时发送到 WebSocket。"""

    # 捕获当前事件循环(创建时一定在 async 上下文中)
    loop = asyncio.get_running_loop()

    def _send(msg_text: str, level: str):
        try:
            coro = _safe_send(ws, {
                "event": "command_output",
                "session_id": session_id,
                "content": msg_text,
                "level": level,
            })
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            pass

    return _send


async def _send_todolist(session_id: str, task):
    """如果 TodoList 有内容,广播状态给所有订阅者。"""
    todo = task.todolist
    if todo and not todo.is_empty():
        await _broadcast({
            "event": "todolist",
            "session_id": session_id,
            "items": [{"content": it.content, "status": it.status.value} for it in todo.items],
        })


async def _watch_user_queue(session_id: str, ws: WebSocket, config: AppConfig):
    """bridge_events 结束后监听 user_queue,捕获延迟唤醒消息(如 sleep_timer)并重新触发 agent。"""
    key = (id(ws), session_id)
    async with _watch_tasks_lock:
        _watch_tasks[key] = asyncio.current_task()
    task = config.current_agent
    try:
        while True:
            msg = await task.user_queue.get()
            if not msg:
                continue
            if task.status != AgentStatus.RUNNING:
                # 使用 config.ws_send 回调(始终指向最新连接)
                ws_send = getattr(config, "ws_send", None)
                if ws_send:
                    try:
                        await ws_send({"event": "system_message", "session_id": session_id, "content": msg})
                    except Exception:
                        pass
                multi_agent = MultiAgent.get_instance()
                multi_agent.start_agent(msg, config)
                await _start_bridge(session_id, ws, config)
                break
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        async with _watch_tasks_lock:
            _watch_tasks.pop(key, None)


async def _start_bridge(session_id: str, ws: WebSocket, config: AppConfig):
    """启动 bridge_events 任务(如果尚未运行)。"""
    key = (id(ws), session_id)
    async with _bridge_tasks_lock:
        task = _bridge_tasks.get(key)
        if task and not task.done():
            return  # 已在运行
        t = asyncio.create_task(bridge_events(session_id, ws, config))
        _bridge_tasks[key] = t

        def _on_bridge_done(done_task: asyncio.Task):
            _bridge_tasks.pop(key, None)
            # bridge 结束后启动 user_queue 监听,捕获延迟唤醒消息(如 sleep_timer)
            asyncio.create_task(_watch_user_queue(session_id, ws, config))

        t.add_done_callback(_on_bridge_done)


async def handle_ws_message(ws: WebSocket, msg: dict):
    """处理客户端发来的 WS 消息。"""
    msg_type = msg.get("type", "")

    # === chat 消息：区分创建会话和已有会话 ===
    if msg_type == "chat":
        root_dir = msg.get("root_dir")
        session_id = msg.get("session_id")

        if root_dir and not session_id:
            # 创建新会话
            spinner = WebSpinner()
            config = load_config(root_dir=Path(root_dir), spinner=spinner)
            session_id = config.current_agent.session.id
            spinner.set_session_id(session_id)
            # 初始化 event_queue
            config.current_agent.event_queue = queue.Queue()
            session_cache[session_id] = config
            spinner.set_send_callback(ws.send_json)
            config.output_callback = _make_output_callback(ws, session_id)
            await _safe_send(ws, {"event": "session_created", "session_id": session_id, "root_dir": root_dir})
            await _start_bridge(session_id, ws, config)
        elif session_id and not root_dir:
            # 已有会话
            config = await get_or_load_session(session_id)
            config.output_callback = _make_output_callback(ws, session_id)
            await _start_bridge(session_id, ws, config)
            # 重发待处理请求(处理新浏览器连接的场景)
            await _resend_pending_requests(session_id)
        else:
            await _safe_send(ws, {"event": "error", "message": "chat 消息必须带 root_dir 或 session_id,二选一"})
            return

        # 存储 ws 回调,供 web_input / AskUserQuestion 等使用
        config.ws_send = ws.send_json
        task = config.current_agent
        raw_content = msg.get("content", "")

        content = _build_content_with_files(raw_content, msg.get("files", []))
        get_logger("webui", Path.cwd()).info(f"[{session_id}] 准备启动 agent, task.status={task.status}")
        if task.status != AgentStatus.RUNNING:
            get_logger("webui", Path.cwd()).info(f"[{session_id}] 启动 agent")
            multi_agent = MultiAgent.get_instance()
            agent_task = multi_agent.start_agent(content, config)
            get_logger("webui", Path.cwd()).info(f"[{session_id}] Agent 启动成功, future={agent_task.future}")
            # 添加异常回调,防止异常被静默吞掉
            if agent_task.future:
                agent_task.future.add_done_callback(
                    lambda t: get_logger("webui", Path.cwd()).error(f"[{session_id}] Agent error: {t.exception()}") if t.exception() else None
                )
        else:
            # Agent 正在运行,将消息放入队列(drain_user_queue 会处理)
            task.user_queue.put_nowait(content)
        return

    # === 其他消息：必须带 session_id ===
    session_id = msg.get("session_id")
    if not session_id:
        await _safe_send(ws, {"event": "error", "message": f"{msg_type} 消息必须带 session_id"})
        return

    try:
        config = await get_or_load_session(session_id)
    except ValueError as e:
        await _safe_send(ws, {"event": "error", "message": str(e), "session_id": session_id})
        return

    task = config.current_agent

    if msg_type == "shell":
        cmd = msg.get("command", "")
        source = msg.get("source", "chat")
        if task.status == AgentStatus.RUNNING:
            # Agent 运行中：放入 user_queue,drain_user_queue 会创建 ShellCommandEvent
            # !!前缀=控制台命令(不注入session)；!前缀=聊天区命令(注入session)
            prefix = "!!" if source == "console" else "!"
            task.user_queue.put_nowait(f"{prefix}{cmd}")
        else:
            # Agent 空闲：直接执行；仅聊天区命令注入 session
            try:
                output = await Bash.func(cmd, config=config)
            except Exception as e:
                output = f"命令执行失败: {e}"
            if source == "chat":
                task.session.add_message(
                    MessageRole.USER,
                    f"{SYSTEM_PREFIX}(用户执行Shell命令)\n$ {cmd}\n{output}",
                )
            await _safe_send(ws, {
                "event": "shell_result",
                "session_id": session_id,
                "command": cmd,
                "output": output,
                "success": True,
                "source": source,
            })

    elif msg_type == "command":
        from uniclaw.commands import handle_slash
        # 始终绑定当前 WebSocket 的回调(与 chat 路径一致)
        config.output_callback = _make_output_callback(ws, session_id)
        config.ws_send = ws.send_json
        source = msg.get("source", "chat")
        result = await handle_slash(msg.get("command", ""), config)
        # info/ok/warn/err 已通过 output_callback 实时发送
        # 仅 str 返回值(技能路径)需要额外发送
        if isinstance(result, str) and result:
            await _safe_send(ws, {
                "event": "command_result",
                "session_id": session_id,
                "command": msg.get("command", ""),
                "output": result,
                "source": source,
            })

    elif msg_type == "permission_response":
        await handle_permission_response(
            msg.get("id", ""),
            msg.get("approved", False),
            msg.get("reason", ""),
            msg.get("always", False),
        )

    elif msg_type == "input_response":
        await handle_input_response(
            msg.get("id", ""),
            msg.get("value", ""),
        )

    elif msg_type == "cancel":
        task.cancel_event.set()

    elif msg_type == "set_active":
        # 前端通知当前活跃会话：重发待处理请求
        await _resend_pending_requests(session_id)




def _build_content_with_files(content: str, files: list[dict]) -> Any:
    """构建带附件的消息内容。"""
    from uniclaw.tools.session.session import MultimodalBlock

    if not files:
        return content

    blocks = [MultimodalBlock(type="text", text=content)]
    for f in files:
        name = f.get("name", "")
        data = f.get("data", "")
        mime = f.get("mime", "")
        if mime.startswith("image/"):
            blocks.append(MultimodalBlock(type="image_url", image_url={"url": f"data:{mime};base64,{data}"}))
        else:
            blocks.append(MultimodalBlock(type="text", text=f"[附件: {name}]"))
    return blocks


async def websocket_endpoint(ws: WebSocket):
    """WebSocket 入口。"""
    await ws.accept()
    async with _connected_ws_lock:
        _connected_ws.add(ws)
    try:
        while True:
            data = await ws.receive_json()
            get_logger("webui", Path.cwd()).info(f"收到 WS 消息: {data.get('type', 'unknown')}")
            # 并发处理,避免接收循环被阻塞(如 command 等待 input_response 时死锁)
            asyncio.create_task(handle_ws_message(ws, data))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        get_logger("webui", Path.cwd()).error(f"WebSocket 错误: {traceback.format_exc()}")
    finally:
        async with _connected_ws_lock:
            _connected_ws.discard(ws)
        # 取消该 WS 关联的 bridge / watch 任务
        ws_id = id(ws)
        async with _bridge_tasks_lock:
            for key, t in list(_bridge_tasks.items()):
                if key[0] == ws_id:
                    t.cancel()
                    _bridge_tasks.pop(key, None)
        async with _watch_tasks_lock:
            for key, t in list(_watch_tasks.items()):
                if key[0] == ws_id:
                    t.cancel()
                    _watch_tasks.pop(key, None)
        # 注意：不清理 pending_permissions / pending_inputs / pending_session_requests
        # 待处理请求保持存活,等待用户重连后通过 set_active 重发


# ── 模块级便捷接口(供 commands/ 导入)──────────────────────


async def notify_session_switched(session_id: str, old_session_id: str = ""):
    """通知前端会话已切换(用于 fork 后切换到新会话)。"""
    await _broadcast({
        "event": "session_switched",
        "session_id": session_id,
        "old_session_id": old_session_id,
    })


async def notify_session_deleted(session_id: str, root_dir=None):
    """通知前端会话已删除。如果删除的是当前活跃会话,前端应进入新建会话状态。"""
    await _broadcast({
        "event": "session_deleted",
        "session_id": session_id,
        "root_dir": str(root_dir) if root_dir else None,
    })


async def web_input(prompt: str, title: str = "输入", config=None) -> str:
    """WebUI 模式的输入便捷函数,注册到会话级注册表并等待回答。"""
    ws_send = getattr(config, "ws_send", None)
    session_id = config.current_agent.session.id
    if not session_id:
        return ""
    req_id = f"input_{uuid.uuid4().hex[:8]}"
    input_msg = {
        "event": "input_request",
        "id": req_id,
        "session_id": session_id,
        "prompt": prompt,
        "title": title,
    }

    # 创建 Future 并注册到会话级注册表
    input_future: asyncio.Future = asyncio.get_event_loop().create_future()
    pending_req = PendingRequest(
        msg_type="input_request",
        msg_data=input_msg,
        future=input_future,
    )
    async with _inputs_lock:
        pending_inputs[req_id] = input_future
    await _register_pending(session_id, req_id, pending_req)

    # 发送给前端(ws_send 可能已过期,set_active 时会重发)
    if ws_send:
        try:
            await ws_send(input_msg)
        except Exception:
            pass

    try:
        return await asyncio.wait_for(input_future, timeout=300)
    except asyncio.TimeoutError:
        return ""
    finally:
        async with _inputs_lock:
            pending_inputs.pop(req_id, None)
        await _unregister_pending(session_id, req_id)
