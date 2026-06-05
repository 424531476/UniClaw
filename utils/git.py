import os
import subprocess
import tempfile
import time
from typing import Optional
import uuid


def get_git_root(cwd: str) -> Optional[str]:
    """返回 cwd 的 git 根目录,如果不在 git 仓库中则返回 None。"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return r.stdout.strip()
    except Exception:
        return None


def create_worktree(base_dir: str) -> tuple:
    """创建一个临时的 git worktree。

    返回:
        (worktree_path, branch_name)
    异常:
        失败时抛出 subprocess.CalledProcessError 或 OSError。
    """
    branch = f"nano-agent-{uuid.uuid4().hex[:8]}"
    # mkdtemp 给我们一个路径；删除空目录以便 git 可以创建它
    wt_path = tempfile.mkdtemp(prefix="nano-agent-wt-")
    os.rmdir(wt_path)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, wt_path],
        cwd=base_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return wt_path, branch


def remove_worktree(wt_path: str, branch: str, base_dir: str) -> None:
    """移除 git worktree 并删除其分支(尽力而为)。"""
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", wt_path],
            cwd=base_dir,
            capture_output=True,
        )
    except Exception:
        pass
    try:
        subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=base_dir,
            capture_output=True,
        )
    except Exception:
        pass


# ── Git Checkpoints ──────────────────────────────────────────────────────────


def create_checkpoint(cwd: str, message: str = "") -> bool:
    """创建检查点:git stash push --include-untracked

    在 assistant turn 开始前调用,捕获当前工作目录状态。
    如果没有变更则静默返回 False(git stash 无变更时返回非 0)。
    message 使用用户消息的前 50 个字符,便于在 stash list 中识别。

    Args:
        cwd: 工作目录路径
        message: 检查点描述,默认使用时间戳

    Returns:
        bool: 是否成功创建(无变更时返回 False)
    """
    git_root = get_git_root(cwd)
    if not git_root:
        return False
    # 截取前 50 字符,去除换行,避免 git message 解析问题
    if message:
        msg = message.replace("\n", " ")[:50]
    else:
        msg = f"checkpoint-{time.strftime('%Y%m%d-%H%M%S')}"
    result = subprocess.run(
        ["git", "stash", "push", "--include-untracked", "-m", msg],
        cwd=git_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0


def restore_checkpoint(cwd: str, index: int = 0) -> tuple:
    """恢复检查点:git stash pop stash@{index}

    Args:
        cwd: 工作目录路径
        index: 检查点序号,默认 0(最近的)

    Returns:
        (success, message) — success 是否成功,message 为结果描述或错误信息
    """
    git_root = get_git_root(cwd)
    if not git_root:
        return False, "不在 git 仓库中"
    result = subprocess.run(
        ["git", "stash", "pop", f"stash@{{{index}}}"],
        cwd=git_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        return True, f"已恢复到检查点 stash@{{{index}}}"
    stderr = (result.stderr or "").strip()
    if "would be overwritten" in stderr:
        # 自动暂存当前修改,再恢复检查点
        stash_result = subprocess.run(
            ["git", "stash", "push", "-m", "user-changes-before-undo"],
            cwd=git_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if stash_result.returncode == 0:
            # 再次尝试恢复检查点
            result = subprocess.run(
                ["git", "stash", "pop", f"stash@{{{index + 1}}}"],
                cwd=git_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                return True, f"已恢复到检查点 stash@{{{index}}}（当前修改已暂存,可用 git stash pop 恢复）"
            return False, "恢复检查点失败,当前修改已暂存在 stash 中"
        return False, "暂存当前修改失败,请手动 commit 或 stash"
    return False, stderr or "没有可恢复的检查点"


def list_checkpoints(cwd: str) -> str:
    """列出所有检查点:git stash list

    Args:
        cwd: 工作目录路径

    Returns:
        str: 检查点列表文本,无检查点时返回提示信息
    """
    git_root = get_git_root(cwd)
    if not git_root:
        return "不在 git 仓库中"
    result = subprocess.run(
        ["git", "stash", "list"],
        cwd=git_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or "").strip() or "没有检查点"
