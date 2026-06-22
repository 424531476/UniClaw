"""WebUI 模式启动入口。"""

from __future__ import annotations

from pathlib import Path

import uvicorn

from uniclaw.utils.logger import get_logger
import socket


def launch(host: str = "127.0.0.1", port: int = 8080):
    """启动 WebUI 模式。

    不在启动时创建 config — root_dir 由前端第一条消息指定。
    config 在 create_session 时按需创建。

    Args:
        host: 监听地址,默认 127.0.0.1(仅本地访问),0.0.0.0 允许局域网访问
        port: 端口号,默认 8080
    """
    from uniclaw.tools.scheduler.scheduler import Scheduler

    Scheduler.get_instance().start()

    logger = get_logger("webui", Path.cwd())
    logger.info(f"启动 WebUI 模式,地址: {host}:{port}")

    print(f"\n  UniClaw WebUI 已启动")
    if host == "0.0.0.0":
        # 显示本机 IP 地址方便局域网访问

        local_ip = _get_local_ip()
        print(f"  本地访问: http://localhost:{port}")
        if local_ip:
            print(f"  局域网访问: http://{local_ip}:{port}")
        else:
            print(f"  局域网访问: http://<本机IP>:{port}")
    else:
        print(f"  请在浏览器中打开: http://{host}:{port}")
    print()

    uvicorn.run(
        "uniclaw.webui.app:app",
        host=host,
        port=port,
        log_level="info",
    )


def _get_local_ip() -> str:
    """获取本机局域网 IP 地址。"""
    try:
        # 通过连接外部地址获取本机 IP(不会真正发送数据)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return ""
