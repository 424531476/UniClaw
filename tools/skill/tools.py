from typing import Optional, List
from langchain_core.tools import tool
from .loader import load_skills, find_skill, substitute_arguments


@tool
def skill_tool(skill_name: str, arguments: str) -> str:
    """执行指定的技能并返回执行结果。

    该函数根据技能名称查找对应的技能，使用提供的参数渲染技能提示词，
    然后通过agent执行技能并收集输出结果。

    Args:
        skill_name: 要执行的技能名称，用于查找和匹配对应的技能定义
        arguments: 技能执行所需的参数字典，键值对形式提供技能需要的参数

    Returns:
        str: 技能执行的结果字符串。可能的返回值包括：
             - 技能执行的文本输出内容
             - 如果未找到技能，返回错误信息和可用技能列表
             - 如果执行出错，返回错误描述
             - 如果技能完成但无文本输出，返回"(技能完成但无文本输出)"
    """
    # 查找匹配的技能定义
    skill = None
    for s in load_skills():
        if s.name == skill_name:
            skill = s
            break
    if skill is None:
        skill = find_skill(skill_name)

    # 如果未找到技能，返回错误信息和可用技能列表
    if skill is None:
        names = [s.name for s in load_skills()]
        return f"错误：未找到技能 '{skill_name}'。可用技能：{', '.join(names)}"

    # 渲染技能提示词并构造执行消息
    rendered = substitute_arguments(skill.prompt, arguments, skill.arguments)
    # message = f"[skill：{skill.name}]\n\n{rendered}"
    message = (
        f"[skill：{skill.name}]\n参数:{arguments}\n\n"
        f"**skill path:{skill.file_path}**\n"
        f"**请立即执行以下技能任务，不要仅确认或总结。**\n"
        f"**按照技能说明中的步骤逐一执行，并使用可用的工具完成任务。**\n\n"
        f"{rendered}"
    )

    output_parts: list[str] = []
    from agent import run, AssistantEvent, ToolEvent

    # 执行技能并收集输出结果
    try:
        for event in run(message):
            if isinstance(event, AssistantEvent) and hasattr(event, "content"):
                output_parts.append(event.content)
                print(event.tool_calls)
            if isinstance(event, ToolEvent):
                print(f"   工具执行结果: {event.content}")
    except Exception as e:
        return f"技能执行错误：{e}"

    return "".join(output_parts) or "(技能完成但无文本输出)"


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


tools = [skill_tool, skill_list]
