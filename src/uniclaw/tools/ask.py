from langchain_core.tools import tool


@tool
def AskUserQuestion(question: str, title: str = "询问") -> str:
    """
    向用户提问并等待回答。这是你唯一合法的主动与用户沟通的方式,任何需要用户输入、决策或等待用户确认后才能继续执行的任务环节,都必须通过此工具。
    当任务不明确、需要澄清需求、执行关键操作前需要用户确认、或在计划模式下需要与用户交流时使用此工具。
    提问时不要只问问题,要同时给出 2-5 个可行的解决方案供用户选择,降低用户思考负担。

    Args:
        question: 要向用户提出的问题,应包含多个备选方案
        title: 对话框标题,默认为"询问"
    """
    from uniclaw.console.run import tui_input

    prompt = f"💬 {question}\n\n请输入您的回答:"
    answer = tui_input(prompt, title=title)
    return f"用户回答:{answer}"


def get_tools() -> list:
    return [AskUserQuestion]


def get_all_tools() -> list:
    """获取所有交互工具(无条件返回)"""
    return get_tools()
