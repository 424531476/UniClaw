import uuid

from uniclaw.agent import AgentTask
from uniclaw.console.ui import info, err
from uniclaw.utils.message import MessageRole


def cmd_btw(args: str, task: AgentTask, config: dict) -> bool:
    """在不打断当前对话的情况下提问侧问题

    开一个独立的 LLM 调用回答问题,不影响当前会话的消息历史。
    自动携带最近对话上下文,让回答更贴合当前工作场景。

    用法: /btw <问题>
    示例: /btw 什么是 Python GIL?
    """
    question = args.strip()
    if not question:
        err("用法: /btw <问题>\n示例: /btw 什么是 Python GIL?")
        return True

    from uniclaw.llm import chat
    from uniclaw.utils.message import build_context_summary

    # 构建带上下文的消息
    context = build_context_summary(task.messages, max_messages=10, max_chars=2000)
    system_content = "你是一个有帮助的助手。请简洁明了地回答,如果问题涉及代码给出关键示例即可。"
    if context:
        system_content += f"\n\n以下是用户当前对话的最近上下文,供你参考:\n---\n{context}\n---"

    messages = [
        {"role": MessageRole.SYSTEM, "content": system_content},
        {"role": MessageRole.USER, "content": question},
    ]

    # 获取 TUI 实例用于显示
    from uniclaw.console.run import TUIApp

    tui = TUIApp.get_instance()

    try:
        if tui:
            from uniclaw.console.ui import TUISpinner

            wait_id = TUISpinner.start("💡 思考侧问题...")

        response = chat(
            messages=messages,
            model_name=config.get("model_name"),
            openai_api_base=config.get("OPENAI_BASE_URL", ""),
            openai_api_key=config.get("OPENAI_API_KEY", ""),
            multimodal_model_name=config.get("multimodal_model_name"),
            temperature=0.7,
            max_tokens=2000,
            enable_thinking=False,
            thinking=False,
        )

        answer = response.content if response.content else "(无回答)"

        if tui:
            TUISpinner.stop(wait_id=wait_id)
            # 用特殊样式显示侧问题结果
            tui.print("")
            tui.print(f"💡 侧问题: {question}", style="fg:yellow")
            tui.print("─" * 40, style="fg:gray")
            tui.print(answer)
            tui.print("─" * 40, style="fg:gray")
            tui.print("")
        else:
            # 非 TUI 模式直接打印
            info(f"\n💡 侧问题: {question}")
            info("─" * 40)
            info(answer)
            info("─" * 40)
            info("")

    except Exception as e:
        if tui:
            TUISpinner.stop(wait_id=wait_id)
        err(f"侧问题回答失败: {e}")

    return True
