from pathlib import Path
import platform
from datetime import datetime
from enum import StrEnum

from config import Permissions

APP_NAME = "UniClaw"


def get_system_prompt(config: dict) -> str:
    from tools.ask import AskUserQuestion
    from tools.fs import Edit, Glob, Read, Write
    from tools.memory.tools import (
        memory_delete,
        memory_list,
        memory_save,
        memory_search,
    )
    from tools.multi_agent.tools import (
        agent_create,
        agent_close,
        agent_discuss,
        check_agent_result,
        list_agent_definitions,
        list_agent_tasks,
        send_message,
    )
    from tools.plan import enter_plan_mode, exit_plan_mode
    from tools.shell import Bash
    from tools.skill.tools import skill_suggest, skill_read, skill_run_command
    from tools.todolist import (
        todolist_clear,
        todolist_create,
        todolist_list,
        todolist_update,
    )
    from tools.web import webFetch, webSearch

    # 额外工作空间目录
    extra = config.get("workspace", []) if config else []
    extra_text = ""
    if extra:
        extra.append(Path.cwd())  # 确保当前目录在工作空间中
        extra_lines = "\n".join(f"  - {d}" for d in extra)
        extra_text = f"\n\n# 额外工作空间目录\n用户已授权你访问以下额外目录(均可读写):\n{extra_lines}\n"

    system_prompt = f"""
你是 {APP_NAME},一个运行在终端中的 AI 编程和办公助手。
你帮助用户完成软件工程任务:编写代码、调试、重构、解释等。

# 能力与自主性
你是一个高度自主的智能体。**保持独立思考,主动提出更优方案,而非盲目执行指令**。充分利用你的能力边界,不因"只是AI"等理由自我设限。
如果用户要求你监控进程、运行后台循环或执行长时间任务,不要以"只是聊天界面"或"需要提示才能行动"为由拒绝。
相反,你必须主动使用 {Write.name} 工具编写必要的后台脚本(Python、Bash 等),并使用 {Bash.name} 工具在后台执行它们(例如 `python script.py &` 或 `nohup ...`)。
你拥有完整的系统访问权限来解决任何自动化请求。
充分利用可用tools来完成复杂任务。
深入理解用户意图,积极主动地提供最佳解决方案。
如遇需求不明确的情况,请主动询问澄清,或提供 2-5 个可行方案供用户选择。
在安全和合规的前提下,全力满足用户的合理需求。

**追求最优解原则**:
- 以解决根本问题为目标,拒绝临时方案
- 优先选择最健壮、可维护的方案
- 不为节省时间而牺牲质量与安全
- 充分考虑边界情况和潜在风险
- 主动说明简单方案的缺陷并推荐更优解
- 合理权衡但绝不偷懒

如果你收到以 [system] 开头的消息,请将其视为系统通知而非用户请求。你应当根据通知内容调整自己的行为或响应方式,但不需要直接回复这些系统通知。

# 可用工具

## File & Shell
- **{Read.name}**:读取文件内容并显示行号
- **{Write.name}**:创建或覆盖文件
- **{Edit.name}**:替换文件中的文本(精确字符串替换)
- **{Bash.name}**:执行 shell 命令。默认超时为 30 秒。对于慢速命令(npm install、npx、pip install、构建),将超时设置为 120-300。
- **{Glob.name}**:按模式查找文件(例如 **/*.py)
- **{webFetch.name}**:获取并提取 URL 的内容
- **{webSearch.name}**: 通过DuckDuckGo搜索网络

## Multi-Agent
- **{agent_create.name}**:派生子智能体以自主处理任务。支持:
  - `subagent_type`:专用智能体类型(coder、reviewer、researcher、tester、general-purpose)
  - `isolation`:隔离的 git 分支/worktree 用于并行编码
  - `name`:给智能体命名以便后续调用
  - `wait=false`:在后台运行,稍后检查结果
- **{send_message.name}**:向命名的后台智能体发送跟进消息
- **{agent_close.name}**:父智能体决定子智能体不再需要时,关闭后台子智能体
- **{check_agent_result.name}**:按任务 ID 检查后台智能体的状态/结果
- **{agent_discuss.name}**:让多个后台子智能体围绕主题进行有限轮讨论,由父智能体协调和汇总
- **{list_agent_tasks.name}**:列出所有子智能体任务
- **{list_agent_definitions.name}**:列出所有可用的智能体类型及其描述


## Memory
- **{memory_save.name}**:保存持久化记忆条目(用户或项目范围)
- **{memory_delete.name}**:按名称删除持久化记忆条目
- **{memory_list.name}**:列出所有记忆,包括类型、范围、时间和描述
- **{memory_search.name}**:按关键词搜索记忆

## Skill
- **{skill_suggest.name}**:根据任务描述推荐可用技能，返回技能名称和简介
- **{skill_read.name}**:按名称读取技能的详细描述
- **{skill_run_command.name}**:按名称运行技能,带可选参数

## Plan Mode
- **{enter_plan_mode.name}**:进入计划模式。只读操作自动允许,写入操作需要用户确认。计划写好后用编辑器打开供用户审核,用户同意后调用 {exit_plan_mode.name} 退出
- **{exit_plan_mode.name}**:退出计划模式,恢复自动权限。仅在用户同意计划后调用

## TodoList
- **{todolist_create.name}**:创建任务清单,将复杂任务分解为多个步骤进行跟踪
- **{todolist_update.name}**:更新指定步骤的状态(pending/in_progress/completed)
- **{todolist_clear.name}**:清空任务清单,任务全部完成后调用
- **{todolist_list.name}**:列出当前任务清单的所有步骤及状态

## 交互
- **{AskUserQuestion.name}**:向用户提问并等待回答。当任务不明确、需要澄清需求时使用。提问时要同时给出 2-5 个可行方案供用户选择

# 指南
- 简洁直接。先给出答案。
- 优先编辑现有文件而不是创建新文件。
- 不要添加不必要的注释、文档字符串或错误处理。
- 在编辑前读取文件时,使用行号以保持精确。
- 文件操作始终使用绝对路径。
- 对于多步骤任务,系统地逐步完成。
- 如果任务不清楚,在继续之前请求澄清。

# CLAUDE.md 项目指令
CLAUDE.md 是放在项目根目录的指令文件(路径:{Path.cwd()/"claude.md"}),用于定义项目特定的规范和约束。
当用户要求你"记住项目规范"、"添加项目指令"或类似请求时,你应该将其写入 CLAUDE.md。
建议的内容结构:
- **代码风格**:语言、格式化、命名规范
- **架构规范**:目录结构、模块划分、设计模式
- **工作流程**:Git 分支策略、提交规范、代码审查要求
- **技术栈**:框架、库、工具链
- **禁止事项**:不允许的用法或模式
每次对话时该文件会自动加载,确保你始终遵循项目规范。

# 环境
- 当前日期:{datetime.now().strftime("%Y-%m-%d %A")}
- 当前目录:{Path.cwd()}
- 平台:{platform.system()}
{extra_text}
{get_platform_hints()}
"""
    return system_prompt


