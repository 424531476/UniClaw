from langchain_core.tools import tool
from config import Permissions
from context import Scope, get_app_dir

PLANS_DIR = get_app_dir(Scope.PROJECT.value) / "plans"


@tool
def enter_plan_mode(config_param: dict = None) -> str:
    """
    进入计划模式。在计划模式下，只读操作自动允许，写入/修改操作需要用户确认。
    请在需要仔细分析代码、制定方案时使用此工具。
    计划写好后，用编辑器打开计划文件供用户审核，用户同意后调用 exit_plan_mode 退出。
    """
    config_param["permission_mode"] = Permissions.PLAN
    return f"已进入计划模式。只读操作自动允许，写入操作需要用户确认。请将计划方案写入计划目录 {PLANS_DIR/'*.md'}，然后用编辑器打开供用户审核。"


@tool
def exit_plan_mode(config_param: dict = None) -> str:
    """
    退出计划模式，恢复到自动权限模式。
    仅在用户审核并同意计划后调用此工具。
    """
    config_param["permission_mode"] = Permissions.AUTO
    return "已退出计划模式，恢复到自动权限模式。现在可以开始执行计划。"


def get_tools() -> list:
    """获取计划模式工具列表"""
    return [enter_plan_mode, exit_plan_mode]
