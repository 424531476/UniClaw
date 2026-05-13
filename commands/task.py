import time

from agent import AgentTask
from console.ui import info, ok, warn, err


def cmd_task(args: str, task: AgentTask, config: dict) -> bool:

    """后台任务管理"""
    from task_queue import BackgroundTaskQueue

    bq = BackgroundTaskQueue.get_instance()
    parts = args.strip().split(None, 1) if args else []
    subcmd = parts[0].lower() if parts else "list"
    subargs = parts[1] if len(parts) > 1 else ""

    if subcmd == "submit":
        _task_submit(bq, subargs, config)
    elif subcmd == "list" or not subcmd:
        _task_list(bq)
    elif subcmd == "view":
        _task_view(bq, subargs)
    elif subcmd == "cancel":
        _task_cancel(bq, subargs)
    else:
        err(f"未知子命令: {subcmd}")
        info("可用命令: submit, list, view, cancel")
    return True


def _task_submit(bq, prompt: str, config: dict):
    if not prompt.strip():
        err("请提供任务描述: /task submit <prompt>")
        return

    # 解析 --silent / --notify 标志
    from task_queue import NotifyPolicy
    notify_policy = NotifyPolicy.DONE_ONLY.value
    actual_prompt = prompt
    if "--silent" in prompt:
        notify_policy = NotifyPolicy.SILENT.value
        actual_prompt = actual_prompt.replace("--silent", "").strip()
    elif "--notify" in prompt:
        notify_policy = NotifyPolicy.STATE_CHANGES.value
        actual_prompt = actual_prompt.replace("--notify", "").strip()

    if not actual_prompt:
        err("请提供任务描述: /task submit <prompt>")
        return

    info("后台任务权限策略: 只读操作自动放行，写入/执行操作按安全规则判断")
    success, result = bq.submit(actual_prompt, config, notify_policy=notify_policy)
    if success:
        info(f"  任务ID: {result}")
        info("  使用 /task list 查看任务状态")
        info(f"  使用 /task view {result} 查看输出")
    else:
        err(result)


def _task_list(bq):
    tasks = bq.list_tasks()
    if not tasks:
        warn("暂无后台任务")
        info("使用 /task submit <prompt> 提交后台任务")
        return

    status_icons = {
        "pending": "⏳",
        "running": "🔄",
        "completed": "✅",
        "failed": "❌",
        "cancelled": "🚫",
        "lost": "👻",
    }

    info(f"\n后台任务 (共 {len(tasks)} 个):\n")
    for t in tasks:
        icon = status_icons.get(t.status, "❓")
        elapsed = ""
        if t.completed_at:
            secs = int(t.completed_at - t.submitted_at)
            elapsed = f" ({secs}s)"
        elif t.status == "running":
            secs = int(time.time() - t.submitted_at)
            elapsed = f" ({secs}s)"

        info(f"  {icon} [{t.status}{elapsed}] {t.task_id}")
        info(f"     {t.name}")
        info("")


def _task_view(bq, task_id: str):
    task_id = task_id.strip()
    if not task_id:
        err("请指定任务 ID: /task view <task_id>")
        return
    text = bq.view_task(task_id)
    if text is None:
        task_info = bq.tasks.get(task_id)
        if task_info is None:
            err(f"任务 '{task_id}' 不存在")
        else:
            warn(f"任务 '{task_id}' 尚无输出 (状态: {task_info.status})")
        return
    info(text)


def _task_cancel(bq, task_id: str):
    task_id = task_id.strip()
    if not task_id:
        err("请指定任务 ID: /task cancel <task_id>")
        return
    if bq.cancel_task(task_id):
        ok(f"已取消任务: {task_id}")
    else:
        task_info = bq.tasks.get(task_id)
        if task_info is None:
            err(f"任务 '{task_id}' 不存在")
        else:
            warn(f"任务 '{task_id}' 已经结束 (状态: {task_info.status})")
