"""MCP 服务器管理器 — 直接使用 mcp 包,不依赖 langchain_mcp_adapters。"""

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from uniclaw.context import get_app_dir, Scope
from uniclaw.console.ui import err, info, ok
from uniclaw.tools.base import Tool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _connect_mcp(connection: dict):
    """根据 transport 类型建立 MCP 连接,统一返回 (read, write) 流。

    支持 stdio / sse / streamable_http / websocket 四种协议。
    """
    transport = connection.get("transport", "stdio")

    if transport == "stdio":
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=connection.get("command", ""),
            args=connection.get("args", []),
            env=connection.get("env"),
        )
        async with stdio_client(server_params) as (read, write):
            yield read, write

    elif transport == "sse":
        from mcp.client.sse import sse_client

        async with sse_client(
            url=connection["url"],
            headers=connection.get("headers"),
            timeout=connection.get("timeout", 5),
        ) as (read, write):
            yield read, write

    elif transport == "streamable_http":
        from mcp.client.streamable_http import streamable_http_client

        # streamable_http_client 不直接支持 headers,需要通过 http_client 传递
        headers = connection.get("headers")
        if headers:
            import httpx

            async with httpx.AsyncClient(headers=headers) as http_client:
                async with streamable_http_client(
                    url=connection["url"],
                    http_client=http_client,
                ) as (read, write, _get_session_id):
                    yield read, write
        else:
            async with streamable_http_client(
                url=connection["url"],
            ) as (read, write, _get_session_id):
                yield read, write

    elif transport == "websocket":
        from mcp.client.websocket import websocket_client

        async with websocket_client(url=connection["url"]) as (read, write):
            yield read, write

    else:
        raise ValueError(f"不支持的传输类型: {transport}")


def _make_mcp_caller(server_name: str, tool_name: str, connection: dict):
    """创建 MCP 工具的异步调用闭包。每次调用时建立连接、执行、断开。"""

    async def _call(**kwargs) -> str:
        from mcp import ClientSession

        try:
            async with _connect_mcp(connection) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=kwargs)
                    parts = []
                    for block in result.content:
                        if hasattr(block, "text"):
                            parts.append(block.text)
                        else:
                            parts.append(str(block))
                    return "\n".join(parts) if parts else "(无输出)"
        except Exception as e:
            return f"MCP 工具调用失败: {e}"

    _call.__name__ = f"{server_name}_{tool_name}"
    _call.__qualname__ = _call.__name__
    return _call


async def _discover_tools_async(server_name: str, connection: dict) -> list[Tool]:
    """异步连接 MCP 服务器,发现工具并转换为 Tool 对象。"""
    from mcp import ClientSession

    tools = []
    async with _connect_mcp(connection) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            for mcp_tool in tools_result.tools:
                full_name = f"{server_name}_{mcp_tool.name}"
                schema = mcp_tool.inputSchema or {"type": "object", "properties": {}}
                caller = _make_mcp_caller(server_name, mcp_tool.name, connection)
                tools.append(Tool(
                    name=full_name,
                    description=mcp_tool.description or "",
                    func=caller,
                    parameters=schema,
                ))
    return tools


