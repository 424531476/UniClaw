import json
from agent import AgentTask
from console.ui import info, ok, warn, err


def cmd_mcp(args: str, task: AgentTask, config: dict) -> bool:
    """MCP 服务器管理"""
    from tools.mcp import MCPManager

    manager = MCPManager.get_instance()
    parts = args.strip().split(None, 1) if args else []
    subcmd = parts[0].lower() if parts else "list"
    subargs = parts[1] if len(parts) > 1 else ""
    interactive = config.get("interactive", True)

    if subcmd == "list" or not subcmd:
        _mcp_list(manager)
    elif subcmd == "add":
        # 解析 name 和 json_str
        add_parts = subargs.split(None, 1) if subargs else []
        name = add_parts[0] if add_parts else ""
        json_str = add_parts[1] if len(add_parts) > 1 else ""
        _mcp_add(manager, name, json_str)
    elif subcmd == "remove":
        _mcp_remove(manager, subargs, interactive)
    elif subcmd == "show":
        _mcp_show(manager, subargs)
    elif subcmd == "edit":
        # 解析 name 和 json_str
        edit_parts = subargs.split(None, 1) if subargs else []
        name = edit_parts[0] if edit_parts else ""
        json_str = edit_parts[1] if len(edit_parts) > 1 else ""
        _mcp_edit(manager, name, json_str)
    elif subcmd == "enable":
        _mcp_toggle(manager, subargs, True)
    elif subcmd == "disable":
        _mcp_toggle(manager, subargs, False)
    elif subcmd == "tools":
        _mcp_tools(manager, subargs)
    elif subcmd == "refresh":
        _mcp_refresh(manager)
    else:
        err(f"未知子命令: {subcmd}")
        info("可用命令: list, add, remove, show, edit, enable, disable, tools, refresh")
    return True


def _mcp_list(manager) -> bool:
    servers = manager.list_servers()
    if not servers:
        warn("暂无 MCP 服务器配置")
        info("使用 /mcp add <名称> 添加服务器")
        return True
    info(f"\nMCP 服务器 (共 {len(servers)} 个):\n")
    for s in servers:
        name = s["name"]
        transport = s.get("transport", "unknown")
        enabled = s.get("enabled", True)
        status = "✓ 启用" if enabled else "✗ 禁用"
        detail = ""
        if transport == "stdio":
            detail = f"{s.get('command', '')} {' '.join(s.get('args', []))}"
        else:
            detail = s.get("url", "")
        info(f"  [{status}] {name} ({transport})")
        info(f"    {detail}")
        info("")
    return True


def _mcp_add(manager, name: str, json_str: str = "") -> bool:
    """添加 MCP 服务器

    用法:
        /mcp add <名称>  - 交互式添加
        /mcp add <名称> <JSON>  - 通过 JSON 配置添加
    """
    if not name:
        err("请指定服务器名称: /mcp add <名称> [JSON]")
        return True

    if manager.get_server(name):
        err(f"服务器 '{name}' 已存在")
        return True

    # JSON 模式
    if json_str:
        try:
            connection = json.loads(json_str)
        except json.JSONDecodeError as e:
            err(f"JSON 格式错误: {e}")
            return False
        if "transport" not in connection:
            err("配置必须包含 'transport' 字段")
            return False
    else:
        # 交互式模式
        connection = _mcp_interactive_input()
        if connection is None:
            return False

    try:
        info("正在验证连接...")
        manager.add_server(name, connection)
    except ValueError as e:
        err(str(e))
        return False

    ok(f"✓ 已添加 MCP 服务器: {name}")
    info("正在刷新 MCP 工具...")
    manager.refresh()
    tools_count = len(manager.get_mcp_tools())
    ok(f"✓ 已加载 {tools_count} 个 MCP 工具")
    return True


