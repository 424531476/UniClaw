"""检查点系统 - 支持两种模式：文件快照 和 git stash。

自动检测：有 git 用 git_stash,否则用 file。
"""

import difflib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import pathspec

from uniclaw.utils.git import (
    get_git_root,
    is_git_installed,
    has_git_commit,
    git_create_checkpoint,
    git_pop_checkpoint,
    git_apply_checkpoint,
    git_delete_checkpoint,
    git_list_checkpoints,
    git_diff_checkpoint,
    git_diff_current,
    git_diff_between,
)


# ── 通用函数 ──────────────────────────────────────────────────────────────────

def _get_checkpoint_dir(cwd: Path) -> Path:
    """获取检查点存储目录。"""
    return cwd / ".UniClaw" / "checkpoints"


def _load_index(checkpoint_dir: Path) -> list:
    """加载检查点索引文件,返回按时间倒序排列的检查点列表。

    索引文件路径为 `<checkpoint_dir>/index.json`,每个条目结构:
        {
            "id": str,      # 检查点唯一标识(时间戳)
            "message": str, # 检查点描述信息
            "time": str     # 创建时间(ISO 格式字符串)
        }

    文件不存在或解析失败时返回空列表,不抛异常。

    Args:
        checkpoint_dir: 检查点存储目录路径(由 _get_checkpoint_dir 返回)

    Returns:
        list[dict]: 按 time 字段倒序排列的检查点列表,索引 0 为最新
    """
    index_file = checkpoint_dir / "index.json"
    if index_file.exists():
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            return sorted(data, key=lambda x: x.get("time", ""), reverse=True)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_index(checkpoint_dir: Path, index: list) -> None:
    """保存检查点索引。"""
    index_file = checkpoint_dir / "index.json"
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_gitignore(cwd: Path) -> Optional[pathspec.PathSpec]:
    """加载 .gitignore 文件并编译为 PathSpec 匹配器。

    读取工作目录下的 .gitignore,将其 gitwild 模式规则编译为
    pathspec.PathSpec 对象,供 _get_all_files 等函数用于过滤
    应被忽略的文件(非 git 仓库场景下的替代方案)。

    Args:
        cwd: 工作目录路径,函数会在此目录下查找 .gitignore

    Returns:
        pathspec.PathSpec: 编译后的匹配器,可用于 match_file() 判断文件是否被忽略
        None: .gitignore 不存在、读取失败或解码错误时返回
    """
    gitignore = cwd / ".gitignore"
    if gitignore.exists():
        try:
            lines = gitignore.read_text(encoding="utf-8").splitlines()
            return pathspec.PathSpec.from_lines("gitwild", lines)
        except (OSError, UnicodeDecodeError):
            pass
    return None


def _get_all_files(cwd: Path) -> list[str]:
    """获取工作目录下文件列表(相对路径)。

    有 git 时使用 git ls-files,否则扫描目录并应用 .gitignore。
    """
    # 有 git 时使用 git
    git_root = get_git_root(cwd)
    # 没有 git 仓库但安装了 git,自动 init
    if not git_root and is_git_installed():
        subprocess.run(
            ["git", "init"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        git_root = get_git_root(cwd)
    if git_root:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=git_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().splitlines() if f]

    # 无 git 时扫描目录
    gitignore_spec = _load_gitignore(cwd)
    exclude_dirs = {".UniClaw", ".git", "__pycache__", "node_modules", ".venv", "venv"} if not gitignore_spec else set()

    files = []
    for root, dirs, filenames in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for filename in filenames:
            filepath = Path(root) / filename
            rel_path = str(filepath.relative_to(cwd))
            if gitignore_spec and gitignore_spec.match_file(rel_path):
                continue
            files.append(rel_path)
    return files


def _read_file_content(filepath: Path) -> Optional[str]:
    """安全读取文件内容。"""
    try:
        return filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _generate_diff(old_content: str, new_content: str, old_label: str, new_label: str) -> str:
    """生成 unified diff。"""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=old_label, tofile=new_label)
    return "".join(diff)


# ── 文件快照模式 ──────────────────────────────────────────────────────────────

