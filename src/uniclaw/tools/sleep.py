import threading
import asyncio
from datetime import datetime, timedelta
from uniclaw.tools.base import tool
from uniclaw.config import AppConfig


@tool
def sleep_timer(seconds: int, name: str = "", config: AppConfig = None) -> str:
    """
    异步等待指定秒数后唤醒 AI 继续工作。函数立即返回,不阻塞。

    Args:
        seconds: 等待秒数(1-3600)
        name: 可选的等待原因描述,用于日志
        config: 内部参数,由系统自动注入

    Returns:
        str: 确认消息
    """
    # 验证等待时间是否在合法范围内
    if seconds <= 0 or seconds > 3600:
        return "错误:等待秒数必须在 1-3600 之间"

    async def _wakeup(task):
        """后台线程执行的等待与唤醒逻辑"""
        await asyncio.sleep(seconds)
        reason = f"({name})" if name else ""
        task.user_queue.put_nowait(
            f"[system](sleep_timer) 已等待{reason}{seconds} 秒,请继续工作。"
        )

    asyncio.create_task(_wakeup(config.current_agent))

    # 计算并格式化预计唤醒的时间点
    wakeup_time = datetime.now() + timedelta(seconds=seconds)
    time_str = wakeup_time.strftime("%H:%M:%S")

    name_part = f"({name})" if name else ""
    return f"已设置 {seconds} 秒后唤醒{name_part},预计 {time_str} 唤醒,系统将自动以 [system](sleep_timer) 前缀发送唤醒通知,继续等待中..."


@tool
async def wait(seconds: float) -> str:
    """
    等待指定的秒数。此工具会阻塞当前线程,超过30秒请使用 sleep_timer。

    Args:
        seconds: 等待秒数(1-30)
    """

    await asyncio.sleep(seconds)
    return f"已等待 {seconds} 秒"


def get_tools() -> list:
    """获取睡眠定时器工具列表"""
    return [sleep_timer, wait]


def get_all_tools() -> list:
    """获取所有睡眠定时器工具(无条件返回)"""
    return get_tools()
