import base64
import mimetypes
from pathlib import Path
from langchain_core.tools import tool

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg", ".ico"}


def is_image_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in IMAGE_EXTENSIONS


@tool
def ReadImage(file_path: str) -> list | str:
    """
    读取图片文件并返回图片内容供视觉分析。

    支持格式: png, jpg, jpeg, gif, webp, bmp, tiff, svg, ico
    适用于需要识别、分析或理解图片内容的场景。

    Args:
        file_path: 图片文件的路径

    Returns:
        list: 多模态内容块列表（成功时），str: 错误信息（失败时）
    """
    p = Path(file_path)
    if not p.exists():
        return f"错误：文件不存在: {file_path}"
    if p.is_dir():
        return f"错误：{file_path} 是一个目录"

    suffix = p.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        return f"Error: 不支持的图片格式 '{suffix}'，支持的格式: {', '.join(sorted(IMAGE_EXTENSIONS))}"

    try:
        size_kb = p.stat().st_size / 1024
        if size_kb > 20 * 1024:
            return f"Error: 图片文件过大 ({size_kb:.0f} KB)，最大支持 20 MB"

        blocks = [{"type": "text", "text": f"[图片: {p.name}, {size_kb:.0f} KB]"}]

        if suffix == ".svg":
            text = p.read_text(encoding="utf-8")
            blocks.append({"type": "text", "text": text})
        else:
            mime_type = mimetypes.guess_type(str(p))[0] or "image/png"
            data = p.read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{b64}"},
            })

        return blocks
    except Exception as e:
        return f"Error: 读取图片失败: {e}"


tools = [ReadImage]
