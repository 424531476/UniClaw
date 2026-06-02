import subprocess
import sys
from langchain_core.tools import tool


def _notify_windows(title: str, message: str) -> bool:
    """Windows Toast 通知"""
    # 使用 PowerShell 调用 .NET 的 NotifyIcon
    script = f"""
    Add-Type -AssemblyName System.Windows.Forms
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon = [System.Drawing.SystemIcons]::Information
    $n.Visible = $true
    $n.ShowBalloonTip(5000, '{title}', '{message}', [System.Windows.Forms.ToolTipIcon]::Info)
    Start-Sleep 3
    $n.Dispose()
    """
    try:
        subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True,
            timeout=10,
        )
        return True
    except Exception:
        return False


def _notify_macos(title: str, message: str) -> bool:
    """macOS 通知"""
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "{title}"',
            ],
            capture_output=True,
            timeout=10,
        )
        return True
    except Exception:
        return False


def _notify_linux(title: str, message: str) -> bool:
    """Linux 通知 (notify-send)"""
    try:
        subprocess.run(
            ["notify-send", title, message],
            capture_output=True,
            timeout=10,
        )
        return True
    except Exception:
        return False


@tool
def push_notification(
    message: str,
    title: str = "UniClaw",
    urgency: str = "normal",
) -> str:
    """
    发送桌面通知。后台任务完成、监控匹配、子 Agent 完成时可调用此工具通知用户。

    Args:
        message: 通知内容
        title: 通知标题，默认 "UniClaw"
        urgency: 紧急程度 (low/normal/critical)，目前仅用于日志标记

    Returns:
        str: 发送结果
    """
    if not message:
        return "错误: 通知内容不能为空"

    # 根据平台选择通知方式
    if sys.platform == "win32":
        success = _notify_windows(title, message)
    elif sys.platform == "darwin":
        success = _notify_macos(title, message)
    else:
        success = _notify_linux(title, message)

    if success:
        return f"已发送桌面通知: [{title}] {message}"
    else:
        return f"通知发送失败，当前平台: {sys.platform}"


def get_tools() -> list:
    """获取通知工具列表"""
    return [push_notification]


def get_all_tools() -> list:
    """获取所有通知工具"""
    return get_tools()
