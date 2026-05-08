import difflib
from pathlib import Path
from langchain_core.tools import tool


def _read_preserving_newlines(p: Path, encoding: str = "utf-8") -> str:
    with p.open(encoding=encoding, errors="replace", newline="") as f:
        return f.read()


# ── Diff helpers ──────────────────────────────────────────────────────────


def generate_unified_diff(
    old: str, new: str, filename: str, context_lines: int = 3
) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=context_lines,
    )
    return "".join(diff)


# ── Read ─────────────────────────────────────────────────────────────────
@tool
def Read(
    file_path: str, limit: int = None, offset: int = None, encoding: str = "utf-8"
) -> str:
    """
    读取文件内容并返回带行号的文本。

    Args:
        file_path: 要读取的文件路径
        limit: 可选，限制读取的行数。如果未指定，则读取从offset开始的所有行
        offset: 可选，起始行偏移量（从0开始）。默认为0
        encoding: 可选，文件编码格式。默认为"utf-8"

    Returns:
        str: 带行号的文件内容字符串，格式为"行号\t内容"。
             如果文件不存在或出错，返回错误信息字符串
    """
    p = Path(file_path)
    if not p.exists():
        return f"Error: file not found: {file_path}"
    if p.is_dir():
        return f"Error: {file_path} is a directory"

    try:
        lines = _read_preserving_newlines(p, encoding).splitlines(keepends=True)
        start = offset or 0
        chunk = lines[start : start + limit] if limit else lines[start:]
        if not chunk:
            return "(empty file)"
        return "".join(f"{start + i + 1:6}\t{l}" for i, l in enumerate(chunk))
    except Exception as e:
        return f"Error: {e}"


# ── Write ─────────────────────────────────────────────────────────────────
@tool
def Write(file_path: str, content: str) -> str:
    """
    写入文件内容，支持创建新文件或更新现有文件。

    该函数会将指定内容写入文件，如果文件不存在则创建新文件并返回创建信息；
    如果文件已存在则比较新旧内容的差异，并返回差异报告。函数会自动创建
    必要的父目录，并使用UTF-8编码保存文件。

    Args:
        file_path (str): 要写入的文件路径。如果父目录不存在会自动创建。
        content (str): 要写入的文件内容字符串。

    Returns:
        str: 操作结果信息。可能的返回值包括：
             - 创建新文件时：返回 "Created {file_path} ({lc} lines)"，包含行数信息
             - 文件无变化时：返回 "No changes in {file_path}"
             - 文件更新时：返回 "File updated — {file_path}:" 后跟差异报告
             - 发生错误时：返回 "Error: {e}"，包含具体错误信息
    """
    p = Path(file_path)
    try:
        # 检查文件是否存在，并读取旧内容（如果存在）
        is_new = not p.exists()
        old_content = "" if is_new else _read_preserving_newlines(p)

        # 确保父目录存在，然后写入新内容
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="")

        # 根据文件是否为新创建，返回不同的结果信息
        if is_new:
            lc = content.count("\n") + (
                1 if content and not content.endswith("\n") else 0
            )
            return f"Created {file_path} ({lc} lines)"

        # 对于已存在的文件，生成并返回差异报告
        diff = generate_unified_diff(old_content, content, p.name)
        if not diff:
            return f"No changes in {file_path}"
        return f"File updated — {file_path}:\n\n{diff}"
    except Exception as e:
        return f"Error: {e}"


