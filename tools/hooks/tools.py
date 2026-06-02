from langchain_core.tools import tool

from context import Scope
from tools.hooks.hook_manager import (
    add_hook,
    remove_hook,
    load_all_hooks_configs,
)


# ── 系统提示词(静态常量,最大化 LLM 缓存命中) ──────────────

_HOOKS_SYSTEM_PROMPT = """\
# Hook 机制
Hook 是在特定事件触发时自动执行的 shell 命令,可用于工具调用前后的自动化检查、阻止危险操作、会话生命周期管理等。\
你可以通过 {read}、{add}、{remove} 工具管理 hook。\
可用事件:SessionStart、SessionEnd、PreToolUse(非零退出码阻止调用)、PostToolUse、PermissionRequest(非零退出码拒绝)、PermissionResponse。
"""


def get_hooks_system_prompt() -> str:
    """返回 Hook 机制的系统提示词(静态内容,适合放在缓存前缀区域)。"""
    return _HOOKS_SYSTEM_PROMPT.format(
        read=hook_read.name,
        add=hook_add.name,
        remove=hook_remove.name,
    )


@tool
def hook_read() -> str:
    """
    读取全部 hooks 配置。Hook 是在特定事件触发时自动执行的 shell 命令。
    输出先项目级后用户级,每个 hook 显示 id、名称、事件、匹配器和命令。
    """
    lines = []
    for scope, config in load_all_hooks_configs():
        lines.append(f"=== {scope} 级 hooks ===")
        hooks = config.get("hooks", {})
        found = False
        for event, entries in hooks.items():
            for entry in entries:
                found = True
                entry_id = entry.get("id", "")
                name = entry.get("name", "")
                matcher = entry.get("matcher") or "*"
                commands = [h["command"] for h in entry.get("hooks", [])]
                label = f"[{entry_id}]"
                if name:
                    label += f" {name}"
                lines.append(f"  {label} event={event} matcher={matcher}")
                for cmd in commands:
                    lines.append(f"    -> {cmd}")
        if not found:
            lines.append("  (无)")
    return "\n".join(lines)


@tool
def hook_add(
    event: str,
    commands: str,
    name: str = "",
    matcher: str = "",
    scope: Scope = Scope.PROJECT,
) -> str:
    """
    添加单条 hook。Hook 是在特定事件触发时自动执行的 shell 命令,可用于:
    - 工具调用前/后的自动化检查或日志记录
    - 阻止危险操作(PreToolUse 非零退出码会阻止工具执行)
    - 会话生命周期的初始化或清理
    支持多个命令按顺序执行。

    event: 触发事件,可选值:
        - SessionStart: 会话启动时触发
        - SessionEnd: 会话结束时触发
        - PreToolUse: 工具调用前触发(可阻止调用,非零退出码会阻止)
        - PostToolUse: 工具调用后触发
        - PermissionRequest: 权限请求时触发(可阻止,非零退出码拒绝权限)
        - PermissionResponse: 权限响应后触发
    commands: 要执行的 shell 命令,多个命令用换行分隔(如 "echo step1\\necho step2")。
    name: 可选的人类可读名称(如 "block-rm"),便于后续按名删除。
    matcher: 可选的工具名匹配器,支持通配符(*,?)和多模式(|或,分隔)。如 "Bash","Read|Write","*Tool*"。不指定则匹配所有。
    scope: 'project'(项目级)或 'user'(用户级)。
    """
    cmd_list = [c.strip() for c in commands.strip().split("\n") if c.strip()]
    new_id = add_hook(
        event=event,
        commands=cmd_list,
        name=name or None,
        matcher=matcher or None,
        scope=scope,
    )
    label = f"[{new_id}]"
    if name:
        label += f" {name}"
    return f"已添加 hook {label},事件={event},命令数={len(cmd_list)}"


@tool
def hook_remove(id_or_name: str) -> str:
    """
    删除单条 hook。Hook 是在特定事件触发时自动执行的 shell 命令。
    根据 id 或 name 删除,自动搜索项目级和用户级配置。

    id_or_name: hook 的 id(如 "a3f8c2")或 name(如 "block-rm")。
    """
    removed = remove_hook(id_or_name)
    if removed:
        return f"已删除 hook: {id_or_name}"
    return f"未找到 hook: {id_or_name}"


def get_tools() -> list:
    return [hook_read, hook_add, hook_remove]


def get_all_tools() -> list:
    return [hook_read, hook_add, hook_remove]
