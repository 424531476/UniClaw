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
        wait_id = config.spinner.start("生成标题...")
        try:
            new_title = await task.session.generate_title()
        except Exception as e:
            error = str(e)
        finally:
            config.spinner.stop(wait_id=wait_id)

        if not new_title:
            err(f"自动生成标题失败: {error}\n请手动指定: /name <名称>")
            return True

    success = SessionManager.update_title(session_id, new_title)
    if success:
        ok(f"会话已命名: {new_title}")
    else:
        err(f"命名失败,会话尚未保存。请先发送消息后再试。")

    return True
