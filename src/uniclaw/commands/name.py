from uniclaw.agent import AgentTask
from uniclaw.config import AppConfig
from uniclaw.console.ui import ok, err
from uniclaw.utils.message import MessageRole


async def cmd_name(args: str, config: AppConfig) -> bool:
    """为当前会话设置名称,无参数时自动生成

    用法:
      /name <名称>    - 手动设置会话名称
      /name           - 根据对话内容自动生成名称
    """
    task = config.current_agent
    session_id = task.session.id

    from uniclaw.tools.session.session_manager import SessionManager

    new_title = args.strip()
    if not new_title:
        # 自动生成
        new_title, error = await _generate_title(task, config)
        if not new_title:
            err(f"自动生成标题失败: {error}\n请手动指定: /name <名称>")
            return True

    success = SessionManager.update_title(session_id, new_title)
    if success:
        ok(f"会话已命名: {new_title}")
    else:
        err(f"命名失败,会话尚未保存。请先发送消息后再试。")

    return True


async def _generate_title(task: AgentTask, config: AppConfig) -> tuple[str, str]:
    """用 LLM 根据对话上下文生成标题。返回 (title, error)。"""
    from uniclaw.llm import achat

    context = task.session.build_context_summary(max_messages=12, max_chars=3000)
    if not context:
        return "", "对话内容为空"

    messages = [
        {
            "role": MessageRole.SYSTEM,
            "content": "你为对话生成标题。只输出一个简洁标题,不要解释,不要引号,10个中文字符以内。",
        },
        {"role": MessageRole.USER, "content": context},
    ]

    wait_id = config.spinner.start("生成标题...")
    try:
        resp = await achat(
            messages,
            model_name=config.mini_model_name or config.model_name,
            enable_thinking=False,
            thinking=False,
            max_tokens=50,
            config=config,
        )
        title = resp.content.strip().strip('"').strip("'")[:20]
        if not title:
            return "", "LLM 返回了空标题"
        return title, ""
    except Exception as e:
        return "", str(e)
    finally:
        config.spinner.stop(wait_id=wait_id)
