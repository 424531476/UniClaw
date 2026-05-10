import json
import platform
import threading
from datetime import datetime
from pathlib import Path

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
        )

        return response.content
    except Exception as e:
        # 如果 AI 调用失败，返回错误信息
        return f"⚠️ 无法获取命令分析：{str(e)}"


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
