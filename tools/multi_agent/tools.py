from langchain_core.tools import tool
from agent import AgentStatus
from tools.multi_agent.sub_agent import load_agent_definitions
from context import APP_NAME


@tool
def agent_create(
    prompt: str,
    subagent_type: str,
    name: str,
    wait: bool = True,
    isolation=False,
    config_param: dict = None,
):
    """
    创建并启动一个子智能体任务。

    该函数用于创建一个新的智能体实例，根据配置启动子智能体执行指定任务，
    并可选择等待任务完成或直接返回任务信息。

    Args:
        prompt (str): 用户消息或任务提示，作为智能体的输入指令
        subagent_type (str): 子智能体类型标识符，用于从预定义的智能体定义中加载对应配置
        name (str): 智能体名称，用于标识和追踪该智能体任务
        wait (bool, optional): 是否等待任务完成。默认为 True，表示同步等待；
                              设置为 False 时异步执行，立即返回任务信息
        isolation (bool, optional): 是否启用隔离模式。默认为 False，
                                   启用后智能体将在独立环境中运行
        config_param: 内部使用参数，由系统自动注入，请勿传递。

    Returns:
        str: 根据 wait 参数返回不同格式的结果：
             - 当 wait=True 时：返回包含智能体名称、类型、分支信息和执行结果的格式化字符串
             - 当 wait=False 时：返回包含任务 ID、名称、状态等信息的多行文本，
                               提示用户使用 CheckAgentResult 或 SendMessage 进行后续交互
             - 如果任务启动失败：返回错误信息字符串

    Example:
        >>> # 同步执行，等待结果
        >>> result = agent_create(
        ...     prompt="分析这段代码",
        ...     subagent_type="code_analyzer",
        ...     name="analysis_task"
        ... )
        >>>
        >>> # 异步执行，立即返回
        >>> task_info = agent_create(
        ...     prompt="编写单元测试",
        ...     subagent_type="test_writer",
        ...     name="test_task",
        ...     wait=False
        ... )
    """
    from agent import MultiAgent

    # 创建多智能体管理器实例
    mgr = MultiAgent()

    # 启动子智能体任务，配置系统提示、智能体定义和隔离模式等参数
    task = mgr.start_sub_agent(
        name=name,
        user_message=prompt,
        system_prompt=config_param.get(
            "_system_prompt", "你是一个有用的助手，请帮助我解决我的问题。"
        ),
        config=config_param,
        agent_def=load_agent_definitions().get(subagent_type),
        isolation=isolation,
    )

    # 检查任务启动是否失败，如果失败则返回错误信息
    if task.status == AgentStatus.FAILED.value:
        return f"生成智能体时出错：{task.result}"

    # 根据 wait 参数决定是同步等待还是异步返回
    if wait:
        # 同步模式：等待任务完成（最多300秒），然后返回格式化结果
        mgr.wait(task.id, timeout=300)
        result = task.result or f"(无输出 — 状态：{task.status})"
        header = f"[智能体：{task.name}"
        if subagent_type:
            header += f" ({subagent_type})"
        if task.worktree_branch:
            header += f", 分支：{task.worktree_branch}"
        header += "]"
        return f"{header}\n\n{result}"
    else:
        # 异步模式：立即返回任务基本信息，供后续查询使用
        info_parts = [
            f"任务 ID：{task.id}",
            f"名称：{task.name}",
            f"状态：{task.status}",
        ]
        if subagent_type:
            info_parts.append(f"类型：{subagent_type}")
        if task.worktree_branch:
            info_parts.append(f"工作树分支：{task.worktree_branch}")
        info_parts.append("使用 CheckAgentResult 或 SendMessage 与此智能体交互。")
        return "\n".join(info_parts)

@tool
def send_message(target: str, message: str) -> str:
    """
    向指定的智能体发送消息。

    该函数尝试将消息发送给目标智能体。如果智能体正在运行，消息会被排队等待处理；
    如果智能体不存在或未运行，则返回相应的错误信息。

    Args:
        target (str): 目标智能体的名称或ID。
        message (str): 要发送给智能体的消息内容。

    Returns:
        str: 操作结果的状态信息，包含以下情况：
            - 成功时：返回消息已排队的确认信息
            - 智能体不存在时：返回无法找到智能体的错误提示
            - 智能体未运行时：返回包含智能体当前状态的错误信息
    """
    from agent import MultiAgent

    mgr = MultiAgent()
    ok = mgr.send_message(target, message)
    if ok:
        return f"消息已排队发送给智能体 '{target}'。它将在当前工作完成后处理。"
    
    # 消息发送失败，检查智能体状态
    task = mgr.id2AgentTask.get(target)
    if task is None:
        return f"无法找到智能体 '{target}'。请检查名称是否正确。"
    return f"错误：智能体 '{target}' 未运行（状态：{task.status}）。无法发送消息。"


@tool
def list_agent_definitions() -> str:
    """
    列出所有可用的智能体类型定义。

    该函数加载并格式化显示系统中所有已定义的智能体类型信息，包括每个智能体的名称、
    调用 agent_create 时使用类型名称作为 subagent_type。
    """
    defs = load_agent_definitions()
    if not defs:
        return "没有可用的智能体类型。"

    # 构建智能体类型列表的输出内容
    lines = ["可用的智能体类型：", ""]
    for aname, d in sorted(defs.items()):
        model_info = f"  模型：{d.model_name}" if d.model_name else ""
        tools_info = f"  工具：{', '.join(d.tools)}" if d.tools else ""
        lines.append(f"  {aname:20s}  [{d.source:8s}]  {d.description}")
        if model_info:
            lines.append(f"                           {model_info}")
        if tools_info:
            lines.append(f"                           {tools_info}")

    # 添加自定义智能体创建指引
    lines.append("")
    lines.append(
        f"创建自定义智能体：将 .md 文件放置在 ~/.{APP_NAME}/agents/ 或 .{APP_NAME}/agents/ 中"
    )
    return "\n".join(lines)
