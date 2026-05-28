import json
import platform
import random
import threading
from datetime import datetime
from pathlib import Path
from langchain_core.tools import tool


from tools.mcp.tools import mcp_list_servers
from tools.shell import Bash

# 无需权限提示即可安全运行的前缀
_SAFE_PREFIXES = (
    # 文件查看类
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "less",
    "more",
    # 路径与目录
    "pwd",
    "cd ",
    "dir ",
    # 输出与信息显示
    "echo",
    "printf",
    # 时间与日期
    "date",
    "time",
    # 命令查找与类型
    "which",
    "type",
    "where ",
    "command -v",
    # 环境变量
    "env",
    "printenv",
    "set",
    # 系统信息
    "uname",
    "hostname",
    "whoami",
    "id",
    "uptime",
    "w",
    # Git 只读操作
    "git log",
    "git status",
    "git diff",
    "git show",
    "git branch",
    "git remote",
    "git stash list",
    "git tag",
    "git reflog",
    "git blame",
    "git shortlog",
    "git describe",
    "git rev-parse",
    "git ls-files",
    "git ls-tree",
    # 文件搜索
    "find ",
    "grep ",
    "rg ",
    "ag ",
    "fd ",
    "locate ",
    # 编程语言解释器（仅执行，不包含危险参数）
    "python ",
    "python3 ",
    "node ",
    "ruby ",
    "perl ",
    # Python 包管理（只读）
    "pip show",
    "pip list",
    "pip freeze",
    "pip check",
    "pip index versions",
    "uv pip list",
    "uv pip show",
    # Node.js 包管理（只读）
    "npm list",
    "npm view",
    "npm info",
    "yarn list",
    "yarn info",
    # Rust 包管理（只读）
    "cargo metadata",
    "cargo tree",
    "cargo search",
    "cargo doc --no-deps",
    # 磁盘与文件系统
    "df ",
    "du ",
    "mount",
    "lsblk",
    # 内存与进程
    "free ",
    "top -bn",
    "ps ",
    "htop",
    # 网络诊断（只读）
    "ping -c",
    "ping -n",
    "curl -I",
    "curl --head",
    "curl -s",
    "wget -S",
    "wget --spider",
    "nslookup",
    "dig",
    "host",
    "traceroute",
    "tracert",
    "netstat -",
    "ss -",
    "ip addr",
    "ip route",
    "ifconfig",
    # 端口检查
    "lsof -i",
    "netstat -tlnp",
    # Docker 只读操作
    "docker ps",
    "docker images",
    "docker version",
    "docker info",
    "docker inspect",
    "docker logs",
    "docker stats --no-stream",
    # 服务状态
    "systemctl status",
    "systemctl list-units",
    "service --status-all",
    # 硬件信息
    "lscpu",
    "lsmem",
    "lsusb",
    "lspci",
    # 日志查看
    "journalctl --no-pager",
    "dmesg",
    # Windows 特定命令
    "tasklist",
    "wmic ",
    "systeminfo",
    "driverquery",
)


_CHAIN_OPERATORS = (";", "&&", "||", "|", "`", "$(", "\n")


