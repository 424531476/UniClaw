import argparse
import asyncio
import os
import threading
import warnings

# jieba 0.42.1 使用了非 raw 字符串的正则表达式，在 Python 3.12+ 触发 SyntaxWarning
warnings.filterwarnings("ignore", category=SyntaxWarning)
from uniclaw.config import is_first_launch, run_setup_wizard


def main():
    parser = argparse.ArgumentParser(description="UniClaw - AI Agent")
    parser.add_argument(
        "--mode",
        choices=["console", "wechat"],
        default="console",
        help="启动模式: console(控制台, 默认) 或 wechat(微信)",
    )
    args = parser.parse_args()

    # 首次启动引导(console 和 wechat 共用)
    if is_first_launch():
        asyncio.run(run_setup_wizard())

    # 后台预加载 tiktoken 编码器,避免首次调用时同步下载阻塞事件循环
    def _preload_tiktoken():
        try:
            import tiktoken
            tiktoken.get_encoding("cl100k_base")
            tiktoken.get_encoding("o200k_base")
        except Exception:
            pass

    # 后台预加载 OpenAI SDK 模块,避免首次 API 调用时同步 import 阻塞事件循环
    def _preload_openai():
        try:
            import openai.resources.audio  # noqa: F401
            import openai.types.audio  # noqa: F401
        except Exception:
            pass

    # 后台预加载 MCP 模块,避免首次使用 MCP 工具时同步 import 阻塞事件循环
    def _preload_mcp():
        try:
            import mcp  # noqa: F401
        except Exception:
            pass

    threading.Thread(target=_preload_tiktoken, daemon=True).start()
    threading.Thread(target=_preload_openai, daemon=True).start()
    threading.Thread(target=_preload_mcp, daemon=True).start()

    if args.mode == "wechat":
        from uniclaw.wechat.launcher import launch
    else:
        from uniclaw.console.launcher import launch

    launch()


if __name__ == "__main__":
    main()
