from .fs import get_tools as fs_get_tools
from .multi_agent.tools import get_tools as multi_agent_get_tools
from .plan import get_tools as plan_get_tools
from .shell import get_tools as shell_get_tools
from .skill.tools import get_tools as skill_get_tools
from .web import get_tools as web_get_tools
from .memory.tools import get_tools as memory_get_tools
from .image import get_tools as image_get_tools
from .sandbox import get_tools as sandbox_get_tools
from .scheduler import get_tools as scheduler_get_tools
from .sleep import get_tools as sleep_get_tools
from .process.tools import get_tools as process_get_tools
from .todolist import get_tools as todolist_get_tools
from .ask import get_tools as ask_get_tools
from .mcp.tools import get_tools as mcp_management_get_tools
from .fs import get_all_tools as fs_get_all_tools
from .multi_agent.tools import get_all_tools as multi_agent_get_all_tools
from .plan import get_all_tools as plan_get_all_tools
from .shell import get_all_tools as shell_get_all_tools
from .skill.tools import get_all_tools as skill_get_all_tools
from .web import get_all_tools as web_get_all_tools
from .memory.tools import get_all_tools as memory_get_all_tools
from .image import get_all_tools as image_get_all_tools
from .sandbox import get_all_tools as sandbox_get_all_tools
from .scheduler import get_all_tools as scheduler_get_all_tools
from .sleep import get_all_tools as sleep_get_all_tools
from .process.tools import get_all_tools as process_get_all_tools
from .todolist import get_all_tools as todolist_get_all_tools
from .ask import get_all_tools as ask_get_all_tools
from .mcp.tools import get_all_tools as mcp_management_get_all_tools
from .security import is_safe_bash
from .mcp import MCPManager


def get_tools() -> list:
    """获取所有可用工具（包括 MCP 工具）"""
    mcp_manager = MCPManager.get_instance()
    mcp_tools = mcp_manager.get_mcp_tools()
    return [
        *fs_get_tools(),
        *multi_agent_get_tools(),
        *plan_get_tools(),
        *shell_get_tools(),
        *skill_get_tools(),
        *web_get_tools(),
        *memory_get_tools(),
        *image_get_tools(),
        *sandbox_get_tools(),
        *scheduler_get_tools(),
        *sleep_get_tools(),
        *process_get_tools(),
        *todolist_get_tools(),
        *ask_get_tools(),
        *mcp_management_get_tools(),
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
        *image_get_all_tools(),
        *sandbox_get_all_tools(),
        *scheduler_get_all_tools(),
        *sleep_get_all_tools(),
        *process_get_all_tools(),
        *todolist_get_all_tools(),
        *ask_get_all_tools(),
        *mcp_management_get_all_tools(),
        *mcp_tools,
    ]
