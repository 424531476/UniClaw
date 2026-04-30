import os
import subprocess
import tempfile
from typing import Optional
import uuid


def get_git_root(cwd: str) -> Optional[str]:
    """返回 cwd 的 git 根目录，如果不在 git 仓库中则返回 None。"""
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

    返回：
        (worktree_path, branch_name)
    异常：
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
    """移除 git worktree 并删除其分支（尽力而为）。"""
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
