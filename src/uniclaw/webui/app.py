"""FastAPI 应用实例。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from uniclaw.webui.api import router as api_router
from uniclaw.webui.ws import websocket_endpoint

# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="UniClaw WebUI", version="1.0.0")

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
