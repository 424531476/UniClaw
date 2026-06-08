from langchain_core.tools import tool

from .todolist import TodoList, TodoStatus

# ── 普通模式工具 ──────────────────────────────────────────────


@tool
def todolist_create(items: list[str]) -> str:
    """
    创建一个新的任务清单(todolist),替换现有内容。如果已有清单则覆盖。
    用于将复杂任务分解为尽可能多的细粒度步骤进行跟踪。
    每个步骤应该是具体、独立、可验证的小任务,不应超过 20 字描述。
    第一个步骤自动标记为正在进行。

    Args:
        items: 任务步骤列表,每个元素是一个步骤的描述。优先分解为更多细粒度步骤,避免步骤过于宽泛。
    """
    todo = TodoList.get_instance()
    todo.clear()
    for content in items:
        todo.add(content)
    if todo.items:
        todo.items[0].status = TodoStatus.IN_PROGRESS
    return f"已创建任务清单,共 {len(todo.items)} 个步骤:\n{todo.get_list()}"


@tool
def todolist_update(index: int, status: str) -> str:
    """
    更新任务清单中指定步骤的状态。

    Args:
        index: 步骤的索引(从 0 开始)
        status: 新状态,可选值为 "pending"(未完成)、"in_progress"(正在进行)、"completed"(已完成)
    """
    try:
        status = TodoStatus(status)
    except ValueError:
        return f"错误: 无效状态 '{status}',可选值为 {', '.join(TodoStatus)}"
    todo = TodoList.get_instance()
    if todo.is_empty():
        return f"错误: 当前没有任务清单,请先使用 {todolist_create.name} 创建"
    result = todo.update_status(index, status)
    return f"已更新步骤 {index} 状态为 {status}:\n{result}"


@tool
def todolist_clear() -> str:
    """清空当前任务清单。当所有步骤完成后调用此工具。"""
    todo = TodoList.get_instance()
    count = len(todo.items)
    todo.clear()
    return f"已清空任务清单(共 {count} 个步骤)"


@tool
def todolist_cancel(config: dict = None) -> str:
    """
    取消当前任务清单。用户明确要求暂停或取消时调用,允许 agent 退出会话。
    设置取消事件,使 agent 可以正常退出。

    Args:
        config: 系统注入参数,请勿传递
    """
    config["_current_task"].cancel_event.set()
    return "任务暂停,等待用户下一步指示..."


@tool
def todolist_list() -> str:
    """列出当前任务清单的所有步骤及状态。"""
    todo = TodoList.get_instance()
    if todo.is_empty():
        return "当前没有任务清单"
    return todo.get_list()


# ── 监工模式工具(工具名与普通模式一致)──────────────────────


@tool
def _overseer_create(items: list[str], reason: str, config: dict = None) -> str:
    """
    创建一个新的任务清单(todolist),替换现有内容。如果已有清单则覆盖。
    1. 原清单哪里不合理(遗漏/冗余/粒度不当/方向错误等)
    2. 新清单做了哪些改进
    审核不通过则拒绝重建。

    Args:
        items: 任务步骤列表,每个元素是一个步骤的描述
        reason: 重建理由,必须包含"原清单问题"和"新清单改进"
        config: 系统注入参数,请勿传递
    """
    from .overseer import verify_modification

    todo = TodoList.get_instance()
    if len(todo.items) > 0:
        old_items = [f"{item.content} ({item.status})" for item in todo.items]
        passed, fail_reason = verify_modification(
            "重建清单", old_items, items, reason, config
        )
        if not passed:
            return (
                f"❌ 审核未通过,清单未重建:\n"
                f"你的理由: {reason}\n"
                f"不通过原因: {fail_reason}\n"
                f"请修正后重试。"
            )

    todo.clear()
    for content in items:
        todo.add(content)
    if todo.items:
        todo.items[0].status = TodoStatus.IN_PROGRESS
    return f"✅ 已重建清单(共 {len(todo.items)} 个步骤):\n{todo.get_list()}"


@tool
def _overseer_update(index: int, status: str, reason: str, config: dict = None) -> str:
    """
    更新任务清单中指定步骤的状态。
    审核不通过则拒绝标记。

    Args:
        index: 步骤的索引(从 0 开始)
        status: 新状态,可选值为 "pending"、"in_progress"、"completed"
        reason: 完成说明,必须说明做了什么、改了哪些文件
        config: 系统注入参数,请勿传递
    """
    from .overseer import verify_completion

    try:
        status = TodoStatus(status)
    except ValueError:
        return f"错误: 无效状态 '{status}',可选值为 {', '.join(TodoStatus)}"
    todo = TodoList.get_instance()
    if todo.is_empty():
        return f"错误: 当前没有任务清单,请先使用 {todolist_create.name} 创建"

    if status == TodoStatus.COMPLETED:
        item = todo.items[index]
        old_status = item.status
        passed, fail_reason = verify_completion(
            f"{item.content}\n\n完成说明: {reason}", config
        )
        if not passed:
            item.status = old_status
            return (
                f"❌ 审核未通过,步骤 {index} 未标记为完成:\n"
                f"任务: {item.content}\n"
                f"你的说明: {reason}\n"
                f"不通过原因: {fail_reason}\n"
                f"请修正后重试。"
            )

    result = todo.update_status(index, status)
    if status == TodoStatus.COMPLETED:
        return f"✅ 审核通过,步骤 {index} 已标记为完成:\n{result}"
    return f"已更新步骤 {index} 状态为 {status}:\n{result}"


# 监工工具对外名称与普通模式一致
_overseer_create.name = "todolist_create"
_overseer_update.name = "todolist_update"


# ── 系统提示 ────────────────────────────────────────────────


def get_list_system_prompt() -> str:
    """返回 todolist 内容用于注入 system_prompt,为空时返回空字符串"""
    from .overseer import OverseerManager

    todo = TodoList.get_instance()
    is_overseer = OverseerManager.get_instance().active

    if not todo.items:
        return f"遇到复杂任务时,使用 {todolist_create.name} 将其拆解为多个步骤并逐步完成。"

    lines = ["# 当前任务进度", "你有一个未完成的任务清单,必须按照顺序逐步完成:"]
    lines.append(todo.get_list())
    lines.append("")
    lines.append("重要指令:")
    lines.append("- 你必须主动推进任务完成,不要等待用户催促")

    if is_overseer:
        lines.append(f"- 每完成一步,立即调用 {todolist_update.name} 并在 reason 中说明做了什么")
        lines.append(f"- 需要重建清单时,调用 {todolist_create.name} 并在 reason 中说明原清单问题和新清单改进")
    else:
        lines.append(f"- 每完成一步,立即调用 {todolist_update.name} 将状态更新为 completed")
        lines.append(f"- 全部完成后调用 {todolist_clear.name} 清空清单")

    lines.append("- 完成当前步骤后,自动开始下一步,不要停下来问用户")
    lines.append("- 如果遇到阻塞,记录问题并继续推进其他步骤")
    return "\n".join(lines)


# ── 工具列表 ────────────────────────────────────────────────


def get_tools() -> list:
    from .overseer import OverseerManager

    base = [todolist_clear, todolist_list, todolist_cancel]
    if OverseerManager.get_instance().active:
        return [_overseer_create, _overseer_update, *base]
    return [todolist_create, todolist_update, *base]


def get_all_tools() -> list:
    """获取所有待办工具,与 get_tools 相同(按模式动态返回)"""
    return get_tools()
