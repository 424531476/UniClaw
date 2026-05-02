from typing import Union

from tools.skill.executor import exectute_skill
from commands.core import cmd_clear, cmd_compact, cmd_model, cmd_cwd

COMMANDS = dict()
COMMANDS["clear"] = cmd_clear
COMMANDS["cls"] = cmd_clear
COMMANDS["compact"] = cmd_compact
COMMANDS["model"] = cmd_model
COMMANDS["cwd"] = cmd_cwd
COMMANDS["cd"] = cmd_cwd


def handle_slash(line: str, state, config) -> Union[bool, str]:
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
        return handler(args, state, config)

    # 回退到技能查找
    from tools.skill.loader import find_skill

    skill = find_skill(parts[0])
    if skill:
        cmd_parts = line.strip().split(maxsplit=1)
        skill_args = cmd_parts[1] if len(cmd_parts) > 1 else ""
        rendered = exectute_skill(skill, skill_args, config=config)
        return f"[技能: {skill.name}]\n\n{rendered}"

    return True
