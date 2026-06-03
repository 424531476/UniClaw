from typing import Union

from agent import AgentTask
from tools.skill.executor import run_skill
from commands.session import cmd_compact, cmd_clear, cmd_export
from commands.model import cmd_model
from commands.system import cmd_cwd, cmd_skills, cmd_exit, cmd_usage, cmd_help
from commands.context_usage import cmd_context
from commands.memory import cmd_memory
from commands.mcp import cmd_mcp
from commands.schedule import cmd_schedule
from commands.permissions import cmd_permissions
from commands.init import cmd_init
from commands.add_dir import cmd_add_dir
from commands.resume import cmd_resume
from commands.cost import cmd_cost
from commands.doctor import cmd_doctor
from commands.task import cmd_task
from commands.btw import cmd_btw

COMMANDS = dict()
COMMANDS["clear"] = cmd_clear
COMMANDS["cls"] = cmd_clear
COMMANDS["compact"] = cmd_compact
COMMANDS["model"] = cmd_model
COMMANDS["cwd"] = cmd_cwd
COMMANDS["pwd"] = cmd_cwd
COMMANDS["cd"] = cmd_cwd
COMMANDS["skills"] = cmd_skills
COMMANDS["exit"] = cmd_exit
COMMANDS["quit"] = cmd_exit
COMMANDS["export"] = cmd_export
COMMANDS["memory"] = cmd_memory
COMMANDS["mcp"] = cmd_mcp
COMMANDS["usage"] = cmd_usage
COMMANDS["context"] = cmd_context
COMMANDS["schedule"] = cmd_schedule
COMMANDS["permissions"] = cmd_permissions
COMMANDS["help"] = cmd_help
COMMANDS["init"] = cmd_init
COMMANDS["add_dir"] = cmd_add_dir
COMMANDS["add-dir"] = cmd_add_dir
COMMANDS["resume"] = cmd_resume
COMMANDS["cost"] = cmd_cost
COMMANDS["doctor"] = cmd_doctor
COMMANDS["task"] = cmd_task
COMMANDS["btw"] = cmd_btw


def handle_slash(line: str, task: AgentTask, config: dict) -> Union[bool, str]:
    """处理 /command [args]。如果已处理则返回True,技能匹配时返回元组(skill, args)。"""
    if not line.startswith("/"):
        return False
    parts = line[1:].split(None, 1)
    if not parts:
        return True
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    handler = COMMANDS.get(cmd)
    if handler:
        # /command help — 打印该命令的 docstring
        if args.strip().lower() == "help":
            doc = handler.__doc__
            if doc:
                from console.ui import info

                info(f"\n/{cmd} — {doc.strip()}\n")
            else:
                from console.ui import warn

                warn(f"/{cmd} 没有帮助文档")
            return True
        return handler(args, task, config)

    # 回退到技能查找
    from tools.skill.loader import find_skill
    from tools.skill.tools import set_active_skill_tools

    skill = find_skill(parts[0])
    if skill:
        cmd_parts = line.strip().split(maxsplit=1)
        skill_args = cmd_parts[1] if len(cmd_parts) > 1 else ""

        # 区分 prompt-based skill 和 command-based skill：
        # - 如果 skill 名称是 PATH 上的可执行文件，走 run_skill(bash 执行)
        # - 否则是 prompt-based skill，把 prompt 注入为用户消息让 LLM 读取
        import shutil

        if shutil.which(skill.name):
            # command-based skill：直接执行
            rendered = run_skill(skill, skill_args, config=config)
            return f"[skill: {skill.name}]\n\n{rendered}"
        else:
            # prompt-based skill：注入 prompt + 设置工具白名单
            if skill.tools:
                set_active_skill_tools(skill.tools)
            # 替换参数占位符
            from tools.skill.loader import substitute_arguments

            prompt = substitute_arguments(skill.prompt, skill_args, skill.arguments)
            return f"[skill: {skill.name}]\n\n{prompt}"

    return False
