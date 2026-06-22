"""REST API 路由。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from uniclaw.webui.models import (
    CheckpointCreate,
    CheckpointRestore,
    ConfigUpdate,
    GitCommit,
    GitStage,
    HookUpdate,
    PermissionRuleDelete,
    SessionMove,
    SessionRename,
)
from uniclaw.webui.ws import get_or_load_session, session_cache
from uniclaw.tools.session.session_manager import SessionManager
from uniclaw.utils.logger import get_logger

router = APIRouter(prefix="/api")


def _validate_path(base_dir: str, relative_path: str) -> Path:
    """验证并规范化路径,防止路径遍历攻击。

    Args:
        base_dir: 基础目录(项目根目录)
        relative_path: 相对路径

    Returns:
        规范化后的绝对路径

    Raises:
        HTTPException: 路径越界时抛出 403 错误
    """
    base = Path(base_dir).resolve()
    target = (base / relative_path).resolve()

    # 检查目标路径是否在基础目录内
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=403, detail=f"路径越界: {relative_path}")

    return target


# === 项目管理 ===

@router.get("/projects")
async def list_projects():
    """列出已有项目(从 session metadata 提取去重的 root_dir)。"""
    sessions = SessionManager.list_sessions(limit=10000)
    projects = {}
    for s in sessions:
        root_dir = s.get("root_dir", "")
        if not root_dir:
            continue
        if root_dir not in projects:
            projects[root_dir] = {
                "root_dir": root_dir,
                "session_count": 0,
                "last_active": s.get("end_time") or s.get("start_time", ""),
            }
        projects[root_dir]["session_count"] += 1
        end_time = s.get("end_time") or s.get("start_time", "")
        if end_time > projects[root_dir]["last_active"]:
            projects[root_dir]["last_active"] = end_time
    # 按最后活跃时间排序
    result = sorted(projects.values(), key=lambda x: x["last_active"], reverse=True)
    return result


@router.get("/dirs")
async def list_dirs(path: str = ""):
    """浏览服务端目录。"""
    if not path:
        # 返回根目录列表
        if os.name == "nt":
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            return [{"name": d, "path": d, "is_dir": True} for d in drives]
        else:
            return [{"name": "/", "path": "/", "is_dir": True}]

    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"不是目录: {path}")

    entries = []
    try:
        for item in sorted(p.iterdir()):
            entries.append({
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir(),
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"无权限访问: {path}")
    return entries


# === 会话管理 ===

@router.get("/sessions")
async def list_sessions(root_dir: str = ""):
    """列出会话(文件 + 内存缓存中的活跃会话)。"""
    limit = 10000
    if root_dir:
        sessions = SessionManager.list_sessions(limit=limit, root_dir=root_dir)
    else:
        sessions = SessionManager.list_sessions(limit=limit)

    # 合并内存缓存中的活跃会话(缓存版本优先,因为可能有未保存的新消息)
    saved_map = {s["session_id"]: s for s in sessions}
    for sid, config in session_cache.items():
        session = config.current_agent.session
        item_root_dir = str(session.root_dir) if session.root_dir else ""
        if root_dir and item_root_dir != root_dir:
            continue
        cache_item = {
            "session_id": session.id,
            "title": session.title or session.id,
            "start_time": session.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": "",
            "message_count": len(session._messages),
            "root_dir": item_root_dir,
            "file_path": "",
        }
        existing = saved_map.get(sid)
        if existing:
            # 缓存中的消息数更多 → 用缓存版本替换
            if cache_item["message_count"] > existing.get("message_count", 0):
                saved_map[sid] = cache_item
            # 更新 title(缓存中的 title 可能更准确)
            if session.title:
                saved_map[sid]["title"] = session.title
        else:
            saved_map[sid] = cache_item
    sessions = list(saved_map.values())

    # 按时间排序
    sessions.sort(
        key=lambda x: x.get("end_time") or x.get("start_time") or "",
        reverse=True,
    )
    return sessions[:limit]


@router.get("/sessions/search")
async def search_sessions(keyword: str):
    """搜索会话。"""
    return SessionManager.search_sessions(keyword)



@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情(优先从缓存读取,缓存中可能有未保存的新消息)。"""
    session = None
    # 优先从缓存获取(可能有未保存的新消息)
    if session_id in session_cache:
        config = session_cache[session_id]
        session = config.current_agent.session
    # 缓存未命中或缓存中没有消息,从文件加载
    if session is None or not session._messages:
        file_session = SessionManager.load_session(session_id)
        if file_session and (session is None or len(file_session._messages) > len(session._messages)):
            session = file_session
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    # 手动构建响应(避免 to_dict 的 async/config 依赖)
    from datetime import datetime
    from uniclaw.tools.session.session import AIMessage, ToolCallMessage
    now = datetime.now()
    duration = max(0, int((now - session.start_time).total_seconds()))
    messages_data = []
    for msg in session._messages:
        try:
            d = msg.to_dict()
            # AIMessage 的 usage 可能为 None,补充默认值
            if isinstance(msg, AIMessage) and d.get("usage") is None:
                d["usage"] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            messages_data.append(d)
        except Exception as e:
            # 降级：手动构建基本结构
            role = getattr(msg, 'role', 'unknown')
            content = getattr(msg, 'content', '')
            if isinstance(content, list):
                content = str(content)
            messages_data.append({"role": str(role), "content": str(content)})
    return {
        "session_id": session.id,
        "title": session.title or session.id,
        "root_dir": str(session.root_dir),
        "start_time": session.start_time.isoformat(),
        "end_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": duration,
        "message_count": len(session._messages),
        "messages": messages_data,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话。"""
    SessionManager.delete_session(session_id)
    session_cache.pop(session_id, None)
    return {"ok": True}


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, body: SessionRename):
    """重命名会话。"""
    SessionManager.update_title(session_id, body.title)
    return {"ok": True}


@router.post("/sessions/{session_id}/move")
async def move_session(session_id: str, body: SessionMove):
    """移动会话到其他项目。"""
    ok = SessionManager.update_root_dir(session_id, body.root_dir)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 更新缓存中的 root_dir
    if session_id in session_cache:
        session_cache[session_id].current_agent.session.root_dir = Path(body.root_dir)
    return {"ok": True}


@router.post("/sessions/{session_id}/title/generate")
async def generate_title(session_id: str):
    """AI 生成标题。"""
    try:
        config = await get_or_load_session(session_id)
        session = config.current_agent.session
        title = await session.generate_title(config)
        SessionManager.update_title(session_id, title)
        return {"title": title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === 配置 ===

@router.get("/config")
async def get_config(session_id: str):
    """获取会话配置。"""
    try:
        config = await get_or_load_session(session_id)
        return {
            "model_name": config.model_name,
            "mini_model_name": config.mini_model_name,
            "permission_mode": config.permission_mode.value if hasattr(config.permission_mode, 'value') else str(config.permission_mode),
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "root_dir": config.root_dir,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/config")
async def update_config(body: ConfigUpdate):
    """更新配置。"""
    try:
        config = await get_or_load_session(body.session_id)
        if body.model_name is not None:
            config.model_name = body.model_name
        if body.permission_mode is not None:
            from uniclaw.config import Permissions
            config.permission_mode = Permissions(body.permission_mode)
        if body.temperature is not None:
            config.temperature = body.temperature
        if body.max_tokens is not None:
            config.max_tokens = body.max_tokens
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/context")
async def get_context_usage(session_id: str):
    """获取上下文使用情况。"""
    try:
        config = await get_or_load_session(session_id)
        from uniclaw.commands.context_usage import analyze_context, _pct
        report = await analyze_context(config)
        return {
            "model": report.model,
            "limit": report.limit,
            "used_tokens": report.used_tokens,
            "system_prompt_tokens": report.system_prompt_tokens,
            "tool_tokens": report.tool_tokens,
            "message_tokens": report.message_tokens,
            "autocompact_tokens": report.autocompact_tokens,
            "free_tokens": report.free_tokens,
            "percentage": round(_pct(report.used_tokens, report.limit), 1),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        get_logger("webui", Path.cwd()).error(f"获取上下文使用情况失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === 文件浏览 ===

@router.get("/files")
async def list_files(root_dir: str, path: str = "", recursive: bool = False):
    """列出项目文件。"""
    target = _validate_path(root_dir, path) if path else Path(root_dir).resolve()

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {target}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"不是目录: {target}")

    base = Path(root_dir).resolve()
    entries = []
    try:
        if recursive:
            for item in sorted(target.rglob("*")):
                if item.name.startswith(".") or any(p.startswith(".") for p in item.relative_to(base).parts):
                    continue
                entries.append({
                    "name": item.name,
                    "path": str(item.relative_to(base)),
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0,
                })
                if len(entries) >= 200:  # 限制数量
                    break
        else:
            for item in sorted(target.iterdir()):
                if item.name.startswith("."):
                    continue
                entries.append({
                    "name": item.name,
                    "path": str(item.relative_to(base)),
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0,
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"无权限访问: {target}")
    return entries


@router.get("/files/content")
async def get_file_content(root_dir: str, path: str):
    """读取文件内容。"""
    file_path = _validate_path(root_dir, path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail=f"不是文件: {file_path}")
    # 限制文件大小 (100MB)
    if file_path.stat().st_size > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大(>100MB)")
    try:
        content = file_path.read_text(encoding="utf-8")
        return {"content": content, "path": path}
    except UnicodeDecodeError:
        return {"content": "[二进制文件]", "path": path}


# === Checkpoint ===

@router.get("/checkpoints")
async def list_checkpoints(root_dir: str):
    """列出 checkpoint。"""
    from uniclaw.utils.checkpoint import list_checkpoints as cp_list
    # 验证 root_dir 合法性
    _validate_path(root_dir, "")
    result = await cp_list(Path(root_dir))
    return {"output": result}


@router.post("/checkpoints")
async def create_checkpoint(body: CheckpointCreate):
    """创建 checkpoint。"""
    from uniclaw.utils.checkpoint import create_checkpoint
    # 验证 root_dir 合法性
    _validate_path(body.root_dir, "")
    result = await create_checkpoint(Path(body.root_dir), body.message)
    return {"result": result}


@router.post("/checkpoints/{idx}/restore")
async def restore_checkpoint(idx: int, body: CheckpointRestore):
    """恢复 checkpoint。"""
    from uniclaw.utils.checkpoint import apply_checkpoint
    # 验证 root_dir 合法性
    _validate_path(body.root_dir, "")
    result = await apply_checkpoint(Path(body.root_dir), idx)
    return {"result": result}


@router.get("/checkpoints/{idx}/diff")
async def diff_checkpoint(idx: int, root_dir: str):
    """查看 checkpoint diff。"""
    from uniclaw.utils.checkpoint import diff_checkpoint as cp_diff
    # 验证 root_dir 合法性
    _validate_path(root_dir, "")
    result = await cp_diff(Path(root_dir), idx)
    return {"output": result}


# === Git ===

@router.get("/git/status")
async def git_status(root_dir: str):
    """Git status。"""
    import subprocess
    # 验证 root_dir 合法性
    _validate_path(root_dir, "")
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {"output": result.stdout}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Git 命令执行超时")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Git 未安装或不在 PATH 中")
    except Exception as e:
        get_logger("webui", Path.cwd()).error(f"Git status 失败: {e}")
        raise HTTPException(status_code=500, detail="Git 命令执行失败")


@router.post("/git/commit")
async def git_commit(body: GitCommit):
    """Git commit。"""
    import subprocess
    # 验证 root_dir 合法性
    _validate_path(body.root_dir, "")
    try:
        # 暂存文件
        if body.files:
            subprocess.run(["git", "add"] + body.files, cwd=body.root_dir, check=True)
        # 提交
        result = subprocess.run(
            ["git", "commit", "-m", body.message],
            cwd=body.root_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {"output": result.stdout + result.stderr}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Git 命令执行超时")
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=f"Git 命令执行失败: {e.stderr}")
    except Exception as e:
        get_logger("webui", Path.cwd()).error(f"Git commit 失败: {e}")
        raise HTTPException(status_code=500, detail="Git 提交失败")


@router.post("/git/stage")
async def git_stage(body: GitStage):
    """Git add。"""
    import subprocess
    # 验证 root_dir 合法性
    _validate_path(body.root_dir, "")
    try:
        result = subprocess.run(
            ["git", "add"] + body.files,
            cwd=body.root_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {"output": result.stdout + result.stderr}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Git 命令执行超时")
    except Exception as e:
        get_logger("webui", Path.cwd()).error(f"Git stage 失败: {e}")
        raise HTTPException(status_code=500, detail="Git 暂存失败")


@router.post("/git/unstage")
async def git_unstage(body: GitStage):
    """Git reset。"""
    import subprocess
    # 验证 root_dir 合法性
    _validate_path(body.root_dir, "")
    try:
        result = subprocess.run(
            ["git", "reset"] + body.files,
            cwd=body.root_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {"output": result.stdout + result.stderr}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Git 命令执行超时")
    except Exception as e:
        get_logger("webui", Path.cwd()).error(f"Git unstage 失败: {e}")
        raise HTTPException(status_code=500, detail="Git 取消暂存失败")


# === 权限 ===

@router.get("/permissions/rules")
async def list_permission_rules(root_dir: str):
    """列出权限规则。"""
    from uniclaw.tools.security.security import list_permission_rules as list_rules
    # 验证 root_dir 合法性
    _validate_path(root_dir, "")
    return list_rules(Path(root_dir))


@router.delete("/permissions/rules")
async def delete_permission_rule(body: PermissionRuleDelete):
    """删除权限规则。"""
    from uniclaw.tools.security.security import remove_permission_rule
    # 验证 root_dir 合法性
    _validate_path(body.root_dir, "")
    remove_permission_rule(body.rule_type, body.pattern, body.root_dir)
    return {"ok": True}


# === Hooks ===

@router.get("/hooks")
async def list_hooks(root_dir: str):
    """列出 hooks 配置。"""
    from uniclaw.tools.hooks.hook_manager import load_hooks_config
    # 验证 root_dir 合法性
    _validate_path(root_dir, "")
    return load_hooks_config(Path(root_dir))


@router.put("/hooks")
async def update_hooks(body: HookUpdate):
    """更新 hooks 配置。"""
    from uniclaw.tools.hooks.hook_manager import get_hooks_path, load_all_hooks_configs
    # 验证 root_dir 合法性
    _validate_path(body.root_dir, "")
    try:
        path = get_hooks_path(Path(body.root_dir))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(body.hooks, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        load_all_hooks_configs.cache_clear()
        return {"ok": True}
    except Exception as e:
        get_logger("webui", Path.cwd()).error(f"更新 hooks 失败: {e}")
        raise HTTPException(status_code=500, detail="更新 hooks 配置失败")


@router.get("/hooks/events")
async def list_hook_events():
    """列出可用的 HookEvent 类型。"""
    from uniclaw.tools.hooks.hook_manager import HookEvent
    return [{"name": e.name, "value": e.value} for e in HookEvent]


# === 命令 ===

@router.get("/commands")
async def list_commands():
    """列出可用命令。"""
    from uniclaw.commands import COMMANDS, COMMAND_SUBCOMMANDS
    commands = []
    for name, handler in COMMANDS.items():
        commands.append({
            "name": name,
            "description": (handler.__doc__ or "").strip().split("\n")[0],
        })
    # 展开别名：/cp → /checkpoint 的子命令
    subcommands = dict(COMMAND_SUBCOMMANDS)
    for name, handler in COMMANDS.items():
        if name not in subcommands:
            for primary, primary_handler in COMMANDS.items():
                if primary in subcommands and primary_handler is handler:
                    subcommands[name] = subcommands[primary]
                    break
    return {"commands": commands, "subcommands": subcommands}


# === 技能 ===

@router.get("/skills")
async def list_skills(root_dir: str = ""):
    """列出可用技能。"""
    from uniclaw.tools.skill.loader import load_skills
    # 验证 root_dir 合法性(如果提供)
    if root_dir:
        _validate_path(root_dir, "")
    skills = load_skills(Path(root_dir) if root_dir else Path.cwd())
    return [{"name": s.name, "description": s.description, "triggers": s.triggers} for s in skills]


# === 后台进程管理 ===

@router.get("/monitors")
async def list_monitors():
    """列出后台进程。"""
    from uniclaw.tools.monitor.manager import MonitorManager
    manager = MonitorManager.get_instance()
    result = []
    for mid, mon in manager._monitors.items():
        result.append({
            "id": mid,
            "command": mon.command,
            "description": mon.description,
            "status": mon.status.value if hasattr(mon.status, 'value') else str(mon.status),
            "pid": mon.process.pid if mon.process else None,
        })
    return result


@router.post("/monitors/{monitor_id}/stop")
async def stop_monitor(monitor_id: str):
    """停止后台进程。"""
    from uniclaw.tools.monitor.manager import MonitorManager
    manager = MonitorManager.get_instance()
    try:
        result = await manager.stop_monitor(monitor_id)
        return {"output": result}
    except Exception as e:
        get_logger("webui", Path.cwd()).error(f"停止进程失败: {e}")
        raise HTTPException(status_code=500, detail="停止进程失败")
