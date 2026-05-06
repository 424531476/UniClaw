"""
UniClaws 控制台启动器模块

提供应用启动相关功能，包括 Logo 显示、欢迎信息展示和 REPL 循环启动。
"""

import os
from PIL import Image
from config import get_config, get_config_dict
from console.run import repl_run


def image_to_ascii(image_path: str, width: int = 80) -> str:
    """
    将图片转换为 ASCII 艺术字

    参数:
        image_path: 图片文件路径
        width: ASCII 艺术的宽度（字符数）

    返回:
        ASCII 艺术字符串
    """
    img = Image.open(image_path)
    gray_img = img.convert("L")
    aspect_ratio = gray_img.height / gray_img.width
    height = int(width * aspect_ratio * 0.5)
    gray_img = gray_img.resize((width, height))
    chars = r"$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\|()1{}[]?-_+~<>i!lI;:,\"^`'.  "
    pixels = list(gray_img.get_flattened_data())
    min_pixel = min(pixels)
    max_pixel = max(pixels)
    pixel_range = max_pixel - min_pixel
    if pixel_range == 0:
        pixel_range = 1
    ascii_art = ""
    for i, pixel in enumerate(pixels):
        normalized_value = (pixel - min_pixel) / pixel_range
        char_index = int(normalized_value * (len(chars) - 1))
        ascii_art += chars[char_index]
        if (i + 1) % width == 0:
            ascii_art += "\n"
    lines = ascii_art.split("\n")
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[len(lines) - 1].strip() == "":
        lines.pop()
    ascii_art = "\n".join(lines) + "\n"
    return ascii_art


def show_logo():
    """
    显示 UniClaws 的 ASCII Logo

    从 assets 目录加载 UniClaws.png 并转换为 ASCII 艺术字显示。
    如果加载失败，仅输出错误信息而不中断程序。
    """
    try:
        logo_path = os.path.join(os.path.dirname(__file__), "..", "assets/UniClaws.png")
        ascii_logo = image_to_ascii(logo_path, width=60)
        print(ascii_logo)
    except Exception as e:
        print(f"加载 Logo 失败: {e}\n")


def show_welcome(config: dict):
    """
    显示欢迎信息和当前配置摘要

    参数:
        config: 配置字典，包含模型名称、权限模式等信息
    """
    print("UniClaws\n")
    print("=" * 60)
    print("🦞 欢迎使用 (UniClaws)")
    print("=" * 60)
    print(f"🤖 模型名称: {config['model_name']}")
    print(f"⚙️  权限模式: {config['permission_mode']}")
    print(f"📂 当前目录: {os.getcwd()}")
    print("=" * 60)
    print()


def launch():
    """
    启动 UniClaws 应用

    完整的启动流程：
    1. 显示 ASCII Logo
    2. 加载配置
    3. 显示欢迎信息
    4. 启动 REPL 交互循环
    """

    show_logo()

    config = get_config_dict(get_config())

    show_welcome(config)

    repl_run(config)