def _mcp_interactive_input() -> dict | None:
    """交互式输入 MCP 配置"""
    from console.run import tui_input

    prompt = """\n选择传输类型:
  [1] stdio (本地进程)
  [2] sse (Server-Sent Events)
  [3] streamable_http (HTTP Streamable)
  [4] websocket (WebSocket)

请输入编号: """
    choice = tui_input(prompt).strip()

    transport_map = {"1": "stdio", "2": "sse", "3": "streamable_http", "4": "websocket"}
    transport = transport_map.get(choice)
    if not transport:
        err("无效选择")
        return None

    connection = {"transport": transport}

    if transport == "stdio":
        command = tui_input("请输入命令 (例如: npx, python, node): ").strip()
        if not command:
            err("命令不能为空")
            return None
        connection["command"] = command

        args_str = tui_input("请输入参数 (空格分隔): ").strip()
        if args_str:
            connection["args"] = args_str.split()

        env_prompt = "[可选] 环境变量 (KEY=VALUE 格式, 空行结束):"
        env = {}
        while True:
            line = tui_input(f"{env_prompt}\n> ").strip()
            if not line:
                break
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
            env_prompt = ""
        if env:
            connection["env"] = env

        cwd = tui_input("[可选] 工作目录: ").strip()
        if cwd:
            connection["cwd"] = cwd

    elif transport in ("sse", "streamable_http"):
        url = tui_input("请输入 URL: ").strip()
        if not url:
            err("URL 不能为空")
            return None
        connection["url"] = url

        headers_prompt = "[可选] 请求头 (KEY=VALUE 格式, 空行结束):"
        headers = {}
        while True:
            line = tui_input(f"{headers_prompt}\n> ").strip()
            if not line:
                break
            if "=" in line:
                k, v = line.split("=", 1)
                headers[k.strip()] = v.strip()
            headers_prompt = ""
        if headers:
            connection["headers"] = headers

        timeout_str = tui_input("[可选] 超时时间 (秒, 直接回车跳过): ").strip()
        if timeout_str:
            try:
                connection["timeout"] = float(timeout_str)
            except ValueError:
                pass

    elif transport == "websocket":
        url = tui_input("请输入 WebSocket URL: ").strip()
        if not url:
            err("URL 不能为空")
            return None
        connection["url"] = url

    return connection


def _mcp_remove(manager, name: str, interactive: bool = True) -> bool:
    if not name:
        err("请指定服务器名称: /mcp remove <名称>")
        return True
    if not manager.get_server(name):
        err(f"服务器 '{name}' 不存在")
        return True

    # 交互模式下需要确认
    if interactive:
        from console.run import tui_input
        confirm = tui_input(f"确认删除服务器 '{name}'? [y/N]: ").strip().lower()

        if confirm != "y":
            info("已取消")
            return True

    manager.remove_server(name)
    ok(f"✓ 已删除服务器: {name}")
    manager.refresh()
    return True


def _mcp_show(manager, name: str) -> bool:
    if not name:
        err("请指定服务器名称: /mcp show <名称>")
        return True
    server = manager.get_server(name)
    if not server:
        err(f"服务器 '{name}' 不存在")
        return True

    info(f"\n服务器: {name}\n")
    for k, v in server.items():
        if k == "name":
            continue
        if isinstance(v, dict):
            info(f"  {k}:")
            for dk, dv in v.items():
                info(f"    {dk}: {dv}")
        elif isinstance(v, list):
            info(f"  {k}: {' '.join(str(i) for i in v)}")
        else:
            info(f"  {k}: {v}")
    info("")
    return True


def _mcp_edit(manager, name: str, json_str: str = "") -> bool:
    """编辑 MCP 服务器

    用法:
        /mcp edit <名称>  - 交互式编辑
        /mcp edit <名称> <JSON>  - 通过 JSON 配置编辑
    """
    if not name:
        err("请指定服务器名称: /mcp edit <名称> [JSON]")
        return True
    server = manager.get_server(name)
    if not server:
        err(f"服务器 '{name}' 不存在")
        return True

    info(f"正在编辑服务器 '{name}'")
    old_connection = {k: v for k, v in server.items() if k not in ("name", "enabled")}
    old_enabled = server.get("enabled", True)
    manager.remove_server(name)

    try:
        result = _mcp_add(manager, name, json_str)
        if not result:
            raise Exception("添加失败")
        return True
    except Exception:
        # 恢复旧配置（跳过验证）
        try:
            manager.add_server(name, old_connection, old_enabled, skip_validation=True)
            manager.refresh()
            warn("已恢复原配置")
        except Exception:
            err("恢复原配置失败")
        return True


def _mcp_toggle(manager, name: str, enabled: bool) -> bool:
    if not name:
        cmd = "enable" if enabled else "disable"
        err(f"请指定服务器名称: /mcp {cmd} <名称>")
        return True
    if not manager.get_server(name):
        err(f"服务器 '{name}' 不存在")
        return True

    action = "启用" if enabled else "禁用"
    manager.toggle_server(name, enabled)
    ok(f"✓ 已{action}服务器: {name}")
    manager.refresh()
    return True


def _mcp_tools(manager, server_name: str) -> bool:
    tools_info = manager.get_tools_info(server_name if server_name else None)
    if not tools_info:
        warn("暂无可用的 MCP 工具")
        return True

    info(f"\nMCP 工具 (共 {len(tools_info)} 个):\n")
    for t in tools_info:
        info(f"  • {t['name']} (来自: {t['server']})")
        if t['description']:
            info(f"    {t['description']}")
    info("")
    return True


def _mcp_refresh(manager) -> bool:
    info("正在刷新 MCP 工具...")
    manager.refresh()
    tools_count = len(manager.get_mcp_tools())
    ok(f"✓ 已加载 {tools_count} 个 MCP 工具")
    return True
