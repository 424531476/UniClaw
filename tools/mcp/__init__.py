import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from context import get_app_dir, Scope
from console.ui import err, info, ok, warn


class MCPManager:
    """MCP 服务器管理器（单例）"""

    _instance: "MCPManager | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._config_path: Path = get_app_dir(Scope.USER) / "mcp.json"
        self._config: dict = {"servers": {}}
        self._client = None
        self.server2tools: dict[str, list] = {}
        self.refresh()  # 确保工具列表是最新的

    @classmethod
    def get_instance(cls) -> "MCPManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def load_config(self) -> dict:
        if not self._config_path.exists():
            self._config = {"servers": {}}
            return self._config
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            if "servers" not in self._config:
                self._config["servers"] = {}
        except (json.JSONDecodeError, IOError) as e:
            err(f"加载 MCP 配置失败: {e}")
            self._config = {"servers": {}}
        return self._config

    def save_config(self, config: dict | None = None):
        if config is not None:
            self._config = config
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)

    def list_servers(self) -> list[dict]:
        self.load_config()
        servers = []
        for name, conn in self._config.get("servers", {}).items():
            entry = {"name": name, **conn}
            servers.append(entry)
        return servers

    def get_server(self, name: str) -> dict | None:
        self.load_config()
        conn = self._config.get("servers", {}).get(name)
        if conn is None:
            return None
        return {"name": name, **conn}

    def add_server(
        self,
        name: str,
        connection: dict,
        enabled: bool = True,
        skip_validation: bool = False,
    ):
        self.load_config()
        if name in self._config["servers"]:
            raise ValueError(f"服务器 '{name}' 已存在")
        # 验证连接
        if not skip_validation and not self.test_connection(connection):
            raise ValueError("连接验证失败")
        connection["enabled"] = enabled
        self._config["servers"][name] = connection
        self.save_config()
        self.refresh()

    def remove_server(self, name: str) -> bool:
        self.load_config()
        if name not in self._config["servers"]:
            return False
        del self._config["servers"][name]
        self.save_config()
        self.refresh()
        return True

    def update_server(self, name: str, connection: dict) -> bool:
        self.load_config()
        if name not in self._config["servers"]:
            return False
        old = self._config["servers"][name]
        connection["enabled"] = old.get("enabled", True)
        self._config["servers"][name] = connection
        self.save_config()
        return True

    def toggle_server(self, name: str, enabled: bool) -> bool:
        self.load_config()
        if name not in self._config["servers"]:
            return False
        self._config["servers"][name]["enabled"] = enabled
        self.save_config()
        self.refresh()
        return True

    def _build_connections(self) -> dict:
        self.load_config()
        connections = {}
        for name, conn in self._config.get("servers", {}).items():
            if not conn.get("enabled", True):
                continue
            clean = {k: v for k, v in conn.items() if k != "enabled"}
            connections[name] = clean
        return connections

    def init_client(self):
        connections = self._build_connections()
        if not connections:
            self._client = None
            self.server2tools = {}
            return None
        self.server2tools = {k: list() for k in connections.keys()}
        try:
            self._client = MultiServerMCPClient(connections, tool_name_prefix=True)
            mcp_tools = asyncio.run(self._client.get_tools())
            for tool in mcp_tools:
                for server_name in connections.keys():
                    if tool.name.startswith(f"{server_name}_"):
                        self.server2tools[server_name].append(tool)
                    # 确保工具名称以服务器名为前缀
        except Exception as e:
            err(f"初始化 MCP 客户端失败: {e}")
            self._client = None
            self.server2tools = {}
        return self._client

    def get_mcp_tools(self) -> list:
        return [tool for tools in self.server2tools.values() for tool in tools]

    def test_connection(self, connection: dict) -> bool:
        """测试单个 MCP 连接是否可用"""
        try:
            client = MultiServerMCPClient({"test": connection}, tool_name_prefix=True)
            tools = asyncio.run(client.get_tools())
            ok(f"连接验证成功，发现 {len(tools)} 个工具")
            return True
        except Exception as e:
            err(f"连接验证失败: {e}")
            return False

    def refresh(self):
        """重新初始化客户端以加载最新配置"""
        self.init_client()

    def get_tools_info(self, server_name: str | None = None) -> list[dict]:
        info = []
        for tool in self.server2tools.get(server_name, []):
            info.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "server": server_name or "unknown",
                }
            )
        return info


# 导出工具函数
from .tools import get_tools, get_all_tools
