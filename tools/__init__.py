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
        *mcp_tools,
    ]
