"""调试辅助工具:检测协程/事件循环阻塞并写入日志文件。

核心原理:全局单线程 watchdog,即使事件循环被同步阻塞也能拿到控制权。
无论装饰多少函数,始终只有 1 个监控线程。
每次 await 返回后重置计时器,只在单次 await 长时间未返回时才报警。
"""

import os
import sys
import threading
import time
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Awaitable

# 日志文件路径:写入项目 .UniClaw/logs/ 目录
_LOG_DIR = Path.cwd() / ".UniClaw" / "logs"
_LOG_FILE = _LOG_DIR / "slow_await.log"


def _write_log(msg: str):
    """写入日志文件,带时间戳。"""
    os.makedirs(_LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


# ── 全局 watchdog ──────────────────────────────────────────────────────────

# 注册表:{id: (func_name, threshold, main_thread_id, last_active_time)}
_registry: dict[int, tuple[str, float, int, float]] = {}
_registry_lock = threading.Lock()
_next_id = 0
_watchdog_started = False
_watchdog_lock = threading.Lock()


def _global_watchdog():
    """全局 watchdog 线程:周期扫描所有注册项,单次 await 超时则打印堆栈。"""
    while True:
        with _registry_lock:
            if _registry:
                interval = min(t for _, t, _, _ in _registry.values())
                interval = max(interval, 0.1)
            else:
                interval = 0.5

        threading.Event().wait(interval)

        with _registry_lock:
            items = list(_registry.items())

        now = time.monotonic()
        for _, (func_name, threshold, main_thread_id, last_active) in items:
            elapsed = now - last_active
            if elapsed < threshold:
                continue

            frames = sys._current_frames()
            main_frame = frames.get(main_thread_id)
            if main_frame is None:
                continue

            # 事件循环空闲等待不算阻塞:栈顶在 _selector.select / GetQueuedCompletionStatus
            frame_str = "".join(traceback.format_stack(main_frame))
            if "_selector.select" in frame_str or "GetQueuedCompletionStatus" in frame_str:
                # 进一步确认:如果只有 _run_once 而没有 handle._run,说明是空闲等待
                if "handle._run" not in frame_str:
                    continue

            # 栈底(实际阻塞点)全是第三方/标准库代码不算阻塞
            # 只看最底部 3 帧(真正卡住的位置)
            stack_lines = traceback.format_stack(main_frame)
            bottom_frames = stack_lines[-3:] if len(stack_lines) > 3 else stack_lines
            blocking_is_third_party = all(
                "site-packages" in line or "<frozen" in line or "cpython" in line
                for line in bottom_frames
            )
            if blocking_is_third_party:
                continue

            count = int(elapsed // threshold)
            lines = [
                f"⚠️  [{func_name}] 单次 await 阻塞超过 {elapsed:.1f}s(第{count}次检测)",
                f"--- Thread {main_thread_id} (blocked) ---",
            ]
            for line in traceback.format_stack(main_frame):
                lines.append(line.rstrip())
            _write_log("\n".join(lines))


def _ensure_watchdog():
    """懒启动全局 watchdog 线程(只创建一次)。"""
    global _watchdog_started
    if _watchdog_started:
        return
    with _watchdog_lock:
        if _watchdog_started:
            return
        t = threading.Thread(target=_global_watchdog, daemon=True)
        t.start()
        _watchdog_started = True


def _register(func_name: str, threshold: float, main_thread_id: int) -> int:
    """注册一个监控项,返回 entry_id。"""
    _ensure_watchdog()
    global _next_id
    with _registry_lock:
        entry_id = _next_id
        _next_id += 1
        _registry[entry_id] = (func_name, threshold, main_thread_id, time.monotonic())
    return entry_id


def _unregister(entry_id: int):
    """移除监控项。"""
    with _registry_lock:
        _registry.pop(entry_id, None)


def _touch_thread(thread_id: int):
    """重置同线程所有监控项的活跃时间(任何 await 返回说明事件循环未阻塞)。"""
    now = time.monotonic()
    with _registry_lock:
        for eid, (name, thr, tid, _) in _registry.items():
            if tid == thread_id:
                _registry[eid] = (name, thr, tid, now)


# ── Awaitable 包装器 ───────────────────────────────────────────────────────


class _TrackedAwaitable:
    """包装 Awaitable,每次 await 返回时重置 watchdog 计时器。"""

    __slots__ = ("_awaitable", "_thread_id")

    def __init__(self, awaitable: Awaitable, thread_id: int):
        self._awaitable = awaitable
        self._thread_id = thread_id

    def __await__(self):
        result = yield from self._awaitable.__await__()
        _touch_thread(self._thread_id)
        return result


# ── 装饰器 ─────────────────────────────────────────────────────────────────


def trace_slow_await(threshold: float = 1.0):
    """装饰器:当单次 await 阻塞超过 threshold 秒时,将堆栈写入日志文件。

    每次 await 返回后重置计时器,只在某个 await 长时间不返回时才报警。
    使用全局单线程 watchdog,无论装饰多少函数始终只有 1 个监控线程。

    日志路径:.UniClaw/logs/slow_await.log

    用法:
        @trace_slow_await(threshold=5.0)
        async def my_coro():
            await some_slow_operation()
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            main_thread_id = threading.current_thread().ident
            entry_id = _register(func.__qualname__, threshold, main_thread_id)
            try:
                result = await _TrackedAwaitable(
                    func(*args, **kwargs), main_thread_id
                )
                return result
            finally:
                _unregister(entry_id)

        return wrapper

    return decorator