def _file_create_checkpoint(cwd: Path, message: str = "") -> bool:
    """文件快照模式：复制所有文件到检查点目录。"""
    all_files = _get_all_files(cwd)
    if not all_files:
        return False

    checkpoint_dir = _get_checkpoint_dir(cwd)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    cp_id = f"cp_{time.strftime('%Y%m%d_%H%M%S')}"
    cp_path = checkpoint_dir / cp_id
    files_path = cp_path / "files"
    files_path.mkdir(parents=True, exist_ok=True)

    copied_files = []
    for rel_path in all_files:
        src = cwd / rel_path
        dst = files_path / rel_path
        if src.exists() and src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied_files.append(rel_path)

    if not copied_files:
        shutil.rmtree(cp_path, ignore_errors=True)
        return False

    msg = message.replace("\n", " ")[:50] if message else cp_id
    meta = {
        "id": cp_id,
        "message": msg,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": copied_files,
        "mode": "file",
    }
    (cp_path / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    index = _load_index(checkpoint_dir)
    index.append({"id": cp_id, "message": msg, "time": meta["time"]})
    _save_index(checkpoint_dir, index)

    return True


def _file_restore_checkpoint(cwd: Path, index: int = 0) -> tuple[bool, str]:
    """文件快照模式：从检查点目录恢复文件。"""
    checkpoint_dir = _get_checkpoint_dir(cwd)
    if not checkpoint_dir.exists():
        return False, "没有检查点"

    cp_index = _load_index(checkpoint_dir)
    if not cp_index:
        return False, "没有检查点"

    if index < 0 or index >= len(cp_index):
        return False, f"检查点序号 {index} 不存在(共 {len(cp_index)} 个)"

    cp_info = cp_index[index]
    cp_path = checkpoint_dir / cp_info["id"]

    if not cp_path.exists():
        return False, f"检查点目录不存在: {cp_info['id']}"

    meta_file = cp_path / "meta.json"
    if not meta_file.exists():
        return False, f"检查点元数据不存在: {cp_info['id']}"

    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return False, f"读取检查点元数据失败: {e}"

    files_path = cp_path / "files"
    restored = []
    for rel_path in meta.get("files", []):
        src = files_path / rel_path
        dst = cwd / rel_path
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(rel_path)

    return True, f"已恢复检查点 {cp_info['id']},恢复了 {len(restored)} 个文件"


def _file_pop_checkpoint(cwd: Path, index: int = 0) -> tuple[bool, str]:
    """文件快照模式：恢复检查点并删除。"""
    success, msg = _file_restore_checkpoint(cwd, index)
    if success:
        # 恢复成功后删除检查点
        _file_delete_checkpoint(cwd, index)
    return success, msg


def _file_apply_checkpoint(cwd: Path, index: int = 0) -> tuple[bool, str]:
    """文件快照模式：恢复检查点但保留。"""
    return _file_restore_checkpoint(cwd, index)


def _file_delete_checkpoint(cwd: Path, index: int = 0) -> tuple[bool, str]:
    """文件快照模式：删除检查点。"""
    checkpoint_dir = _get_checkpoint_dir(cwd)
    if not checkpoint_dir.exists():
        return False, "没有检查点"

    cp_index = _load_index(checkpoint_dir)
    if not cp_index:
        return False, "没有检查点"

    if index < 0 or index >= len(cp_index):
        return False, f"检查点序号 {index} 不存在(共 {len(cp_index)} 个)"

    cp_info = cp_index[index]
    cp_path = checkpoint_dir / cp_info["id"]

    # 删除检查点目录
    if cp_path.exists():
        shutil.rmtree(cp_path)

    # 从索引中移除
    cp_index.pop(index)
    _save_index(checkpoint_dir, cp_index)

    return True, f"已删除检查点: {cp_info['id']}"


def _file_list_checkpoints(cwd: Path) -> str:
    """文件快照模式：列出所有检查点。"""
    checkpoint_dir = _get_checkpoint_dir(cwd)
    if not checkpoint_dir.exists():
        return "没有检查点"

    cp_index = _load_index(checkpoint_dir)
    if not cp_index:
        return "没有检查点"

    lines = []
    for i, cp in enumerate(cp_index):
        lines.append(f"[{i}] {cp['id']} - {cp['message']} ({cp['time']})")

    return "\n".join(lines)


def _file_diff_two_dirs(
    files_a: list[str],
    files_b: list[str],
    dir_a: Path,
    dir_b: Path,
    label_a: str,
    label_b: str,
    empty_msg: str,
) -> str:
    """文件快照模式：比较两个目录的文件差异。

    Args:
        files_a: 第一个目录的文件列表
        files_b: 第二个目录的文件列表
        dir_a: 第一个目录路径
        dir_b: 第二个目录路径
        label_a: 第一个目录的标签
        label_b: 第二个目录的标签
        empty_msg: 无差异时的提示信息

    Returns:
        str: diff 文本
    """
    all_files = sorted(set(files_a) | set(files_b))
    diffs = []

    for rel_path in all_files:
        content_a = _read_file_content(dir_a / rel_path)
        content_b = _read_file_content(dir_b / rel_path)

        if content_a is None and content_b is None:
            continue

        if content_a is None:
            diffs.append(f"+++ 仅在 {label_b}: {rel_path}\n{content_b}")
        elif content_b is None:
            diffs.append(f"+++ 仅在 {label_a}: {rel_path}\n{content_a}")
        else:
            diff = _generate_diff(content_a, content_b, f"{label_a}:{rel_path}", f"{label_b}:{rel_path}")
            if diff:
                diffs.append(diff)

    return "\n".join(diffs) if diffs else empty_msg


def _get_checkpoint_meta(checkpoint_dir: Path, index: int) -> tuple[dict, Path, str]:
    """获取检查点元数据和路径。

    Args:
        checkpoint_dir: 检查点目录
        index: 倒序索引（0 = 最新）

    Returns:
        (meta, cp_path, error_msg) — 如果出错,meta 为空字典,error_msg 非空
    """
    cp_index = _load_index(checkpoint_dir)

    if index < 0 or index >= len(cp_index):
        return {}, Path(), f"检查点序号 {index} 不存在"

    cp_info = cp_index[index]
    cp_path = checkpoint_dir / cp_info["id"]
    meta_file = cp_path / "meta.json"

    if not meta_file.exists():
        return {}, Path(), "检查点元数据不存在"

    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}, Path(), "读取检查点元数据失败"

    return meta, cp_path, ""


