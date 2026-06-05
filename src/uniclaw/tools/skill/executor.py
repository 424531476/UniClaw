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


def run_command(
    command: str, cwd: Path, timeout: int = 120, config: dict | None = None
) -> str:
    """在指定目录下执行命令,并返回输出结果。"""
    config = {**config} if config is not None else {}
    config["cwd"] = str(cwd)
    return Bash.func(command, timeout=timeout, config=config)


def run_skill(skill_name: str, command: str, config: dict | None = None) -> str:
    skill = find_skill(skill_name)

    if skill is None:
        return f"错误：未找到技能 '{skill_name}'。"

    return run_command(
        normalize_skill_command(skill, command),
        cwd=Path(skill.file_path).parent,
        config=config,
    )