def is_safe_tool(name: str) -> bool:
    """判断是否为安全工具（自动批准，无需用户确认）

    包括只读类工具和记忆/技能管理等安全的管理工具。
    通过导入工具函数并使用 .name 属性获取名称，避免硬编码字符串导致的大小写错误。

    Args:
        name: 工具名称

    Returns:
        bool: 如果是安全工具返回True,否则返回False
    """
    # 从各个模块导入安全工具函数
    from tools.fs import Read, Glob, ReadPDF
    from tools.shell import Grep, search_files_with_everything
    from tools.media import ReadMedia
    from tools.sandbox import RunCode
    from tools.web import webFetch, webSearch
    from tools.memory.tools import (
        memory_save,
        memory_delete,
        memory_list,
        memory_search,
    )
    from tools.scheduler.tools import (
        schedule_create,
        schedule_list,
        schedule_remove,
        schedule_toggle,
    )
    from tools.skill.tools import skill_suggest, skill_read
    from tools.sleep import sleep_timer
    from tools.plan import enter_plan_mode, exit_plan_mode
    from tools.process.tools import process_list, process_output, process_cleanup
    from tools.todolist import (
        todolist_create,
        todolist_update,
        todolist_clear,
        todolist_list,
        todolist_cancel,
    )
    from tools.ask import AskUserQuestion
    from tools.conversation.tools import conversation_list, conversation_detail
    from tools.hooks.tools import hook_read
    from tools.multi_agent.tools import (
        list_agent_tasks,
        check_agent_result,
        list_agent_definitions,
        agent_close,
    )
    from tools.computer_use import get_tools as cu_get_tools

    # 使用 .name 属性获取工具的实际名称,构建安全工具集合
    safe_tools = [
        Read.name,
        ReadPDF.name,
        ReadMedia.name,
        Glob.name,
        Grep.name,
        RunCode.name,
        webFetch.name,
        webSearch.name,
        memory_save.name,
        memory_delete.name,
        memory_list.name,
        memory_search.name,
        schedule_create.name,
        schedule_list.name,
        schedule_remove.name,
        schedule_toggle.name,
        skill_suggest.name,
        sleep_timer.name,
        enter_plan_mode.name,
        exit_plan_mode.name,
        process_list.name,
        process_output.name,
        process_cleanup.name,
        todolist_create.name,
        todolist_update.name,
        todolist_clear.name,
        todolist_list.name,
        todolist_cancel.name,
        AskUserQuestion.name,
        mcp_list_servers.name,
        conversation_list.name,
        conversation_detail.name,
        hook_read.name,
        read_llm_safe_prompt.name,
        list_agent_tasks.name,
        check_agent_result.name,
        agent_close.name,
        list_agent_definitions.name,
        search_files_with_everything.name,
        skill_read.name,
    ]
    for cu_tool in cu_get_tools():
        safe_tools.append(cu_tool.name)

    return name in safe_tools


def is_safe_bash(cmd: str) -> bool:
    """如果命令是只读的且从不需要权限提示，则返回 True。

    拒绝包含 shell 链式操作符（;、&&、||、|、反引号、$(…)）的命令
    — 这些可能在安全前缀后执行任意代码。
    """
    c = cmd.strip()

    # 先拒绝任何链接多个命令的危险操作符（最高优先级，不可被用户规则覆盖）
    if any(op in c for op in _CHAIN_OPERATORS):
        return False

    # 再检查用户自定义的持久化规则
    if check_saved_bash_rule(cmd):
        return True

    # 最后检查系统内置的安全前缀白名单
    return any(c.startswith(p) for p in _SAFE_PREFIXES)


def bash_desc(cmd: str, config) -> str:
    """
    获取命令的描述

    使用 AI 分析命令行参数的功能和潜在安全风险。

    Args:
        cmd: 要分析的命令行字符串
        config: 配置对象，包含模型参数等信息

    Returns:
        AI 生成的命令描述和安全风险评估文本
    """
    from llm import chat

    # 构建提示词
    system_prompt = """你是一个命令行安全分析专家。请分析用户提供的 shell 命令，并返回以下信息：

1. **命令功能**:简要说明这个命令的作用和预期效果
2. **安全风险评估**:评估执行此命令可能带来的安全风险（如文件修改、系统配置更改、数据泄露等）
3. **风险等级**:请给出一个 0 到 100 的整数评分,0 表示非常安全,100 表示非常危险

请以简洁清晰的中文回答，控制在 200 字以内。

# 环境
- 平台：{platform}
""".format(
        platform=platform.system()
    )
    user_prompt = f"请分析以下命令：\n``bash\n{cmd}\n```"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        # 调用 LLM 进行分析
        response = chat(
            messages=messages,
            model_name=config["mini_model_name"],
            enable_thinking=False,
            thinking=False,
        )

        return response.content
    except Exception as e:
        # 如果 AI 调用失败，返回错误信息
        return f"⚠️ 无法获取命令分析：{str(e)}"


def _llm_safe_prompt_path() -> Path:
    from context import get_app_dir, Scope

    return get_app_dir(Scope.PROJECT) / "llm_safe_prompt.json"


