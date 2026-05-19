import json
import platform
import threading
from datetime import datetime
from pathlib import Path

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
        bool: 如果是安全工具返回True，否则返回False
    """
    # 从各个模块导入安全工具函数
    from tools.fs import Read, Glob
    from tools.shell import Grep
    from tools.image import ReadImage
    from tools.sandbox import RunCode
    from tools.web import webfetch, websearch
    from tools.memory.tools import memory_save, memory_delete, memory_list, memory_search
    from tools.scheduler import schedule_create, schedule_list, schedule_remove, schedule_toggle
    from tools.skill.tools import skill_list
    from tools.sleep import sleep_timer
    from tools.plan import enter_plan_mode, exit_plan_mode
    from tools.process.tools import process_list, process_output
    from tools.todolist import todolist_create, todolist_update, todolist_clear, todolist_list
    from tools.ask import ask_user

    # 使用 .name 属性获取工具的实际名称，构建安全工具集合
    safe_tools = {
        Read.name,
        ReadImage.name,
        Glob.name,
        Grep.name,
        RunCode.name,
        webfetch.name,
        websearch.name,
        memory_save.name,
        memory_delete.name,
        memory_list.name,
        memory_search.name,
        schedule_create.name,
        schedule_list.name,
        schedule_remove.name,
        schedule_toggle.name,
        skill_list.name,
        sleep_timer.name,
        enter_plan_mode.name,
        exit_plan_mode.name,
        process_list.name,
        process_output.name,
        todolist_create.name,
        todolist_update.name,
        todolist_clear.name,
        todolist_list.name,
        ask_user.name,
    }
    
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

1. **命令功能**：简要说明这个命令的作用和预期效果
2. **安全风险评估**：评估执行此命令可能带来的安全风险（如文件修改、系统配置更改、数据泄露等）
3. **风险等级**：给出风险等级（低/中/高）

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


# ── LLM 安全检测 ────────────────────────────────────────────

_tool_desc_map: dict[str, str] | None = None


def _get_tool_desc_map() -> dict[str, str]:
    """构建工具名 -> 工具描述的映射，用于 LLM 安全检测。"""
    global _tool_desc_map
    if _tool_desc_map is not None:
        return _tool_desc_map
    from tools import get_all_tools

    _tool_desc_map = {}
    for tool in get_all_tools():
        _tool_desc_map[tool.name] = tool.description or ""
    return _tool_desc_map


def llm_safe_check(tc: dict, config: dict) -> tuple[bool, str]:
    """使用 LLM 检测工具调用是否安全。

    当工具不在安全白名单中时，调用小模型分析工具调用的安全性。
    返回 (is_safe, explanation) 元组。

    Args:
        tc: 工具调用字典，包含 name 和 args
        config: 配置字典，需要包含 mini_model_name

    Returns:
        tuple[bool, str]: (是否安全, 解释文本)
        当 LLM 调用失败时返回 (False, "")，降级到需要用户确认
    """
    from llm import chat
    from console.ui import TUISpinner

    name = tc["name"]
    args = tc.get("args", {})
    desc_map = _get_tool_desc_map()
    tool_desc = desc_map.get(name, "未知工具")

    system_prompt = """你是一个工具调用安全分析专家。分析以下工具调用是否可以安全地自动执行（无需用户确认）。

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

explanation 要求：
- 如果是 Bash/Shell 命令：拆解命令各部分，解释每个参数和管道的作用，说明整体功能和潜在风险
- 如果是其他工具：说明工具的功能和具体操作内容
- 判定为不安全时，必须清楚说明有哪些危害

只返回 JSON,不要用 markdown 包裹：
{{"is_safe": true/false, "explanation": "简要中文解释"}}"""

    if name == Bash.name:
        command = args.get("command", "")
        user_prompt = f"工具: {Bash.name} (Shell 命令)\n命令: {command}\n\n平台: {platform.system()}"
    else:
        user_prompt = f"工具: {name}\n工具描述: {tool_desc}\n参数:\n{json.dumps(args, indent=2, ensure_ascii=False)}\n\n平台: {platform.system()}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    TUISpinner.start("Checking safety...")
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
        TUISpinner.stop()


# ── 持久化权限规则 ──────────────────────────────────────────

_RULES_LOCK = threading.Lock()

_COMPOUND_PREFIXES = {"git", "npm", "yarn", "pip", "uv", "cargo", "docker", "systemctl", "npx"}


def _rules_path() -> Path:
    from context import get_app_dir, Scope

    return get_app_dir(Scope.PROJECT.value) / "permission_rules.json"


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
    path.write_text(json.dumps({"rules": rules}, ensure_ascii=False, indent=2), encoding="utf-8")


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
        rules.append({
            "type": rule_type,
            "pattern": pattern,
            "created": datetime.now().isoformat(timespec="seconds"),
        })
        _save_rules(rules)


def remove_permission_rule(rule_type: str, pattern: str) -> bool:
    with _RULES_LOCK:
        rules = _load_rules()
        new_rules = [r for r in rules if not (r["type"] == rule_type and r["pattern"] == pattern)]
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
    return any(
        r["type"] == "bash" and command.startswith(r["pattern"])
        for r in rules
    )


def check_saved_tool_rule(tool_name: str) -> bool:
    """检查工具名称是否匹配用户定义的持久化规则
    
    Args:
        tool_name: 工具名称（如 "Write", "Read", "Edit" 等）
        
    Returns:
        bool: 如果工具名称匹配已保存的tool规则则返回True
    """
    rules = _load_rules()
    return any(r["type"] == "tool" and r["pattern"] == tool_name for r in rules)
