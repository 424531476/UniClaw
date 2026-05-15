import uuid

from config import Permissions, get_config, get_config_dict
from tools.skill.loader import SkillDef, substitute_arguments


def execute_skill(
    skill: SkillDef, arguments: str = "", config: dict | None = None
) -> str:
    """
    渲染并执行技能作为嵌套代理任务。

    该函数将技能定义转换为可执行的任务，通过创建子代理来执行技能指令。
    支持参数替换、任务层级管理和错误处理。

    Args:
        skill: 技能定义对象，包含技能的名称、提示模板、参数定义和文件路径等信息
        arguments: 传递给技能的参数字符串，默认为空字符串
        config: 配置字典，包含代理运行的相关配置项。如果为None，则使用默认配置

    Returns:
        str: 技能执行的结果输出。如果执行成功，返回助手的消息内容或任务结果；
             如果发生异常，返回错误信息；如果没有输出，返回默认完成提示
    """
    if config is None:
        config = get_config_dict(get_config())

    arguments = arguments or ""
    rendered = substitute_arguments(skill.prompt, arguments, skill.arguments)
    message = (
        f"[技能: {skill.name}]\n参数: {arguments}\n\n"
        f"**技能路径: {skill.file_path}**\n"
        "**立即执行以下技能任务。不要仅确认或总结。**\n"
        "**按照技能说明逐步操作，并使用可用工具完成任务。**\n\n"
        f"{rendered}"
    )

    from agent import AgentStatus, AgentTask, MultiAgent

    # 创建多代理实例并构建任务
    try:
        ma = MultiAgent()
        task_id = uuid.uuid4().hex[:12]
        task = AgentTask(
            id=task_id,
            name=task_id[:8],
            prompt=message,
            status=AgentStatus.PENDING.value,
        )

        # 继承父任务的事件队列以支持事件传递
        parent_task = config.get("_task")
        if parent_task is not None and getattr(parent_task, "event_queue", None) is not None:
            task.event_queue = parent_task.event_queue

        # 构建子代理配置，过滤内部配置项并设置默认值
        base_config = {k: v for k, v in config.items() if not k.startswith("_")}
        base_config.setdefault("depth", 0)
        base_config.setdefault("max_agent_depth", 3)
        base_config.setdefault("permission_mode", Permissions.AUTO.value)
        base_config.setdefault("cwd", None)
        child_config = {**base_config, "depth": base_config["depth"] + 1}

        # 执行技能任务并获取输出
        ma.run(message, config=child_config, task=task)
        output = ma.get_assistant_messages(task.messages)
    except Exception as e:
        return f"技能执行错误: {e}"

    return output or task.result or "(技能已完成，无文本输出)"
