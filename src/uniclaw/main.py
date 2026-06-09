import argparse
import asyncio
import os
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

    if args.mode == "wechat":
        from uniclaw.wechat.launcher import launch
    else:
        from uniclaw.console.launcher import launch

    launch()


if __name__ == "__main__":
    main()
