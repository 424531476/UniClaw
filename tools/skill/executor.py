import uuid
from config import Permissions, get_config
from tools.skill.loader import SkillDef, substitute_arguments


def exectute_skill(skill: SkillDef, arguments: str, config: dict) -> str:
    """
    执行指定的技能任务

    该函数通过渲染技能提示词、构造执行消息，并使用多智能体系统来执行技能任务。
    它会按照技能说明中的步骤逐一执行，并返回执行结果。

    Args:
        skill (SkillDef): 技能定义对象，包含技能名称、提示词、参数定义和文件路径等信息
        arguments (str): 传递给技能的参数字符串，用于替换提示词中的占位符

    Returns:
        str: 技能执行的结果文本。如果执行成功则返回助手的响应消息；
             如果执行过程中发生异常则返回错误信息；
             如果执行完成但没有文本输出则返回"(技能完成但无文本输出)"
    """
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

    from agent import MultiAgent, AgentState, AssistantEvent, ToolEvent

    # 执行技能并收集输出结果
    try:
        from agent import AgentStatus, AgentTask

        ma = MultiAgent()
        state = AgentState()
        task_id = uuid.uuid4().hex[:12]
        short_name = task_id[:8]
        task = AgentTask(
            id=task_id,
            name=short_name,
            prompt=message,
            status=AgentStatus.PENDING.value,
        )
        config = {**config, "depth": config["depth"] + 1}
        config["permission_mode"] = Permissions.ACCEPT_ALL
        ma.run(message, state=state, config=config, task=task)

        output = ma.get_assistant_messages(state.messages)

    except Exception as e:
        return f"技能执行错误：{e}"

    return output or "(技能完成但无文本输出)"
