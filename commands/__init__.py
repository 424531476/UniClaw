from typing import Union

from agent import AgentTask
from tools.skill.executor import execute_skill
from commands.session import cmd_compact, cmd_clear, cmd_export
from commands.model import cmd_model
from commands.system import cmd_cwd, cmd_skills, cmd_exit, cmd_usage
from commands.memory import cmd_memory
from commands.mcp import cmd_mcp
from commands.schedule import cmd_schedule
from commands.permissions import cmd_permissions

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
COMMANDS["schedule"] = cmd_schedule
COMMANDS["permissions"] = cmd_permissions


def handle_slash(line: str, task: AgentTask, config:dict) -> Union[bool, str]:
    """处理 /command [args]。如果已处理则返回True，技能匹配时返回元组(skill, args)。"""
    if not line.startswith("/"):
        return False
    parts = line[1:].split(None, 1)
    if not parts:
        return True
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    handler = COMMANDS.get(cmd)
    if handler:
        return handler(args, task, config)

    # 回退到技能查找
    from tools.skill.loader import find_skill

    skill = find_skill(parts[0])
    if skill:
        cmd_parts = line.strip().split(maxsplit=1)
        skill_args = cmd_parts[1] if len(cmd_parts) > 1 else ""
        rendered = execute_skill(skill, skill_args, config=config)
        return f"[技能: {skill.name}]\n\n{rendered}"

    return False
