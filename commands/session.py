import json
from datetime import datetime
from pathlib import Path
from agent import AgentTask
from compaction import compact_messages, estimate_tokens

from console.ui import info, ok, warn, err
from utils.usage import get_stats, UsageField, TOTAL


def cmd_compact(args: str, task: AgentTask, config: dict) -> bool:
    """手动压缩对话历史"""
    focus = args.strip() if args else ""
    model_name = config.get("model_name")
    before = estimate_tokens(task.messages, model_name)
    task.messages = compact_messages(task.messages, config, focus=focus)
    after = estimate_tokens(task.messages, model_name)
    saved = before - after
    ok(
        f"✓ 对话已压缩: {before} → {after} tokens（节省 {saved} tokens）{'（聚焦: ' + focus + '）' if focus else ''}"
    )
    return True


def cmd_clear(_args: str, task: AgentTask, _config: dict) -> bool:
    """清除当前会话上下文和屏幕"""
    task.messages.clear()
    from console.run import TUIApp
    tui = TUIApp.get_instance()
    if tui:
        tui.clear()
    else:
        # 非TUI模式，使用系统清屏命令
        import platform
        import subprocess
        command = 'cls' if platform.system() == 'Windows' else 'clear'
        subprocess.call(command, shell=True)
    return True


def cmd_export(args: str, task: AgentTask, _config: dict) -> bool:
    """导出当前对话消息到文件"""
    from context import get_app_dir, Scope

    # 确定导出路径和格式
    if args.strip():
        # 用户提供了路径
        export_path = Path(args.strip())
        # 如果是相对路径，转换为绝对路径
        if not export_path.is_absolute():
            export_path = Path.cwd() / export_path
        # 根据扩展名决定格式
        use_json = export_path.suffix.lower() == ".json"
    else:
        # 使用默认路径：get_app_dir()/"exports"，默认使用 md 格式
        exports_dir = get_app_dir(Scope.USER.value) / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)

        # 生成带时间戳的文件名，默认使用 .md 格式
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = exports_dir / f"conversation_{timestamp}.md"
        use_json = False

    # 确保父目录存在
    export_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if use_json:
            # JSON 格式导出
            stats = get_stats()
            total = stats.get(TOTAL, {})
            export_data = {
                "exported_at": datetime.now().isoformat(),
                "message_count": len(task.messages),
                "total_input_tokens": total.get(UsageField.INPUT_TOKENS, 0),
                "total_output_tokens": total.get(UsageField.OUTPUT_TOKENS, 0),
                "api_calls": total.get(UsageField.API_CALLS, 0),
                "messages": task.messages,
            }

            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
        else:
            # Markdown 格式导出
            stats = get_stats()
            total = stats.get(TOTAL, {})
            md_content = f"""# 对话导出

**导出时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**消息数量**: {len(task.messages)}
**总输入 Token**: {total.get(UsageField.INPUT_TOKENS, 0)}
**总输出 Token**: {total.get(UsageField.OUTPUT_TOKENS, 0)}
**API 调用次数**: {total.get(UsageField.API_CALLS, 0)}

---

"""

            # 添加消息内容
            for i, msg in enumerate(task.messages, 1):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")

                # 根据角色设置标题
                if role == "user":
                    md_content += f"## 用户 (第 {i} 条)\n\n"
                elif role == "assistant":
                    md_content += f"## 助手 (第 {i} 条)\n\n"
                elif role == "system":
                    md_content += f"## 系统 (第 {i} 条)\n\n"
                else:
                    md_content += f"## {role} (第 {i} 条)\n\n"

                # 添加内容
                if isinstance(content, str):
                    md_content += f"{content}\n\n"
                else:
                    # 如果内容是列表或其他类型，转换为字符串
                    md_content += f"```\n{content}\n```\n\n"

                md_content += "---\n\n"

            with open(export_path, "w", encoding="utf-8") as f:
                f.write(md_content)

        ok(f"✓ 对话已导出: {export_path}")
        info(f"导出格式: {'JSON' if use_json else 'Markdown'}")
        info(f"消息数量: {len(task.messages)}")
        info(f"总输入 Token: {total.get(UsageField.INPUT_TOKENS, 0)}")
        info(f"总输出 Token: {total.get(UsageField.OUTPUT_TOKENS, 0)}")
    except Exception as e:
        err(f"导出失败: {e}")
        return False

    return True
