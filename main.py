import os
from config import get_config
from console.run import repl_run
from llm import chat
from tools.multi_agent.tools import agent_create, list_agent_definitions
from tools.shell import search_files_with_everything, Bash
from utils.truncation import truncate_text_by_lines
from PIL import Image


def image_to_ascii(image_path: str, width: int = 80) -> str:
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
    while lines and lines[-1].strip() == "":
        lines.pop()
    ascii_art = "\n".join(lines) + "\n"
    return ascii_art


def main():
    # 从环境变量获取原始工作目录，并立即切换过去
    original_cwd = os.environ.get("ORIGINAL_DIR")
    if original_cwd:
        os.chdir(original_cwd)

    try:
        logo_path = os.path.join(os.path.dirname(__file__), "assets/UniClaws.png")
        ascii_logo = image_to_ascii(logo_path, width=60)
        print(ascii_logo)

    except Exception as e:
        print(f"加载 Logo 失败: {e}\n")

    config = get_config().to_dict()

    print("UniClaws\n")
    print("=" * 60)
    print("🦞 欢迎使用 (UniClaws)")
    print("=" * 60)
    print(f"🤖 模型名称: {config["model_name"]}")
    print(f"⚙️  权限模式: {config["permission_mode"]}")
    print(f"📂 当前目录: {os.getcwd()}")
    print("=" * 60)
    print()

    repl_run(config)


if __name__ == "__main__":
    main()