class MCPManager:
    """MCP 服务器管理器(单例)"""

    _instance: "MCPManager | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._config_path: Path = get_app_dir(Scope.USER) / "mcp.json"
        self._config: dict = {"servers": {}}
        self._client = None
        self.server2tools: dict[str, list] = {}
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "MCPManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def load_config(self, config=None) -> dict:
        if not self._config_path.exists():
            self._config = {"servers": {}}
            return self._config
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            if "servers" not in self._config:
                self._config["servers"] = {}
        except (json.JSONDecodeError, IOError) as e:
            err(f"加载 MCP 配置失败: {e}", config)
            self._config = {"servers": {}}
        return self._config

    def save_config(self, config: dict | None = None):
        if config is not None:
            self._config = config
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)

    def list_servers(self, config=None) -> list[dict]:
        self.load_config(config)
        servers = []
        for name, conn in self._config.get("servers", {}).items():
            entry = {"name": name, **conn}
            servers.append(entry)
        return servers

    def get_server(self, name: str, config=None) -> dict | None:
        self.load_config(config)
        conn = self._config.get("servers", {}).get(name)
        if conn is None:
            return None
        return {"name": name, **conn}

    async def add_server(
        self,
        name: str,
        connection: dict,
        enabled: bool = True,
        skip_validation: bool = False,
        config=None,
    ):
        self.load_config(config)
        if name in self._config["servers"]:
            raise ValueError(f"服务器 '{name}' 已存在")
        if not skip_validation and not await self.test_connection(connection, config):
            raise ValueError("连接验证失败")
        connection["enabled"] = enabled
        self._config["servers"][name] = connection
        self.save_config()
        await self.refresh(config)

    async def remove_server(self, name: str, config=None) -> bool:
        self.load_config(config)
        if name not in self._config["servers"]:
            return False
        del self._config["servers"][name]
        self.save_config()
        await self.refresh(config)
        return True

    async def update_server(self, name: str, connection: dict, config=None) -> bool:
        self.load_config(config)
        if name not in self._config["servers"]:
            return False
        old = self._config["servers"][name]
        connection["enabled"] = old.get("enabled", True)
        self._config["servers"][name] = connection
        self.save_config()
        await self.refresh(config)
        return True

    async def toggle_server(self, name: str, enabled: bool, config=None) -> bool:
        self.load_config(config)
        if name not in self._config["servers"]:
            return False
        self._config["servers"][name]["enabled"] = enabled
        self.save_config()
        await self.refresh(config)
        return True

    def _build_connections(self, config=None) -> dict:
        self.load_config(config)
        connections = {}
        for name, conn in self._config.get("servers", {}).items():
            if not conn.get("enabled", True):
                continue
            clean = {k: v for k, v in conn.items() if k != "enabled"}
            connections[name] = clean
        return connections

    async def init_client(self, config=None):
        """异步并发连接所有 MCP 服务器,单个失败不影响其他。"""
        connections = self._build_connections(config)
        if not connections:
            self._client = None
            self.server2tools = {}
            return None
        self.server2tools = {k: list() for k in connections.keys()}

        async def _try_discover(server_name: str, conn: dict):
            try:
                tools = await _discover_tools_async(server_name, conn)
                self.server2tools[server_name] = tools
                ok(f"MCP [{server_name}] 连接成功,发现 {len(tools)} 个工具", config)
            except Exception as e:
                err(f"MCP [{server_name}] 连接失败: {e}", config)
                self.server2tools[server_name] = []

        await asyncio.gather(*[
            _try_discover(name, conn) for name, conn in connections.items()
        ])
        self._client = True
        return self._client

    def get_mcp_tools(self) -> list:
        return [tool for tools in self.server2tools.values() for tool in tools]

    async def test_connection(self, connection: dict, config=None) -> bool:
        """测试单个 MCP 连接是否可用"""
        try:
            tools = await _discover_tools_async("test", connection)
            ok(f"连接验证成功,发现 {len(tools)} 个工具", config)
            return True
        except Exception as e:
            err(f"连接验证失败: {e}", config)
            return False

    async def refresh(self, config=None):
        """重新初始化客户端以加载最新配置"""
        await self.init_client(config)

    def get_tools_info(self, server_name: str | None = None) -> list[dict]:
        info = []
        if server_name is not None:
            servers = {server_name: self.server2tools.get(server_name, [])}
        else:
            servers = self.server2tools
        for srv_name, tools in servers.items():
            for tool in tools:
                info.append(
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "server": srv_name,
                    }
                )
        return info


# 导出工具函数
from .tools import get_tools, get_all_tools
