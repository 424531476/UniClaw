from .fs import get_tools as fs_get_tools, get_all_tools as fs_get_all_tools
from .multi_agent.tools import (
    get_tools as multi_agent_get_tools,
    get_all_tools as multi_agent_get_all_tools,
)
from .plan import get_tools as plan_get_tools, get_all_tools as plan_get_all_tools
from .shell import get_tools as shell_get_tools, get_all_tools as shell_get_all_tools
from .skill.tools import (
    get_tools as skill_get_tools,
    get_all_tools as skill_get_all_tools,
)
from .web import get_tools as web_get_tools, get_all_tools as web_get_all_tools
from .memory.tools import (
    get_tools as memory_get_tools,
    get_all_tools as memory_get_all_tools,
)
from .media import get_tools as media_get_tools, get_all_tools as media_get_all_tools
from .sandbox import (
    get_tools as sandbox_get_tools,
    get_all_tools as sandbox_get_all_tools,
)
from .scheduler.tools import (
    get_tools as scheduler_get_tools,
    get_all_tools as scheduler_get_all_tools,
)
from .sleep import get_tools as sleep_get_tools, get_all_tools as sleep_get_all_tools
from .monitor.tools import (
    get_tools as process_get_tools,
    get_all_tools as process_get_all_tools,
)
from .todolist import (
    get_tools as todolist_get_tools,
    get_all_tools as todolist_get_all_tools,
)
from .ask import get_tools as ask_get_tools, get_all_tools as ask_get_all_tools
from .mcp.tools import (
    get_tools as mcp_management_get_tools,
    get_all_tools as mcp_management_get_all_tools,
)
from .session import (
    get_tools as session_get_tools,
    get_all_tools as session_get_all_tools,
)
from .security import (
    get_tools as security_get_tools,
    get_all_tools as security_get_all_tools,
)
from .hooks.tools import (
    get_tools as hooks_get_tools,
    get_all_tools as hooks_get_all_tools,
)
from .computer_use import (
    get_tools as computer_use_get_tools,
    get_all_tools as computer_use_get_all_tools,
)
from .notify import get_tools as notify_get_tools, get_all_tools as notify_get_all_tools
from .mcp import MCPManager
from .registry import get_tools as registry_get_tools, init_registry

_registry_initialized = False


def _ensure_registry():
    """懒初始化工具注册表(仅首次调用时执行)。"""
    global _registry_initialized
    if _registry_initialized:
        return
    _registry_initialized = True
    all_tools = get_all_tools()
    init_registry(all_tools)


async def get_core_tools() -> list:
    """获取核心工具 + search_tools(约 15 个)。

    核心工具始终加载完整 schema,是 prompt 缓存的稳定前缀。
    扩展工具通过 search_tools 按需发现和加载。
    """
    from .registry import CORE_TOOL_NAMES

    _ensure_registry()
    all_candidates = [
        *fs_get_tools(),            # Read, Write, Edit, Glob
        *await shell_get_tools(),   # Bash, Grep
        *web_get_tools(),           # webFetch, webSearch
        *memory_get_tools(),        # memory_save/delete/list/search
        *plan_get_tools(),          # enter/exit_plan_mode
        *skill_get_tools(),         # skill_suggest/read/run_command
        *registry_get_tools(),      # search_tools 元工具
    ]
    # 过滤:只保留核心工具 + search_tools
    return [t for t in all_candidates if t.name in CORE_TOOL_NAMES or t.name == "search_tools"]


async def get_tools(todolist=None) -> list:
    """获取所有可用工具(包括 MCP 工具)"""
    mcp_manager = MCPManager.get_instance()
    mcp_tools = mcp_manager.get_mcp_tools()
    return [
        *fs_get_tools(),
        *multi_agent_get_tools(),
        *plan_get_tools(),
        *await shell_get_tools(),
        *skill_get_tools(),
        *web_get_tools(),
        *memory_get_tools(),
        *media_get_tools(),
        *await sandbox_get_tools(),
        *scheduler_get_tools(),
        *sleep_get_tools(),
        *process_get_tools(),
        *todolist_get_tools(todolist),
        *ask_get_tools(),
        *mcp_management_get_tools(),
        *session_get_tools(),
        *security_get_tools(),
        *hooks_get_tools(),
        *computer_use_get_tools(),
        *notify_get_tools(),
        *mcp_tools,
    ]


async def get_sub_agent_tools() -> list:
    """获取所有可用工具(包括 MCP 工具)"""
    mcp_manager = MCPManager.get_instance()
    mcp_tools = mcp_manager.get_mcp_tools()
    return [
        *fs_get_tools(),
        *multi_agent_get_tools(),
        *await shell_get_tools(),
        *skill_get_tools(),
        *web_get_tools(),
        *memory_get_tools(),
        *media_get_tools(),
        *await sandbox_get_tools(),
        *scheduler_get_tools(),
        *sleep_get_tools(),
        *process_get_tools(),
        *mcp_management_get_tools(),
        *session_get_tools(),
        *notify_get_tools(),
        *mcp_tools,
    ]


def get_all_tools() -> list:
    """获取所有内置工具"""
    mcp_manager = MCPManager.get_instance()
    mcp_tools = mcp_manager.get_mcp_tools()
    return [
        *fs_get_all_tools(),
        *multi_agent_get_all_tools(),
        *plan_get_all_tools(),
        *shell_get_all_tools(),
        *skill_get_all_tools(),
        *web_get_all_tools(),
        *memory_get_all_tools(),
        *media_get_all_tools(),
        *sandbox_get_all_tools(),
        *scheduler_get_all_tools(),
        *sleep_get_all_tools(),
        *process_get_all_tools(),
        *todolist_get_all_tools(),
        *ask_get_all_tools(),
        *mcp_management_get_all_tools(),
        *session_get_all_tools(),
        *security_get_all_tools(),
        *hooks_get_all_tools(),
        *computer_use_get_all_tools(),
        *notify_get_all_tools(),
        *mcp_tools,
    ]
