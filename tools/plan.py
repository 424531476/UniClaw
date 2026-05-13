from langchain_core.tools import tool
from config import Permissions


@tool
def enter_plan_mode(config_param: dict = None) -> str:
    """
    进入计划模式。在计划模式下，只读操作自动允许，写入/修改操作需要用户确认。
    请在需要仔细分析代码、制定方案时使用此工具。
    """
    config_param["permission_mode"] = Permissions.PLAN
    return "已进入计划模式。只读操作自动允许，写入操作需要用户确认。请将计划方案写入计划目录。"


@tool
def exit_plan_mode(config_param: dict = None) -> str:
    """
    退出计划模式，恢复到自动权限模式。
    在计划制定完成后使用此工具。
    """
    config_param["permission_mode"] = Permissions.AUTO
    return "已退出计划模式，恢复到自动权限模式。"


def get_tools() -> list:
    """获取计划模式工具列表"""
    return [enter_plan_mode, exit_plan_mode]
