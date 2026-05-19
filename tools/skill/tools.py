from typing import Optional, List
from langchain_core.tools import tool

from tools.skill.executor import execute_skill
from .loader import load_skills, find_skill


@tool
def skill_tool(skill_name: str, arguments: str, config_param: dict = None) -> str:
    """执行指定的技能工具。

    该函数根据提供的技能名称查找对应的技能，如果找到则执行该技能并返回结果；
    如果未找到技能，则返回错误信息和可用技能列表供用户参考。

    Args:
        skill_name: 要执行的技能名称，用于查找和匹配对应的技能定义
        arguments: 传递给技能的参数字符串，将被解析后传递给技能执行器
        config_param (dict): 内部使用参数，由系统自动注入，请勿传递。

    Returns:
        str: 技能执行的结果字符串。如果技能不存在，返回包含错误提示和可用技能列表的字符串
    """
    skill = find_skill(skill_name)

    # 如果未找到技能，返回错误信息和可用技能列表
    if skill is None:
        names = [s.name for s in load_skills()]
        return f"错误：未找到技能 '{skill_name}'。可用技能：{', '.join(names)}"
    return execute_skill(skill, arguments, config=config_param)


@tool
def skill_list(skill_name: Optional[str] = None) -> str:
    """获取可用技能的列表信息。

    该函数加载所有已定义的技能，并根据提供的技能名称进行过滤，
    最后返回格式化的技能列表信息，包括技能名称、触发词、参数提示、
    描述和使用时机等详细信息。

    Args:
        skill_name: 可选的技能名称。如果提供，则只返回匹配的技能；
                   如果不提供，则返回所有可用技能

    Returns:
        str: 格式化的技能列表字符串。可能的返回值包括：
             - 包含技能详细信息的格式化列表（技能名称、触发词、参数、描述、使用时机）
             - 如果没有可用技能或没有匹配的技能，返回"没有可用的技能。"
    """
    skills = load_skills()

    # 根据提供的技能名称过滤技能列表
    if skill_name:
        skills = [s for s in skills if s.name == skill_name]

    if not skills:
        return "没有可用的技能。"

    # 构建格式化的技能列表输出
    lines = ["可用技能：\n"]
    for s in skills:
        triggers = ", ".join(s.triggers)
        hint = f"  参数：{s.argument_hint}" if s.argument_hint else ""
        when = f"\n    使用时机：{s.when_to_use}" if s.when_to_use else ""
        lines.append(f"- **{s.name}** [{triggers}]{hint}\n  {s.description}{when}")
    return "\n".join(lines)


def get_tools() -> list:
    """获取技能工具列表"""
    return [skill_tool, skill_list]


def get_all_tools() -> list:
    """获取所有技能工具(无条件返回)"""
    return get_tools()
