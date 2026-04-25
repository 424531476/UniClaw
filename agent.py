from enum import Enum
import time
from typing import Optional
from llm import stream
from tools import tools
from dataclasses import dataclass, field
from context import build_system_prompt
from config import Permissions, get_config
from tools.security import bash_desc
from utils.truncation import truncate_text_by_lines


class MessageRole(Enum):
    """
    消息角色枚举

    定义了对话中不同角色的类型:
        SYSTEM: 系统消息，用于设置助手的行为和背景
        USER: 用户消息，表示用户输入的内容
        ASSISTANT: 助手消息，表示助手的回复
        TOOL: 工具消息，表示工具调用的结果
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class AgentState:
    """可变会话状态。messages 使用与提供商无关的中立格式。"""

    messages: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    turn_count: int = 0


@dataclass
class TextChunkEvent:
    content: str


@dataclass
class ThinkingChunkEvent:
    def __init__(self, content):
        self.content = content


@dataclass
class ThinkingStartEvent:
    pass


@dataclass
class AssistantEvent:
    content: str
    tool_calls: list
    in_tokens: int = 0
    out_tokens: int = 0
    model_name: str = ""


@dataclass
class TooStartlEvent:
    name: str
    args: dict


@dataclass
class ToolEvent:
    name: str
    content: str
    tool_call_id: str


@dataclass
class PermissionRequestEvent:
    description: str
    granted: bool = False


def _check_permission(tc: dict, config: dict) -> bool:
    """如果操作是自动批准的（无需询问用户），则返回 True。"""
    perm_mode = config.get("permission_mode", "auto")
    name = tc["name"]

    # 计划模式工具始终自动批准
    if name in ("EnterPlanMode", "ExitPlanMode"):
        return True

    if perm_mode == Permissions.ACCEPT_ALL:
        return True
    if perm_mode == Permissions.MANUAL:
        return False  # 始终询问

    if perm_mode == Permissions.PLAN:
        # todo: 添加计划模式
        return False

    # "auto" 模式：仅对写入和不安全的 bash 命令询问
    if name in ("Read", "Glob", "Grep", "WebFetch", "WebSearch"):
        return True
    if name == "Bash":
        from tools import is_safe_bash

        return is_safe_bash(tc["args"].get("command", ""))
    return False  # Write, Edit → 询问


def _permission_desc(tc: dict, config: dict) -> str:
    """生成权限请求的美观描述信息
    
    Args:
        tc: 工具调用字典，包含工具名称和参数
        config: 配置字典
        
    Returns:
        格式化的权限请求描述字符串
    """
    name = tc["name"]
    inp = tc["args"]
    
    # Bash 命令执行
    if name == "Bash":
        command = inp.get('command', '')
        desc_lines = [
            f"🖥️  运行 Shell 命令:",
            f"   {command}"
        ]
        bash_info = bash_desc(command, config)
        if bash_info:
            desc_lines.append(f"   {bash_info}")
        return "\n".join(desc_lines)
    
    # 文件写入操作
    if name == "Write":
        file_path = inp.get('file_path', '')
        return f"📝 写入文件:\n   {file_path}"
    
    # 文件编辑操作
    if name == "Edit":
        file_path = inp.get('file_path', '')
        return f"✏️  编辑文件:\n   {file_path}"
    
    # 其他工具调用
    return f"🔧 调用工具: {name}\n   参数: {list(inp.values())[:1]}"

def run(
    user_message: str,
    system_message: Optional[str] = None,
    state: Optional[AgentState] = None,
    config: Optional[dict] = None,
):
    if state is None:
        state = AgentState()
    if config is None:
        config = get_config().to_dict()
    if system_message is None:
        system_message = build_system_prompt()
    name2tool = {tool.name: tool for tool in tools}
    state.messages.append({"role": MessageRole.USER.value, "content": user_message})
    from compaction import maybe_compact

    while True:
        yield ThinkingStartEvent()

        maybe_compact(state, config=config)
        messages = [
            {"role": MessageRole.SYSTEM.value, "content": system_message},
            *state.messages,
        ]
        for i in range(3):
            try:
                resp = None
                for chunk in stream(
                    messages=messages,
                    model_name=config["model_name"],
                    temperature=config["temperature"],
                    max_tokens=config["max_tokens"],
                    top_p=config["top_p"],
                    tools=tools,
                ):
                    if resp is None:
                        resp = chunk
                    else:
                        resp += chunk
                    if chunk.content:
                        yield TextChunkEvent(chunk.content)
                break
            except Exception as e:
                yield TextChunkEvent(f"\n⚠️ 命令执行失败：{str(e)}\n1秒后重试\n")
                time.sleep(1)
        else:
            break
        state.messages.append(
            {
                "role": MessageRole.ASSISTANT.value,
                "content": resp.content if resp.content else "",
                "tool_calls": resp.tool_calls,
            }
        )

        usage_meta = getattr(resp, "usage_metadata", None) or {}
        actual_model = resp.response_metadata.get("model_name", config["model_name"]) if hasattr(resp, 'response_metadata') else config["model_name"]
        yield AssistantEvent(
            content=resp.content,
            tool_calls=resp.tool_calls,
            in_tokens=usage_meta.get("input_tokens", 0),
            out_tokens=usage_meta.get("output_tokens", 0),
            model_name=actual_model
        )
        if len(resp.tool_calls) == 0:
            break
        for tool_call in resp.tool_calls:
            tool = name2tool[tool_call["name"]]
            permitted = _check_permission(tool_call, config)
            if not permitted:
                req = PermissionRequestEvent(
                    description=_permission_desc(tool_call, config=config)
                )
                yield req
                permitted = req.granted
            if permitted:
                yield TooStartlEvent(tool_call["name"], tool_call["args"])
                try:
                    tool_resp = tool.invoke(tool_call)
                    tool_resp_content = tool_resp.content
                except Exception as e:
                    tool_resp_content = f"工具调用失败: {e}"
            else:
                tool_resp_content = "用户拒绝执行"
            yield ToolEvent(
                tool.name,
                tool_call_id=tool_call["id"],
                content=truncate_text_by_lines(
                    tool_resp_content, max_chars=2000, keep_ratio=0.8
                ),
            )

            state.messages.append(
                {
                    "role": MessageRole.TOOL.value,
                    "name": tool_call["name"],
                    "content": tool_resp.content,
                    "tool_call_id": tool_call["id"],
                }
            )
