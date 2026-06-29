"""FastAPI 应用实例。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from uniclaw.webui.api import router as api_router
from uniclaw.webui.ws import websocket_endpoint

# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动时初始化微信 BotManager
    from uniclaw.ilink_bot.manager import BotManager
    manager = BotManager()
    # 注册消息处理器（复用微信模式）
    if not manager._handlers:
        from uniclaw.wechat.run import make_handler
        handler = make_handler()
        manager.on_message(handler)
    # 启动已登录 bot 的消息轮询
    if any(b.is_logged_in for b in manager.bots) and not manager.is_running:
        asyncio.create_task(manager.start())
    yield
    # 关闭时停止 BotManager
    if manager.is_running:
        manager.stop()


app = FastAPI(title="UniClaw WebUI", version="1.0.0", lifespan=lifespan)

# CORS 中间件(开发用)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 REST API 路由
app.include_router(api_router)

# WebSocket 路由
app.add_api_websocket_route("/ws", websocket_endpoint)


# 静态文件挂载
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    """返回 SPA 入口页面。"""
    return FileResponse(str(STATIC_DIR / "index.html"))