def _file_diff_checkpoint(cwd: Path, index: int = 0) -> str:
    """文件快照模式：查看检查点与当前文件的差异。"""
    checkpoint_dir = _get_checkpoint_dir(cwd)
    if not checkpoint_dir.exists():
        return "没有检查点"

    meta, cp_path, err = _get_checkpoint_meta(checkpoint_dir, index)
    if err:
        return err

    return _file_diff_two_dirs(
        files_a=meta.get("files", []),
        files_b=_get_all_files(cwd),
        dir_a=cp_path / "files",
        dir_b=cwd,
        label_a="checkpoint",
        label_b="current",
        empty_msg="检查点与当前文件没有差异",
    )


def _file_diff_current(cwd: Path) -> str:
    """文件快照模式：查看当前未提交的变更。"""
    checkpoint_dir = _get_checkpoint_dir(cwd)
    if checkpoint_dir.exists():
        cp_index = _load_index(checkpoint_dir)
        if cp_index:
            return _file_diff_checkpoint(cwd, 0)

    return "当前没有检查点可供对比"


def _file_diff_between(cwd: Path, index_a: int, index_b: int) -> str:
    """文件快照模式：比较两个检查点的差异。"""
    checkpoint_dir = _get_checkpoint_dir(cwd)
    if not checkpoint_dir.exists():
        return "没有检查点"

    meta_a, cp_a, err_a = _get_checkpoint_meta(checkpoint_dir, index_a)
    if err_a:
        return err_a

    meta_b, cp_b, err_b = _get_checkpoint_meta(checkpoint_dir, index_b)
    if err_b:
        return err_b

    return _file_diff_two_dirs(
        files_a=meta_a.get("files", []),
        files_b=meta_b.get("files", []),
        dir_a=cp_a / "files",
        dir_b=cp_b / "files",
        label_a=f"checkpoint[{index_a}]",
        label_b=f"checkpoint[{index_b}]",
        empty_msg="两个检查点没有差异",
    )


# ── 统一接口 ──────────────────────────────────────────────────────────────────

def create_checkpoint(cwd: Path, message: str = "") -> bool:
    """创建检查点(根据配置选择模式)。"""
    if has_git_commit(cwd):
        return git_create_checkpoint(cwd, message)
    return _file_create_checkpoint(cwd, message)


def pop_checkpoint(cwd: Path, index: int = 0) -> tuple[bool, str]:
    """恢复检查点并删除(根据配置选择模式)。"""
    if has_git_commit(cwd):
        return git_pop_checkpoint(cwd, index)
    return _file_pop_checkpoint(cwd, index)


def apply_checkpoint(cwd: Path, index: int = 0) -> tuple[bool, str]:
    """恢复检查点但保留(根据配置选择模式)。"""
    if has_git_commit(cwd):
        return git_apply_checkpoint(cwd, index)
    return _file_apply_checkpoint(cwd, index)


def list_checkpoints(cwd: Path) -> str:
    """列出所有检查点(根据配置选择模式)。"""
    if has_git_commit(cwd):
        return git_list_checkpoints(cwd)
    return _file_list_checkpoints(cwd)


def diff_checkpoint(cwd: Path, index: int = 0) -> str:
    """查看检查点的变更内容(根据配置选择模式)。"""
    if has_git_commit(cwd):
        return git_diff_checkpoint(cwd, index)
    return _file_diff_checkpoint(cwd, index)


def diff_current(cwd: Path) -> str:
    """查看当前未提交的变更(根据配置选择模式)。"""
    if has_git_commit(cwd):
        return git_diff_current(cwd)
    return _file_diff_current(cwd)


def diff_between(cwd: Path, index_a: int, index_b: int) -> str:
    """比较两个检查点的差异(根据配置选择模式)。"""
    if has_git_commit(cwd):
        return git_diff_between(cwd, index_a, index_b)
    return _file_diff_between(cwd, index_a, index_b)


def delete_checkpoint(cwd: Path, index: int = 0) -> tuple[bool, str]:
    """删除检查点(根据配置选择模式)。"""
    if has_git_commit(cwd):
        return git_delete_checkpoint(cwd, index)
    return _file_delete_checkpoint(cwd, index)