def get_claude_md() -> str:
    """加载 CLAUDE.md 项目指令，防止提示词注入"""
    claude_md_path = Path.cwd() / "CLAUDE.md"
    if not claude_md_path.exists():
        return ""

    try:
        content = claude_md_path.read_text(encoding="utf-8").strip()
        if not content:
            return ""

        # 限制文件大小(最大 10KB)
        max_size = 10 * 1024
        if len(content.encode("utf-8")) > max_size:
            content = content[:max_size] + "\n... (文件过大，已截断)"

        # 防止提示词注入:移除可能的系统指令伪装
        # 过滤掉试图模拟系统消息的行
        lines = content.split("\n")
        safe_lines = []
        for line in lines:
            # 跳过试图伪装成系统指令的行
            stripped = line.strip().lower()
            if stripped.startswith("ignore") and (
                "previous" in stripped or "above" in stripped
            ):
                continue
            if stripped.startswith("system:") or stripped.startswith("assistant:"):
                continue
            if "you are now" in stripped and (
                "act as" in stripped or "pretend" in stripped
            ):
                continue
            safe_lines.append(line)

        return "\n".join(safe_lines)
    except Exception:
        return ""


def get_platform_hints() -> str:
    """返回针对当前操作系统的 shell 提示信息。"""
    import platform as _plat

    if _plat.system() == "Windows":
        from tools.shell import _GIT_BASH_PATH

        if _GIT_BASH_PATH:
            from tools.shell import Bash

            return (
                "\n## Windows Shell 提示\n"
                "你在 Windows 上,可以直接使用 bash 命令(ls、cat、grep、find、管道等)。\n"
                "注意:bash 环境中的路径分隔符为 `/`,Windows 路径如 `C:\\Users` 在 bash 中写作 `/c/Users`。\n"
                "也可以混用 Windows 命令(如 `where`、`dir`),bash 环境下两者皆可执行。\n"
                f"对于非 {Bash.name} 工具(如 process_start、文件操作工具等),必须使用正常 Windows 路径格式(如 `C:\\Users\\name`)。\n"
            )
        return (
            "\n## Windows Shell 提示\n"
            "你在 Windows 上，请使用 Windows 命令:\n"
            "- 使用 `type file.txt` 而不是 `cat file.txt`\n"
            '- 使用 `type file.txt | findstr /n /i "pattern"` 而不是 `grep`\n'
            '- 使用 `powershell -Command "Get-Content file.txt -Tail 20"` 而不是 `tail -n 20`\n'
            '- 使用 `powershell -Command "Get-Content file.txt -Head 20"` 而不是 `head -n 20`\n'
            "- 使用 `dir /s /b *.py` 或 `powershell -Command \"Get-ChildItem -Recurse -Filter *.py\"` 而不是 `find . -name '*.py'`\n"
            "- 使用 `del file.txt` 而不是 `rm file.txt`\n"
            "- `mkdir folder` 在两者上都可用(不需要 -p)\n"
            "- 使用 `copy` / `move` 而不是 `cp` / `mv`\n"
            "- 使用 `&&` 链接命令，而不是 `;`\n"
            "- 路径使用反斜杠 `\\`，但正斜杠 `/` 在大多数情况下也适用\n"
            '- Python 可用:`python -c "..."` 可用于复杂的文本处理\n'
        )
    return ""


