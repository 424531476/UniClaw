from langchain_core.tools import tool
import time
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
    # 拷贝配置时排除带 "_" 前缀的内部键
    child_config = {k: v for k, v in config_param.items() if not k.startswith("_")}
    child_config["_inherit_event_queue"] = wait
    child_config["_notify_parent_on_complete"] = not wait
    child_config["_keep_alive"] = not wait

    # 启动子智能体任务，配置系统提示、智能体定义和隔离模式等参数
    task = mgr.start_sub_agent(
        name=name,
        user_message=prompt,
        system_prompt=config_param.get(
            "_system_prompt", "你是一个有用的助手，请帮助我解决我的问题。"
        ),
        config=child_config,
        agent_def=load_agent_definitions().get(subagent_type),
        isolation=isolation,
    )
    from agent import AgentStatus

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
        info_parts.append(
            f"子智能体完成后会发送简短通知；请使用任务ID调用 {check_agent_result.name} 来读取结果。"
        )
        return "\n".join(info_parts)


@tool
def send_message(task_id: str, message: str) -> str:
    """
    向指定的智能体发送消息。

    该函数尝试将消息发送给目标智能体。如果智能体正在运行，消息会被排队等待处理；
    如果智能体不存在或未运行，则返回相应的错误信息。

    Args:
        task_id (str): 目标智能体的名称或ID。
        message (str): 要发送给智能体的消息内容。

    Returns:
        str: 操作结果的状态信息，包含以下情况：
            - 成功时：返回消息已排队的确认信息
            - 智能体不存在时：返回无法找到智能体的错误提示
            - 智能体未运行时：返回包含智能体当前状态的错误信息
    """
    from agent import MultiAgent

    mgr = MultiAgent()
    ok = mgr.send_message(task_id, message)
    if ok:
        return f"消息已排队发送给智能体 '{task_id}'。它将在当前工作完成后处理。"

    # 消息发送失败，检查智能体状态
    task = mgr.id2AgentTask.get(task_id)
    if task is None:
        return f"无法找到智能体 '{task_id}'。请检查名称是否正确。"
    return f"错误：智能体 '{task_id}' 未运行（状态：{task.status}）。无法发送消息。"


@tool
def agent_close(task_id: str) -> str:
    """
    关闭后台子智能体，当父智能体决定其任务已完成时调用。

    Args:
        task_id (str): 要关闭的子智能体任务ID

    Returns:
        str: 操作结果信息
    """
    from agent import MultiAgent

    mgr = MultiAgent()
    ok = mgr.close_agent(task_id)
    if ok:
        return f"已向子智能体 '{task_id}' 发送关闭信号。"
    return f"错误：未找到子智能体 '{task_id}'。"


@tool
def check_agent_result(task_id: str, full: bool = False) -> str:
    """
    检查指定任务ID的执行结果和状态信息。

    该函数通过 MultiAgent 管理器查询指定任务的状态、名称、工作树分支和执行结果，
    并以格式化的字符串形式返回这些信息。如果任务不存在，则返回错误提示。

    Args:
        task_id (str): 要查询的任务唯一标识符。

    Returns:
        str: 格式化的任务信息字符串，包含以下内容：
             - 状态：任务的当前执行状态
             - 名称：任务的名称
             - 工作树分支（如果存在）：任务关联的工作树分支信息
             - 结果（如果存在）：任务的执行结果内容
             如果任务不存在，返回错误提示信息。
    """
    from agent import MultiAgent

    mgr = MultiAgent()
    task = mgr.id2AgentTask.get(task_id)
    if task is None:
        return f"错误：不存在 ID 为 '{task_id}' 的任务"
    lines = [f"状态：{task.status}", f"名称：{task.name}"]
    if task.worktree_branch:
        lines.append(f"工作树分支：{task.worktree_branch}")
    assistant_items = [
        message.get("content", "")
        for message in task.messages
        if message.get("role") == "assistant" and message.get("content")
    ]
    if full:
        result = "\n".join(assistant_items) or task.result
        if result:
            lines.append(f"\n结果：\n{result}")
        return "\n".join(lines)

    start = min(task.result_read_index, len(assistant_items))
    new_items = assistant_items[start:]
    task.result_read_index = len(assistant_items)
    if new_items:
        lines.append("\n新增结果：\n" + "\n".join(new_items))
    else:
        lines.append("\n新增结果：\n(暂无新增输出)")
    return "\n".join(lines)


