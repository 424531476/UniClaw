import asyncio
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Optional
import uuid


async def _run_git(*args: str, cwd: str | None = None, check: bool = False) -> subprocess.CompletedProcess:
    """异步执行 git 命令,返回 CompletedProcess 风格的结果。"""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
    result = subprocess.CompletedProcess(
        args=args, returncode=proc.returncode, stdout=stdout, stderr=stderr
    )
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, stdout, stderr)
    return result


async def get_git_root(root_dir: Path) -> Optional[str]:
    """返回 root_dir 的 git 根目录,如果不在 git 仓库中则返回 None。"""
    try:
        r = await _run_git("git", "rev-parse", "--show-toplevel", cwd=str(root_dir), check=True)
        return r.stdout.strip()
    except Exception:
        return None


async def is_git_installed() -> bool:
    """检测 git 是否已安装。"""
    try:
        result = await _run_git("git", "--version")
        return result.returncode == 0
    except FileNotFoundError:
        return False


async def is_git_repo(root_dir: Path = None) -> bool:
    """检测是否在 git 仓库中(已 git init)。

    Args:
        root_dir: 仓库根目录路径

    Returns:
        bool: 是否在 git 仓库中
    """
    if root_dir:
        return await get_git_root(root_dir) is not None
    return True


async def has_git_commit(root_dir: Path = None) -> bool:
    """检测 git 仓库是否有至少一次 commit。

    git stash 需要至少一次 commit 才能使用。

    Args:
        root_dir: 仓库根目录路径

    Returns:
        bool: 是否有 commit
    """
    if not await is_git_repo(root_dir):
        return False
    try:
        result = await _run_git("git", "rev-parse", "HEAD", cwd=str(root_dir) if root_dir else None)
        return result.returncode == 0
    except Exception:
        return False


async def create_worktree(base_dir: Path) -> tuple:
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
    await _run_git(
        "git", "worktree", "add", "-b", branch, wt_path,
        cwd=str(base_dir), check=True,
    )
    return wt_path, branch


async def remove_worktree(wt_path: Path, branch: str, base_dir: Path) -> None:
    """移除 git worktree 并删除其分支(尽力而为)。"""
    try:
        await _run_git("git", "worktree", "remove", "--force", str(wt_path), cwd=str(base_dir))
    except Exception:
        pass
    try:
        await _run_git("git", "branch", "-D", branch, cwd=str(base_dir))
    except Exception:
        pass


# ── Git Stash 检查点 ──────────────────────────────────────────────────────────


async def git_create_checkpoint(root_dir: Path, message: str = "") -> bool:
    """创建检查点:git stash push + apply

    在 assistant turn 开始前调用,捕获当前工作目录状态。
    创建后立即 apply 恢复,不影响工作区内容。
    如果没有变更则静默返回 False(git stash 无变更时返回非 0)。
    message 使用用户消息的前 50 个字符,便于在 stash list 中识别。

    Args:
        root_dir: 仓库根目录路径
        message: 检查点描述,默认使用时间戳

    Returns:
        bool: 是否成功创建(无变更时返回 False)
    """
    git_root = await get_git_root(root_dir)
    if not git_root:
        return False
    # 截取前 50 字符,去除换行,避免 git message 解析问题
    if message:
        msg = message.replace("\n", " ")[:50]
    else:
        msg = f"checkpoint-{time.strftime('%Y%m%d-%H%M%S')}"
    # 第一步:stash push 保存当前状态
    result = await _run_git(
        "git", "stash", "push", "--include-untracked", "-m", msg,
        cwd=str(git_root),
    )
    if result.returncode != 0:
        return False
    # 第二步:立即 apply 恢复工作区
    await _run_git("git", "stash", "apply", cwd=str(git_root))
    return True


async def _git_restore_helper(root_dir: Path, index: int, use_pop: bool) -> tuple[bool, str]:
    """git stash 恢复的内部实现,供 git_pop_checkpoint 和 git_apply_checkpoint 调用。

    处理流程:
    1. 校验当前目录是否在 git 仓库内
    2. 根据 use_pop 决定执行 `git stash pop` 或 `git stash apply`
    3. 若 stash 恢复时出现冲突(工作区有未提交的同名文件变更),
       采用强制恢复策略:
       a. `git checkout HEAD -- .` 丢弃当前工作区所有修改
       b. `git clean -fd` 删除未跟踪的文件
       c. 重新执行 stash pop/apply

    Args:
        root_dir: 仓库根目录路径,用于定位 git 仓库
        index: stash 序号,对应 `stash@{index}`,0 表示最近一次
        use_pop: True 使用 `git stash pop`(恢复并从 stash 列表中删除),
                 False 使用 `git stash apply`(恢复但保留 stash 记录)

    Returns:
        (success, message) 元组:
        - success: 操作是否成功
        - message: 成功时为操作描述,失败时为错误信息
    """
    git_root = await get_git_root(root_dir)
    if not git_root:
        return False, "不在 git 仓库中"

    cmd = "pop" if use_pop else "apply"
    action = "恢复并删除" if use_pop else "恢复"

    # 先尝试 stash pop/apply
    result = await _run_git(
        "git", "stash", cmd, f"stash@{{{index}}}",
        cwd=str(git_root),
    )
    if result.returncode == 0:
        return True, f"已{action}检查点 stash@{{{index}}}"

    stderr = (result.stderr or "").strip()
    # 冲突时,使用 git checkout + git clean 强制恢复
    if "would be overwritten" in stderr or "already exists" in stderr or "conflict" in stderr.lower():
        # 1. 丢弃当前工作区修改
        await _run_git("git", "checkout", "HEAD", "--", ".", cwd=str(git_root))
        # 2. 删除未跟踪的文件
        await _run_git("git", "clean", "-fd", cwd=str(git_root))
        # 3. 从 stash 恢复
        result = await _run_git(
            "git", "stash", cmd, f"stash@{{{index}}}",
            cwd=str(git_root),
        )
        if result.returncode == 0:
            return True, f"已{action}检查点 stash@{{{index}}}"
        return False, f"{action}检查点失败: {(result.stderr or '').strip()}"

    return False, stderr or f"没有可{action}的检查点"


