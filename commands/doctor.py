"""环境诊断命令"""

import os
import shutil
import subprocess
from pathlib import Path
from agent import AgentTask
from console.ui import info, ok, warn, err
from context import APP_NAME


def _check_python() -> str:
    import sys
    v = sys.version_info
    return f"Python {v.major}.{v.minor}.{v.micro}"


def _check_config() -> str:
    from config import get_env_path
    env_path = Path(get_env_path())
    if env_path.exists():
        return f".env 配置文件存在: {env_path}"
    raise FileNotFoundError(f".env 文件不存在: {env_path}")


def _check_api(config: dict) -> str:
    api_key = config.get("OPENAI_API_KEY", "") or ""
    if not api_key:
        raise ValueError("未配置 API Key")
    api_base = config.get("OPENAI_BASE_URL", "") or "https://api.openai.com/v1"
    return f"API: {api_base[:40]}..."


def _check_model(config: dict) -> str:
    model = config.get("model_name", "") or "未配置"
    return f"模型: {model}"


def _check_git() -> str:
    git = shutil.which("git")
    if not git:
        raise FileNotFoundError("git 未安装")
    result = subprocess.run(
        ["git", "--version"], capture_output=True, text=True, timeout=5
    )
    return result.stdout.strip()


def _check_gh() -> str:
    gh = shutil.which("gh")
    if not gh:
        raise FileNotFoundError("gh CLI 未安装(PR 管理功能不可用)")
    result = subprocess.run(
        ["gh", "--version"], capture_output=True, text=True, timeout=5
    )
    return result.stdout.strip().split("\n")[0]


def _check_docker() -> str:
    docker = shutil.which("docker")
    if not docker:
        raise FileNotFoundError("Docker 未安装(沙箱功能不可用)")
    result = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, timeout=5
    )
    if result.returncode != 0:
        raise RuntimeError("Docker 未运行(沙箱功能不可用)")
    return "Docker 运行中"


def _check_ripgrep() -> str:
    rg = shutil.which("rg")
    if not rg:
        raise FileNotFoundError("ripgrep 未安装(Grep 将使用 Python 降级方案)")
    result = subprocess.run(
        ["rg", "--version"], capture_output=True, text=True, timeout=5
    )
    return result.stdout.strip().split("\n")[0]


def _check_workspace() -> str:
    cwd = Path.cwd()
    if not cwd.exists():
        raise FileNotFoundError(f"工作目录不存在: {cwd}")
    if not os.access(cwd, os.W_OK):
        raise PermissionError(f"工作目录不可写: {cwd}")
    return f"工作目录: {cwd}"


def _check_app_dir() -> str:
    from context import get_app_dir
    app_dir = get_app_dir("project")
    if app_dir.exists():
        return f"项目目录: {app_dir}"
    return f"项目目录不存在(首次使用时自动创建): {app_dir}"


def _check_skills() -> str:
    from tools.skill.loader import load_skills, get_builtin_skills
    all_skills = load_skills()
    builtin = get_builtin_skills()
    user = [s for s in all_skills if s.source == "user"]
    project = [s for s in all_skills if s.source == "project"]
    return f"技能: {len(builtin)} 内置, {len(user)} 用户, {len(project)} 项目"


def _check_mcp() -> str:
    try:
        from tools.mcp import MCPManager
        mgr = MCPManager.get_instance()
        servers = mgr.get_servers() if hasattr(mgr, "get_servers") else []
        if not servers:
            return "MCP: 无已配置的服务器"
        online = sum(1 for s in servers if getattr(s, "status", None) == "connected")
        return f"MCP: {online}/{len(servers)} 在线"
    except Exception:
        return "MCP: 无法检测"


def cmd_doctor(_args: str, task: AgentTask, config: dict) -> bool:
    """环境诊断

    检查 UniClaw 运行环境的各项依赖和配置状态。
    """
    checks = [
        ("Python", _check_python),
        ("配置文件", _check_config),
        ("API 配置", lambda: _check_api(config)),
        ("当前模型", lambda: _check_model(config)),
        ("Git", _check_git),
        ("GitHub CLI", _check_gh),
        ("Docker", _check_docker),
        ("ripgrep", _check_ripgrep),
        ("工作目录", _check_workspace),
        ("项目目录", _check_app_dir),
        ("技能系统", _check_skills),
        ("MCP 服务", _check_mcp),
    ]

    info(f"\n🔍 {APP_NAME} 环境诊断报告\n")
    info("─" * 50)

    pass_count = 0
    warn_count = 0
    fail_count = 0

    for name, fn in checks:
        try:
            result = fn()
            ok(f"  ✅ {result}")
            pass_count += 1
        except FileNotFoundError as e:
            warn(f"  ⚠️  {e}")
            warn_count += 1
        except Exception as e:
            err(f"  ❌ {e}")
            fail_count += 1

    info("─" * 50)
    total = pass_count + warn_count + fail_count
    info(f"\n  总计: {pass_count} 通过, {warn_count} 警告, {fail_count} 失败 / {total} 项\n")

    return True
