def cmd_clear(_args: str, state, _config) -> bool:
    """清除当前会话上下文"""
    state.messages.clear()
    return True