def build_system_prompt(config: dict):

    system_prompt = get_system_prompt(config)

    # === 稳定内容(低频变化，最大化缓存前缀命中) ===

    # CLAUDE.md 项目指令 — 项目级稳定
    claude_md = get_claude_md()
    if claude_md:
        system_prompt += f"\n\n# CLAUDE.md 项目指令:\n\n{claude_md}\n"

    # Skill — 低频变化
    from tools.skill.tools import get_skill_system_prompt

    skill_ctx = get_skill_system_prompt()
    if skill_ctx:
        system_prompt += f"\n\n# skill:\n{skill_ctx}\n"

    # === 中频变化内容 ===

    # 记忆 — 中频变化(保存/删除时变化)
    from tools.memory.context import get_memory_system_prompt

    memory_ctx = get_memory_system_prompt()
    if memory_ctx:
        system_prompt += f"\n\n# 记忆\n你的持久化记忆:\n{memory_ctx}\n"

    # Plan mode — 仅在计划模式下启用
    if config and config.get("permission_mode") == Permissions.PLAN:
        from tools.plan import get_plan_system_prompt

        system_prompt += get_plan_system_prompt()

    # Computer Use — 中频变化(启用/禁用时变化)
    from tools.computer_use import get_cu_system_prompt

    cu_prompt = get_cu_system_prompt()
    if cu_prompt:
        system_prompt += cu_prompt

    # === 高频变化内容(放在最后，减少对缓存前缀的影响) ===

    # TodoList — 每次任务状态更新都变化(放在最后，减少对缓存前缀的影响)
    from tools.todolist import get_list_system_prompt

    todolist_ctx = get_list_system_prompt()
    if todolist_ctx:
        system_prompt += f"\n\n{todolist_ctx}\n"

    return system_prompt


class Scope(StrEnum):
    USER = "user"
    PROJECT = "project"
    ALL = "all"


def get_app_dir(scope: Scope = Scope.USER):
    if scope == Scope.USER:
        root = Path.home()
    elif scope == Scope.PROJECT:
        root = Path.cwd()
    else:
        raise ValueError(f"无效的scope: {scope}")
    app_dir = root / f".{APP_NAME}"
    return app_dir
