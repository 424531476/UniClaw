from copy import copy
from pathlib import Path
import shlex
import shutil
from uniclaw.tools.shell import Bash
from uniclaw.tools.skill.loader import SkillDef, find_skill


def normalize_skill_command(skill: SkillDef, command: str) -> str:
    """使常见的技能命令代码片段在 PowerShell 中可执行。"""
    stripped = command.strip()
    if not stripped:
        raise ValueError("命令不能为空")

    first_token = shlex.split(stripped, posix=False)[0].strip("'\"")
    if first_token == skill.name:
        return stripped

    if shutil.which(skill.name):
        return f"{skill.name} {stripped}"

    return stripped


def _run_command(
    command: str, cwd: Path, config: dict, timeout: int = 120
) -> str:
    """在指定目录下执行命令,并返回输出结果。"""
    task = config.get("_current_task")
    # 浅拷贝 session 并修改 root_dir,避免并发时修改共享对象
    session_copy = copy(task.session)
    session_copy.root_dir = cwd
    task_copy = copy(task)
    task_copy.session = session_copy
    config = {**config}
    config["_current_task"] = task_copy
    return Bash.func(command, timeout=timeout, config=config)


def run_skill(skill_name: str, command: str, config: dict | None = None) -> str:
    root_dir = config.get("_current_task").session.root_dir
    skill = find_skill(root_dir, skill_name)

    if skill is None:
        return f"错误:未找到技能 '{skill_name}'。"

    return _run_command(
        normalize_skill_command(skill, command),
        cwd=Path(skill.file_path).parent,
        config=config,
    )