@tool
def list_agent_tasks() -> str:
    """
    列出所有子智能体任务的当前状态和信息。

    该函数通过 MultiAgent 管理器获取所有正在运行的任务,并以格式化的表格形式展示每个任务的关键信息,
    包括任务ID、名称、状态、工作树分支和提示内容(截断显示)。

    Returns:
        str: 格式化后的任务列表字符串。如果没有任务,返回提示信息;否则返回包含表头和所有任务信息的表格字符串,
             每行包含任务ID、名称(最多8字符)、状态、工作树分支(最多15字符)和提示内容(最多50字符)。
    """
    from agent import MultiAgent

    mgr = MultiAgent()
    tasks = mgr.list_tasks()

    # 检查是否存在任务,若无则返回提示信息
    if not tasks:
        return "没有子智能体任务。"

    # 构建表格头部和分隔线
    lines = ["ID           | 名称     | 状态      | 工作树分支       | 提示"]
    lines.append("-------------|----------|-----------|-----------------|------")

    # 遍历所有任务,格式化每个任务的信息并添加到列表中
    for task in tasks:
        prompt_short = task.prompt[:50] + ("..." if len(task.prompt) > 50 else "")
        wt = task.worktree_branch[:15] if task.worktree_branch else "-"
        lines.append(
            f"{task.id} | {task.name[:8]:8s} | {task.status:9s} | {wt:15s} | {prompt_short}"
        )

    # 将所有行连接成完整的表格字符串并返回
    return "\n".join(lines)


@tool
def agent_discuss(
    topic: str,
    participants: list[str],
    rounds: int = 2
) -> str:
    """
    让现有的后台子智能体围绕指定主题进行有限轮次的讨论。

    participants 应包含子智能体的任务ID。父智能体作为协调者：
    它将每轮的讨论记录发送给每个参与者，等待他们的回复，并返回完整的讨论文本。
    当父智能体决定不再需要这些子智能体时，应使用 agent_close 关闭它们。

    Args:
        topic (str): 讨论的主题
        participants (list[str]): 参与讨论的子智能体任务ID列表
        rounds (int): 讨论轮数，默认为2，范围为1-5

    Returns:
        str: 完整的讨论文本，包含主题和每轮各参与者的发言
    """
    from agent import MultiAgent, AgentStatus

    mgr = MultiAgent()
    tasks = []
    # 验证所有参与者是否存在且状态可用
    for task_id in participants:
        task = mgr.id2AgentTask.get(task_id)
        if task is None:
            return f"Error: child agent '{task_id}' was not found."
        if task.status not in (
            AgentStatus.RUNNING.value,
            AgentStatus.PENDING.value,
            AgentStatus.WAITING.value,
        ):
            return f"Error: child agent '{task_id}' is not available (status: {task.status})."
        tasks.append(task)

    # 限制讨论轮数在1-5之间
    rounds = max(1, min(int(rounds), 5))
    transcript = [f"Topic: {topic}"]

    # 执行多轮讨论
    for round_no in range(1, rounds + 1):
        round_entries = []
        context = "\n\n".join(transcript)
        for task in tasks:
            before_count = len(task.messages)
            # 构造本轮的提示词，包含当前轮次信息和历史讨论文本
            prompt = (
                f"讨论第 {round_no}/{rounds} 轮。\n"
                f"主题：{topic}\n\n"
                f"当前讨论记录：\n{context}\n\n"
                "请回复你当前的观点、不同意见和具体建议。"
            )
            # 发送消息给子智能体
            if not mgr.send_message(task.id, prompt):
                round_entries.append(f"[{task.name}] could not receive the message.")
                continue

            # 等待子智能体响应，最多等待300秒
            deadline = time.time() + 300
            while time.time() < deadline:
                if task.status in (AgentStatus.FAILED.value, AgentStatus.CANCELLED.value):
                    break
                # 检查是否有新消息且状态为WAITING（表示已完成回复）
                if len(task.messages) > before_count and task.status == AgentStatus.WAITING.value:
                    break
                time.sleep(0.2)

            # 获取最新的助手回复
            latest = ""
            for message in reversed(task.messages):
                if message.get("role") == "assistant" and message.get("content"):
                    latest = message["content"]
                    break
            round_entries.append(f"[{task.name} / {task.id}]\n{latest or task.result or '(no response)'}")
        transcript.append(f"Round {round_no}\n" + "\n\n".join(round_entries))

    return "\n\n".join(transcript)


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


def get_tools() -> list:
    """获取多智能体工具列表"""
    return [
        agent_create,
        send_message,
        agent_close,
        check_agent_result,
        list_agent_tasks,
        agent_discuss,
        list_agent_definitions,
    ]
