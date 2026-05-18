from langchain_core.tools import tool
from config import Permissions
from context import Scope, get_app_dir
from tools.shell import Bash
from tools.fs import Write, Edit
from tools.ask import ask_user

PLANS_DIR = get_app_dir(Scope.PROJECT.value) / "plans"


@tool
def enter_plan_mode(config_param: dict = None) -> str:
    """
    进入计划模式。在计划模式下,只读操作自动允许,写入/修改操作需要用户确认。
    请在需要仔细分析代码、制定方案时使用此工具。
    计划写好后,用编辑器打开计划文件供用户审核,用户同意后调用 exit_plan_mode 退出。

    Args:
        config_param: 内部使用参数，由系统自动注入，请勿传递。
    """
    config_param["permission_mode"] = Permissions.PLAN
    return (
        f"已进入计划模式。\n"
        f"请将计划方案写入计划目录 {PLANS_DIR/'*.md'}。\n\n"
        f"## 计划审核流程（必须严格遵守）\n"
        f"1. 使用 {Write.name} 工具将计划写入上述目录\n"
        f"2. 使用 {Bash.name} 工具异步打开计划书（timeout<=0）供用户审阅\n"
        f"3. 使用 {ask_user.name} 工具询问用户是否同意计划，必须给出明确的同意/修改选项\n"
        f"4. 如果用户不同意或要求修改，使用 {Edit.name} 工具修改计划书，然后重复步骤 2-3\n"
        f"5. 只有用户明确确认同意后，才能调用 {exit_plan_mode.name} 退出计划模式\n"
        f"\n警告：未经用户明确确认不得退出计划模式！"
    )


@tool
def exit_plan_mode(config_param: dict = None) -> str:
    """
    退出计划模式，恢复到自动权限模式。
    调用前必须已完成完整审核流程：打开计划书供用户审阅 → 使用 ask_user 获得用户明确同意。
    未经用户确认不得调用此工具！

    Args:
        config_param: 内部使用参数，由系统自动注入，请勿传递。
    """
    config_param["permission_mode"] = Permissions.AUTO
    return "已退出计划模式，恢复到自动权限模式。现在可以开始执行计划。"


def get_tools() -> list:
    """获取计划模式工具列表"""
    return [enter_plan_mode, exit_plan_mode]