async def git_pop_checkpoint(root_dir: Path, index: int = 0) -> tuple[bool, str]:
    """恢复检查点并删除:git stash pop stash@{index}"""
    return await _git_restore_helper(root_dir, index, use_pop=True)


async def git_apply_checkpoint(root_dir: Path, index: int = 0) -> tuple[bool, str]:
    """恢复检查点但保留:git stash apply stash@{index}"""
    return await _git_restore_helper(root_dir, index, use_pop=False)


async def git_delete_checkpoint(root_dir: Path, index: int = 0) -> tuple[bool, str]:
    """删除检查点:git stash drop stash@{index}

    Args:
        root_dir: 仓库根目录路径
        index: 检查点序号,默认 0(最近的)

    Returns:
        (success, message) — success 是否成功,message 为结果描述或错误信息
    """
    git_root = await get_git_root(root_dir)
    if not git_root:
        return False, "不在 git 仓库中"
    # 先获取 stash 信息用于提示
    list_result = await _run_git("git", "stash", "list", cwd=str(git_root))
    stash_lines = (list_result.stdout or "").strip().splitlines()
    if index < 0 or index >= len(stash_lines):
        return False, f"检查点序号 {index} 不存在(共 {len(stash_lines)} 个)"
    stash_name = stash_lines[index]
    # 删除
    result = await _run_git(
        "git", "stash", "drop", f"stash@{{{index}}}",
        cwd=str(git_root),
    )
    if result.returncode == 0:
        return True, f"已删除检查点: {stash_name}"
    return False, (result.stderr or "").strip() or "删除检查点失败"


async def git_diff_checkpoint(root_dir: Path, index: int = 0) -> str:
    """查看检查点与当前文件的差异:git diff stash@{index}

    Args:
        root_dir: 仓库根目录路径
        index: 检查点序号,默认 0(最近的)

    Returns:
        str: 变更的 diff 文本,无变更时返回提示信息
    """
    git_root = await get_git_root(root_dir)
    if not git_root:
        return "不在 git 仓库中"
    result = await _run_git(
        "git", "diff", f"stash@{{{index}}}",
        cwd=str(git_root),
    )
    return (result.stdout or "").strip() or "检查点与当前文件没有差异"


async def git_diff_current(root_dir: Path) -> str:
    """查看当前未提交的变更:git diff

    Args:
        root_dir: 仓库根目录路径

    Returns:
        str: 变更的 diff 文本,无变更时返回提示信息
    """
    git_root = await get_git_root(root_dir)
    if not git_root:
        return "不在 git 仓库中"
    result = await _run_git("git", "diff", cwd=str(git_root))
    return (result.stdout or "").strip() or "当前没有未提交的变更"


async def git_diff_between(root_dir: Path, index_a: int, index_b: int) -> str:
    """比较两个检查点的差异:git diff stash@{a} stash@{b}

    Args:
        root_dir: 仓库根目录路径
        index_a: 第一个检查点序号
        index_b: 第二个检查点序号

    Returns:
        str: 变更的 diff 文本,无差异时返回提示信息
    """
    git_root = await get_git_root(root_dir)
    if not git_root:
        return "不在 git 仓库中"
    result = await _run_git(
        "git", "diff", f"stash@{{{index_a}}}", f"stash@{{{index_b}}}",
        cwd=str(git_root),
    )
    return (result.stdout or "").strip() or "两个检查点没有差异"


async def git_list_checkpoints(root_dir: Path) -> str:
    """列出所有检查点:git stash list

    Args:
        root_dir: 仓库根目录路径

    Returns:
        str: 检查点列表文本,无检查点时返回提示信息
    """
    git_root = await get_git_root(root_dir)
    if not git_root:
        return "不在 git 仓库中"
    result = await _run_git("git", "stash", "list", cwd=str(git_root))
    return (result.stdout or "").strip() or "没有检查点"