def _load_llm_safe_prompt() -> str:
    path = _llm_safe_prompt_path()
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("prompt", "").strip()
    except (json.JSONDecodeError, OSError):
        return ""


def _save_llm_safe_prompt(prompt: str):
    path = _llm_safe_prompt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"prompt": prompt}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _clear_llm_safe_prompt():
    path = _llm_safe_prompt_path()
    if path.exists():
        path.unlink()


@tool
def read_llm_safe_prompt() -> str:
    """读取当前安全策略注入提示词。

    读取存储的安全审核策略提示词。这个提示词会被自动注入到 LLM 的安全检测系统提示中，
    用于动态调整工具调用的安全审核规则。例如：可以在提示词中指定某些命令或工具的安全性，
    AI 会根据这个策略来判断是否需要用户确认。

    Returns:
        str: 当前存储的安全策略提示词内容，如果未设置则返回提示信息
    """
    prompt = _load_llm_safe_prompt()
    return prompt or "当前未设置 llm_safe_check 注入提示词。"


@tool
def write_llm_safe_prompt(prompt: str) -> str:
    """覆盖保存安全审核策略提示词。

    将新的安全策略提示词完整替换并保存。使用此工具时，旧的提示词会被完全覆盖。
    如果需要修改部分内容，建议使用 edit_llm_safe_prompt。

    Args:
        prompt (str): 完整的安全策略注入提示词文本

    Returns:
        str: 保存成功提示
    """
    _save_llm_safe_prompt(prompt)
    return "已保存 llm_safe_check 注入提示词。"


@tool
def edit_llm_safe_prompt(old_string: str, new_string: str) -> str:
    """精确编辑安全审核策略提示词中的特定部分。

    使用替换法修改安全策略提示词。找到 old_string 并替换为 new_string,
    适合对现有策略进行增量修改。例如：修改某条规则、添加新的安全策略、或调整现有的审核标准。

    与 write_llm_safe_prompt 的区别：
    - write: 完全覆盖整个提示词（破坏式操作）
    - edit: 只修改指定的部分（精确更新）

    Args:
        old_string (str): 要被替换的原始字符串。必须与提示词中的内容完全匹配，
                         包括空格和换行符。
        new_string (str): 用于替换的新字符串。

    Returns:
        str: 操作结果。成功时显示修改前后的预览；失败时返回错误信息。
    """
    try:
        # 读取当前提示词
        current_prompt = _load_llm_safe_prompt()

        # 验证旧字符串存在
        if old_string not in current_prompt:
            return "错误：在提示词中未找到 old_string。请确保完全匹配。"

        # 检查是否存在多个匹配
        count = current_prompt.count(old_string)
        if count > 1:
            return (
                f"错误: old_string 出现了 {count} 次。" "请提供更多上下文以使其唯一。"
            )

        # 执行替换
        new_prompt = current_prompt.replace(old_string, new_string, 1)

        # 保存并返回差异
        _save_llm_safe_prompt(new_prompt)

        # 生成简单的差异报告
        old_preview = old_string[:100] + ("..." if len(old_string) > 100 else "")
        new_preview = new_string[:100] + ("..." if len(new_string) > 100 else "")
        return f"已编辑 llm_safe_check 注入提示词：\n- 删除：{old_preview}\n+ 添加：{new_preview}"
    except Exception as e:
        return f"Error: {e}"


@tool
def clear_llm_safe_prompt() -> str:
    """清除所有存储的安全审核策略提示词。

    删除保存的安全策略，恢复到默认的安全审核规则。此后 llm_safe_check 将不再使用
    自定义的安全策略，仅使用内置的默认规则。

    Returns:
        str: 清除成功提示
    """
    _clear_llm_safe_prompt()
    return "已清除 llm_safe_check 注入提示词。"


# ── LLM 安全检测 ────────────────────────────────────────────

_tool_desc_map: dict[str, str] | None = None


def _get_tool_desc(name) -> dict[str, str]:
    """构建工具名 -> 工具描述的映射，用于 LLM 安全检测。"""
    global _tool_desc_map
    if _tool_desc_map is not None:
        desc = _tool_desc_map.get(name, None)
        if desc:
            return desc
        _tool_desc_map = None
    from tools import get_all_tools

    _tool_desc_map = {}
    for tool in get_all_tools():
        _tool_desc_map[tool.name] = tool.description or ""
    return _tool_desc_map.get(name, None)


