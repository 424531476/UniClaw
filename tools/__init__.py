from .fs import tools as fs_tools
from .multi_agent.tools import tools as multi_agent_tools
from .plan import tools as plan_tools
from .shell import tools as shell_tools
from .skill.tools import tools as skill_tools
from .web import tools as web_tools
from .memory.tools import tools as memory_tools
from .security import is_safe_bash
from .mcp import MCPManager


def get_tools() -> list:
    """获取所有可用工具（包括 MCP 工具）"""
    mcp_manager = MCPManager.get_instance()
    mcp_tools = mcp_manager.get_mcp_tools()
    return [
        *fs_tools,
        *multi_agent_tools,
        *plan_tools,
        *shell_tools,
        *skill_tools,
        *web_tools,
        *memory_tools,
        *mcp_tools,
    ]