# ── Edit ──────────────────────────────────────────────────────────────────
@tool
def Edit(
    file_path: str, old_string: str, new_string: str, replace_all: bool = False
) -> str:
    """
    编辑文件内容，将指定的旧字符串替换为新字符串。

    该函数支持精确的字符串替换，能够自动处理不同的换行符格式（CRLF/LF），
    并生成统一的差异报告。适用于需要精确控制文件内容修改的场景。

    Args:
        file_path (str): 要编辑的文件路径。如果文件不存在，将返回错误信息。
        old_string (str): 要被替换的原始字符串。必须与文件中的内容完全匹配，
                         包括所有前导空格/缩进和尾部换行符。
        new_string (str): 用于替换的新字符串。
        replace_all (bool): 是否替换所有匹配项。默认为False，只替换第一个匹配项。
                           如果为True且存在多个匹配项，将全部替换。

    Returns:
        str: 操作结果信息。成功时返回包含文件名的变更摘要和统一差异报告；
             失败时返回错误信息，可能的错误包括：
             - 文件未找到
             - 旧字符串未在文件中找到
             - 旧字符串出现多次但未指定replace_all
             - 其他异常错误

    Note:
        - 函数会自动检测文件的换行符格式（CRLF或LF），并在写入时保持原格式
        - 比较时会先将所有内容标准化为LF格式进行匹配
        - 生成的差异报告使用统一差异格式（unified diff）
    """
    p = Path(file_path)
    if not p.exists():
        return f"Error: file not found: {file_path}"
    try:
        # 读取文件内容并保持原始换行符格式
        content = _read_preserving_newlines(p)

        # 检测文件的换行符格式，判断是否为纯CRLF格式
        crlf_count = content.count("\r\n")
        lf_count = content.count("\n")
        is_pure_crlf = crlf_count > 0 and crlf_count == lf_count

        # 将所有内容标准化为LF格式以便进行精确匹配
        content_norm = content.replace("\r\n", "\n")
        old_norm = old_string.replace("\r\n", "\n")
        new_norm = new_string.replace("\r\n", "\n")

        # 统计匹配次数并进行验证
        count = content_norm.count(old_norm)
        if count == 0:
            return (
                "错误：在文件中未找到 old_string。请确保完全匹配，"
                "包括所有精确的前导空格/缩进和尾随换行符。"
            )
        if count > 1 and not replace_all:
            return (
                f"错误：old_string 出现了 {count} 次。"
                "请提供更多上下文以使其唯一，或使用 replace_all=true。"
            )

        # 执行替换操作
        if replace_all:
            new_content_norm = content_norm.replace(old_norm, new_norm)
        else:
            new_content_norm = content_norm.replace(old_norm, new_norm, 1)

        # 根据原始文件格式恢复相应的换行符格式
        if is_pure_crlf:
            final_content = new_content_norm.replace("\n", "\r\n")
            old_content_final = content
        else:
            final_content = new_content_norm
            old_content_final = content_norm

        # 写入文件并生成差异报告
        p.write_text(final_content, encoding="utf-8", newline="")
        diff = generate_unified_diff(old_content_final, final_content, p.name)
        return f"Changes applied to {p.name}:\n\n{diff}"
    except Exception as e:
        return f"Error: {e}"


# ── Glob ──────────────────────────────────────────────────────────────────
@tool
def Glob(pattern: str, path: str = None, cwd: str = None) -> str:
    """
    根据通配符模式搜索匹配的文件路径。

    Args:
        pattern (str): 文件匹配模式，支持通配符（如 *.txt, **/*.py 等）
        path (str, optional): 搜索的起始目录路径。如果未提供，则使用 cwd 或当前工作目录
        cwd (str, optional): 当前工作目录，当 path 未提供时作为备选

    Returns:
        str: 匹配的文件路径列表（最多500个），每行一个路径；如果没有匹配则返回 "No files matched"；发生错误时返回错误信息
    """
    # 确定搜索的基础目录路径
    base = Path(path) if path else (Path(cwd) if cwd else Path.cwd())
    try:
        # 执行通配符匹配并排序结果
        matches = sorted(base.glob(pattern))
        if not matches:
            return "No files matched"
        # 返回最多500个匹配结果
        return "\n".join(str(m) for m in matches[:500])
    except Exception as e:
        return f"Error: {e}"


tools = [Read, Write, Edit, Glob]