def llm_safe_check(tc: dict, config: dict) -> tuple[bool, str]:
    """使用 LLM 进行工具调用安全审核（权限检查机制）。

    这是 UniClaw 的核心安全机制。当 AI 尝试执行一个不在白名单中的工具时，
    本函数会调用llm对该工具调用进行智能分析,判断是否安全。

    工作流程：
    1. 检查工具是否在 is_safe_tool() 白名单中
    2. 如果在白名单中：直接放行，无需检查
    3. 如果不在白名单中：
       a. 构建安全分析提示词（包含内置规则 + 用户自定义的注入策略）
       b. 调用llm分析该工具调用的功能和安全风险
       c. llm返回 {"is_safe": true/false, "explanation": "风险评估"}
       d. 如果 is_safe=true,自动执行:否则需要用户确认

    安全策略注入机制：
    - 注入提示词来自 read_llm_safe_prompt()，可通过 write/edit/clear 工具动态调整
    - 例如：管理员可以通过 edit_llm_safe_prompt 告诉 AI "允许所有 git 命令" 或 "禁止删除文件"
    - 这样 AI 在后续的安全审核中会遵循这些策略

    Args:
        tc (dict): 工具调用对象
            - name: 工具名称（如 "Edit", "Bash" 等）
            - args: 工具参数字典(如 {"command": "ls -la"})
        config (dict): 应用配置对象
            - mini_model_name: 用于安全分析的小模型名称(如 gpt-4-mini)

    Returns:
        tuple[bool, str]: (是否安全, 风险说明)
            - (True, explanation): 安全的工具调用，可自动执行
            - (False, explanation): 有安全风险，需要用户确认
            - (False, ""): LLM 调用失败，降级到需要用户确认
    """
    from llm import chat
    from console.ui import TUISpinner

    name = tc["name"]
    args = tc.get("args", {})
    tool_desc = _get_tool_desc(name)

    # 获取当前工作空间
    cwd = Path.cwd()
    extra = config.get("workspace", []) if config else []
    extra_text = ""
    if extra:
        extra.append(cwd)
        extra_lines = "\n".join(f"  - {d}" for d in extra)
        extra_text = f"- 当前空间目录:\n{extra_lines}\n"

    system_prompt = f"""你是一个工具调用安全分析专家。分析以下工具调用是否可以安全地自动执行（无需用户确认）。

# 分析方法
- **必须结合工具的函数描述和具体参数值进行综合判断**，不能仅凭工具名称或类型下结论
- 同一工具在不同参数下安全级别可能截然不同
- 对于 {Bash.name} 命令，必须逐个拆解命令、参数、管道和重定向，分析其完整语义
- 对于其他工具，必须检查参数值是否涉及敏感路径、敏感数据或高风险操作

# 当前环境
- 平台：{platform.system()}
- 当前目录：{cwd}
{extra_text}

安全的调用(is_safe=true):
- 只读操作（读取文件、搜索、列出内容）
- 无害操作（获取公开信息、搜索、时区查询）
- 不会修改系统状态或文件
- 不会泄露敏感数据
- 常规的功能性操作，不涉及安全风险
- 安装或启动软件，只要安装的内容和启动的程序本身是安全的（如通过 npm/pip/brew/apt/cargo 等包管理器安装主流软件包，或启动常见开发工具和服务）

不安全的调用(is_safe=false):
- 修改、删除、覆盖文件
- 执行危险的 shell 命令
- 访问凭据或密钥
- 向非公开端点发送请求
- 修改系统配置
- 可能造成不可逆变更

explanation 要求:
- 如果是 Bash/Shell 命令:拆解命令各部分,解释每个参数和管道的作用,说明整体功能和潜在风险
- 如果是其他工具:说明工具的功能和具体操作内容
- 判定为不安全时,必须清楚说明有哪些危害
- 风险评分:请给出一个 0 到 100 的整数评分,0 表示非常安全,100 表示非常危险

只返回 JSON,不要用 markdown 包裹:
{{"is_safe": true/false,  "explanation": "简要中文解释"}}"""
    injected_prompt = _load_llm_safe_prompt()
    if injected_prompt:
        system_prompt += f"\n\n# ⚠️ 用户自定义安全策略（最高优先级）\n以下是由用户主动配置的安全审核规则,必须严格遵守。当用户策略与默认规则冲突时,以用户策略为准：\n{injected_prompt}"

    if name == Bash.name:
        command = args.get("command", "")
        user_prompt = f"工具: {Bash.name} (Shell 命令)\n命令: {command}"
    else:
        user_prompt = f"工具: {name}\n工具描述: {tool_desc}\n参数:\n{json.dumps(args, indent=2, ensure_ascii=False)}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    wait_id = TUISpinner.start(f"Checking {name} safety...")
    try:
        response = chat(
            messages=messages,
            model_name=config["mini_model_name"],
            temperature=0,
            max_tokens=5000,
            enable_thinking=False,
            thinking=False,
        )
        result = json.loads(response.content)
        return (bool(result.get("is_safe", False)), result.get("explanation", ""))
    except Exception:
        return (False, "")
    finally:
        TUISpinner.stop(wait_id=wait_id)


# ── 持久化权限规则 ──────────────────────────────────────────

_RULES_LOCK = threading.Lock()

_COMPOUND_PREFIXES = {
    "git",
    "npm",
    "yarn",
    "pip",
    "uv",
    "cargo",
    "docker",
    "systemctl",
    "npx",
}


def _rules_path() -> Path:
    from context import get_app_dir, Scope

    return get_app_dir(Scope.PROJECT) / "permission_rules.json"


def _load_rules() -> list:
    path = _rules_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("rules", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save_rules(rules: list):
    path = _rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"rules": rules}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def extract_bash_prefix(command: str) -> str:
    parts = command.strip().split()
    if not parts:
        return ""
    if parts[0] in _COMPOUND_PREFIXES and len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return parts[0]


def add_permission_rule(rule_type: str, pattern: str):
    with _RULES_LOCK:
        rules = _load_rules()
        if any(r["type"] == rule_type and r["pattern"] == pattern for r in rules):
            return
        rules.append(
            {
                "type": rule_type,
                "pattern": pattern,
                "created": datetime.now().isoformat(timespec="seconds"),
            }
        )
        _save_rules(rules)


def remove_permission_rule(rule_type: str, pattern: str) -> bool:
    with _RULES_LOCK:
        rules = _load_rules()
        new_rules = [
            r for r in rules if not (r["type"] == rule_type and r["pattern"] == pattern)
        ]
        if len(new_rules) == len(rules):
            return False
        _save_rules(new_rules)
        return True


def list_permission_rules() -> list:
    return _load_rules()


def check_saved_bash_rule(command: str) -> bool:
    """检查Bash命令是否匹配用户定义的持久化规则

    Args:
        command: Bash命令字符串

    Returns:
        bool: 如果命令匹配已保存的bash规则则返回True
    """
    rules = _load_rules()
    command = command.strip()
    return any(r["type"] == "bash" and command.startswith(r["pattern"]) for r in rules)


def check_saved_tool_rule(tool_name: str) -> bool:
    """检查工具名称是否匹配用户定义的持久化规则

    Args:
        tool_name: 工具名称（如 "Write", "Read", "Edit" 等）

    Returns:
        bool: 如果工具名称匹配已保存的tool规则则返回True
    """
    rules = _load_rules()
    return any(r["type"] == "tool" and r["pattern"] == tool_name for r in rules)


def get_tools() -> list:
    """获取安全管理工具列表"""
    return [
        read_llm_safe_prompt,
        write_llm_safe_prompt,
        edit_llm_safe_prompt,
        clear_llm_safe_prompt,
    ]


def get_all_tools() -> list:
    """获取所有安全管理工具"""
    return [
        read_llm_safe_prompt,
        write_llm_safe_prompt,
        edit_llm_safe_prompt,
        clear_llm_safe_prompt,
    ]
