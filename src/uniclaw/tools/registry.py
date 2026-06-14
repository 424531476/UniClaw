"""工具注册表 — 管理核心工具和扩展工具的发现与加载。

对齐 Anthropic 的 defer_loading 模式:
- 核心工具(defer_loading: false):始终加载完整 schema
- 扩展工具(defer_loading: true):初始不加载,通过 search_tools 按需发现
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from rank_bm25 import BM25Okapi
from uniclaw.utils.tokenize import tokenize as _tokenize

from .base import Tool, tool


# ── 工具分类定义 ──────────────────────────────────────────────


def _build_core_tool_names() -> set[str]:
    """从核心工具对象动态构建核心工具名集合(避免硬编码字符串)。"""
    from .fs import Read, Write, Edit, Glob
    from .shell import Bash, Grep
    from .web import webFetch, webSearch
    from .memory.tools import memory_save, memory_delete, memory_list, memory_search
    from .plan import enter_plan_mode, exit_plan_mode
    from .skill.tools import skill_suggest, skill_read, skill_run_command

    core_tools = [
        Read, Write, Edit, Glob,
        Bash, Grep,
        webFetch, webSearch,
        memory_save, memory_delete, memory_list, memory_search,
        enter_plan_mode, exit_plan_mode,
        skill_suggest, skill_read, skill_run_command,
    ]
    return {t.name for t in core_tools}


CORE_TOOL_NAMES = _build_core_tool_names()


def _build_extended_keywords() -> dict[str, list[str]]:
    """从扩展工具对象动态构建关键词映射(避免硬编码字符串)。"""
    from .fs import ReadPDF
    from .shell import search_files_with_everything
    from .computer_use import (
        screenshot, mouse_move, mouse_click, mouse_double_click,
        mouse_drag, mouse_scroll, keyboard_type, keyboard_type_unicode,
        keyboard_press, keyboard_key_down, keyboard_key_up, locate_on_screen,
    )
    from .multi_agent.tools import (
        agent_create, send_message, agent_close, check_agent_result,
        list_agent_tasks, agent_discuss, list_agent_definitions,
    )
    from .todolist.tools import (
        todolist_create, todolist_update, todolist_clear,
        todolist_cancel, todolist_list, _overseer_create, _overseer_update,
    )
    from .monitor.tools import (
        monitor_start, monitor_stop, monitor_list,
        monitor_output, monitor_input, monitor_get_matched,
    )
    from .session.tools import (
        session_list, session_detail, session_delete, session_update_title,
    )
    from .scheduler.tools import (
        schedule_create, schedule_list, schedule_remove, schedule_toggle,
    )
    from .mcp.tools import (
        mcp_add_server, mcp_remove_server, mcp_toggle_server, mcp_list_servers,
    )
    from .security.tools import (
        read_llm_safe_prompt, write_llm_safe_prompt,
        edit_llm_safe_prompt, clear_llm_safe_prompt,
    )
    from .hooks.tools import hook_read, hook_add, hook_remove
    from .sandbox import RunCode
    from .sleep import sleep_timer, wait
    from .media import ReadMedia
    from .ask import AskUserQuestion
    from .notify import push_notification

    # tool.name → 关键词列表(中英文+语义同义词)
    return {
        ReadPDF.name: ["pdf", "PDF", "文档", "阅读PDF", "read pdf", "parse pdf"],
        search_files_with_everything.name: ["everything", "文件搜索", "快速搜索", "es", "file search"],
        screenshot.name: ["截图", "屏幕", "screenshot", "截屏", "屏幕截图", "capture screen"],
        mouse_move.name: ["鼠标移动", "mouse", "移动鼠标", "move mouse", "cursor"],
        mouse_click.name: ["点击", "click", "鼠标点击", "单击", "tap"],
        mouse_double_click.name: ["双击", "double click", "鼠标双击"],
        mouse_drag.name: ["拖拽", "drag", "拖动", "鼠标拖拽", "drag and drop"],
        mouse_scroll.name: ["滚动", "scroll", "滚轮", "鼠标滚动", "wheel"],
        keyboard_type.name: ["输入", "type", "键盘输入", "打字", "input text", "typing"],
        keyboard_type_unicode.name: ["unicode输入", "中文输入", "unicode type"],
        keyboard_press.name: ["按键", "press", "键盘按键", "快捷键", "hotkey", "key press"],
        keyboard_key_down.name: ["按下", "key down", "键盘按下"],
        keyboard_key_up.name: ["松开", "key up", "键盘松开"],
        locate_on_screen.name: ["定位", "locate", "屏幕定位", "查找图片", "find on screen", "template match"],
        agent_create.name: ["创建代理", "子代理", "sub agent", "create agent", "多智能体", "spawn agent"],
        send_message.name: ["发送消息", "send message", "代理消息", "message agent"],
        agent_close.name: ["关闭代理", "close agent", "停止代理", "kill agent"],
        check_agent_result.name: ["检查结果", "agent result", "代理结果", "check result"],
        list_agent_tasks.name: ["列出代理", "list agents", "代理列表", "代理任务"],
        agent_discuss.name: ["讨论", "discuss", "代理讨论", "多代理讨论", "multi agent discuss"],
        list_agent_definitions.name: ["代理定义", "agent definitions", "可用代理", "available agents"],
        todolist_create.name: ["创建任务", "待办", "todolist", "任务清单", "创建待办", "create task", "todo"],
        todolist_update.name: ["更新任务", "更新待办", "完成任务", "update task", "complete task"],
        todolist_clear.name: ["清除任务", "清空待办", "clear todolist", "clear tasks"],
        todolist_cancel.name: ["取消任务", "cancel todolist", "cancel task"],
        todolist_list.name: ["列出任务", "查看待办", "list todolist", "任务列表", "list tasks"],
        _overseer_create.name: ["监工", "overseer", "创建监工", "create overseer"],
        _overseer_update.name: ["更新监工", "更新监工任务", "update overseer"],
        monitor_start.name: ["启动监控", "monitor", "后台监控", "日志监控", "start monitor", "log monitor"],
        monitor_stop.name: ["停止监控", "stop monitor"],
        monitor_list.name: ["列出监控", "monitor list", "监控列表"],
        monitor_output.name: ["监控输出", "monitor output", "查看日志", "view log"],
        monitor_input.name: ["监控输入", "monitor input"],
        monitor_get_matched.name: ["匹配结果", "matched", "监控匹配", "grep monitor"],
        session_list.name: ["会话列表", "session list", "列出会话", "历史会话", "history"],
        session_detail.name: ["会话详情", "session detail", "查看会话"],
        session_delete.name: ["删除会话", "delete session", "清除会话"],
        session_update_title.name: ["更新标题", "session title", "会话标题"],
        schedule_create.name: ["创建定时", "cron", "定时任务", "schedule", "计划任务", "timer", "periodic"],
        schedule_list.name: ["定时列表", "list schedule", "定时任务列表"],
        schedule_remove.name: ["删除定时", "remove schedule", "取消定时", "cancel schedule"],
        schedule_toggle.name: ["切换定时", "toggle schedule", "启用定时", "禁用定时"],
        mcp_add_server.name: ["添加MCP", "MCP服务器", "add MCP", "添加工具服务", "tool server"],
        mcp_remove_server.name: ["删除MCP", "remove MCP", "移除MCP"],
        mcp_toggle_server.name: ["切换MCP", "toggle MCP", "启用MCP", "禁用MCP"],
        mcp_list_servers.name: ["MCP列表", "list MCP", "MCP服务器列表"],
        read_llm_safe_prompt.name: ["安全提示", "safe prompt", "读取安全规则", "security rules"],
        write_llm_safe_prompt.name: ["写入安全", "write safe prompt"],
        edit_llm_safe_prompt.name: ["编辑安全", "edit safe prompt"],
        clear_llm_safe_prompt.name: ["清除安全", "clear safe prompt"],
        hook_read.name: ["读取钩子", "hook", "查看钩子", "读取hook", "read hook"],
        hook_add.name: ["添加钩子", "add hook", "创建钩子", "create hook"],
        hook_remove.name: ["删除钩子", "remove hook", "移除钩子"],
        RunCode.name: ["沙箱", "sandbox", "Docker", "代码执行", "运行代码", "run code", "execute code"],
        sleep_timer.name: ["睡眠", "sleep", "等待", "定时器", "wait", "delay", "timer"],
        wait.name: ["等待", "wait", "延迟", "delay"],
        ReadMedia.name: [
            "图片", "media", "多媒体", "媒体", "读取图片", "视频", "音频",
            "image", "photo", "picture", "video", "audio", "read image",
            "OCR", "识别图片", "图片识别", "看图", "读图", "analyze image",
            "image recognition", "text recognition", "extract text",
        ],
        AskUserQuestion.name: ["询问用户", "ask user", "用户问题", "确认", "confirm", "question"],
        push_notification.name: ["通知", "notification", "推送通知", "桌面通知", "push notify"],
    }


def _build_tool_categories() -> dict[str, str]:
    """从扩展工具对象动态构建类别映射(避免硬编码字符串)。"""
    from .fs import ReadPDF
    from .shell import search_files_with_everything
    from .computer_use import (
        screenshot, mouse_move, mouse_click, mouse_double_click,
        mouse_drag, mouse_scroll, keyboard_type, keyboard_type_unicode,
        keyboard_press, keyboard_key_down, keyboard_key_up, locate_on_screen,
    )
    from .multi_agent.tools import (
        agent_create, send_message, agent_close, check_agent_result,
        list_agent_tasks, agent_discuss, list_agent_definitions,
    )
    from .todolist.tools import (
        todolist_create, todolist_update, todolist_clear,
        todolist_cancel, todolist_list, _overseer_create, _overseer_update,
    )
    from .monitor.tools import (
        monitor_start, monitor_stop, monitor_list,
        monitor_output, monitor_input, monitor_get_matched,
    )
    from .session.tools import (
        session_list, session_detail, session_delete, session_update_title,
    )
    from .scheduler.tools import (
        schedule_create, schedule_list, schedule_remove, schedule_toggle,
    )
    from .mcp.tools import (
        mcp_add_server, mcp_remove_server, mcp_toggle_server, mcp_list_servers,
    )
    from .security.tools import (
        read_llm_safe_prompt, write_llm_safe_prompt,
        edit_llm_safe_prompt, clear_llm_safe_prompt,
    )
    from .hooks.tools import hook_read, hook_add, hook_remove
    from .sandbox import RunCode
    from .sleep import sleep_timer, wait
    from .media import ReadMedia
    from .ask import AskUserQuestion
    from .notify import push_notification

    # tool.name → 类别
    return {
        ReadPDF.name: "文件系统",
        search_files_with_everything.name: "Shell",
        screenshot.name: "计算机操作", mouse_move.name: "计算机操作", mouse_click.name: "计算机操作",
        mouse_double_click.name: "计算机操作", mouse_drag.name: "计算机操作", mouse_scroll.name: "计算机操作",
        keyboard_type.name: "计算机操作", keyboard_type_unicode.name: "计算机操作",
        keyboard_press.name: "计算机操作", keyboard_key_down.name: "计算机操作",
        keyboard_key_up.name: "计算机操作", locate_on_screen.name: "计算机操作",
        agent_create.name: "多智能体", send_message.name: "多智能体", agent_close.name: "多智能体",
        check_agent_result.name: "多智能体", list_agent_tasks.name: "多智能体",
        agent_discuss.name: "多智能体", list_agent_definitions.name: "多智能体",
        todolist_create.name: "任务清单", todolist_update.name: "任务清单", todolist_clear.name: "任务清单",
        todolist_cancel.name: "任务清单", todolist_list.name: "任务清单",
        _overseer_create.name: "任务清单", _overseer_update.name: "任务清单",
        monitor_start.name: "进程监控", monitor_stop.name: "进程监控", monitor_list.name: "进程监控",
        monitor_output.name: "进程监控", monitor_input.name: "进程监控", monitor_get_matched.name: "进程监控",
        session_list.name: "会话管理", session_detail.name: "会话管理", session_delete.name: "会话管理",
        session_update_title.name: "会话管理",
        schedule_create.name: "定时任务", schedule_list.name: "定时任务", schedule_remove.name: "定时任务",
        schedule_toggle.name: "定时任务",
        mcp_add_server.name: "MCP管理", mcp_remove_server.name: "MCP管理", mcp_toggle_server.name: "MCP管理",
        mcp_list_servers.name: "MCP管理",
        read_llm_safe_prompt.name: "安全管理", write_llm_safe_prompt.name: "安全管理",
        edit_llm_safe_prompt.name: "安全管理", clear_llm_safe_prompt.name: "安全管理",
        hook_read.name: "Hook管理", hook_add.name: "Hook管理", hook_remove.name: "Hook管理",
        RunCode.name: "沙箱",
        sleep_timer.name: "睡眠/等待", wait.name: "睡眠/等待",
        ReadMedia.name: "媒体",
        AskUserQuestion.name: "用户交互",
        push_notification.name: "通知",
    }


# ── 注册表 ──────────────────────────────────────────────────


@dataclass
class ToolEntry:
    tool: Tool
    keywords: list[str]
    category: str


class ToolRegistry:
    """工具注册表 — 管理核心工具和扩展工具的发现与加载。"""

    _instance: Optional["ToolRegistry"] = None

    def __init__(self):
        self._entries: dict[str, ToolEntry] = {}
        self._core_names: set[str] = set()
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_keys: list[str] = []  # 与 BM25 矩阵对齐的工具名列表
        self._bm25_corpus: list[list[str]] = []

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(
        self,
        tool: Tool,
        keywords: list[str],
        category: str,
        is_core: bool = False,
    ):
        """注册工具到注册表。"""
        self._entries[tool.name] = ToolEntry(
            tool=tool, keywords=keywords, category=category
        )
        if is_core:
            self._core_names.add(tool.name)
        # 标记需要重建 BM25 索引
        self._bm25 = None

    def _build_bm25(self):
        """构建 BM25 索引。"""
        self._bm25_keys = []
        self._bm25_corpus = []
        for name, entry in self._entries.items():
            if name in self._core_names:
                continue  # 核心工具不需要搜索
            # 构建文档:工具名 + 描述 + 关键词
            doc = f"{name} {entry.tool.description} {' '.join(entry.keywords)}"
            tokens = _tokenize(doc)
            self._bm25_keys.append(name)
            self._bm25_corpus.append(tokens)
        if self._bm25_corpus:
            self._bm25 = BM25Okapi(self._bm25_corpus)
        else:
            self._bm25 = None

    def search(self, query: str, top_k: int = 10) -> list[ToolEntry]:
        """BM25 搜索工具。"""
        if not self._entries:
            return []
        if self._bm25 is None:
            self._build_bm25()
        if self._bm25 is None:
            return []

        query_tokens = _tokenize(query)
        scores = self._bm25.get_scores(query_tokens)

        # 按分数排序,取 top_k
        scored = sorted(
            zip(self._bm25_keys, scores), key=lambda x: x[1], reverse=True
        )
        results = []
        for name, score in scored[:top_k]:
            if score > 0:
                results.append(self._entries[name])
        return results

    def get_all_entries(self) -> dict[str, ToolEntry]:
        """获取所有注册的工具条目。"""
        return dict(self._entries)

    def get_core_names(self) -> set[str]:
        """获取核心工具名集合。"""
        return set(self._core_names)


# ── search_tools 元工具 ──────────────────────────────────────


@tool
def search_tools(query: str, config=None) -> str:
    """搜索可用的扩展工具。当你需要使用非常用工具时,先搜索再使用。
    搜索结果会自动加载到可用工具集中,下一轮即可调用。支持中英文关键词。

    Args:
        query: 搜索关键词,描述你需要的工具功能(如 "截图"、"screenshot"、"定时任务"、"OCR")
    """
    registry = ToolRegistry.get_instance()
    results = registry.search(query)
    if not results:
        return f"未找到匹配 '{query}' 的工具。尝试其他关键词。"
    # 只保留当前允许的工具(由 run() 在启动时计算,包含模块启用状态和子代理白名单)
    task = config.current_agent
    results = [e for e in results if e.tool.name in task.allowed_tools_set]
    if not results:
        return f"未找到匹配 '{query}' 的工具。尝试其他关键词。"
    # 将发现的工具加入 task 的待加载列表
    for entry in results:
        task.pending_tools.append(entry.tool)
    lines = [f"找到 {len(results)} 个匹配工具(已自动加载到可用工具集):"]
    for entry in results:
        lines.append(f"- {entry.tool.name}: {entry.tool.description}")
    return "\n".join(lines)


def get_tools() -> list:
    """获取 search_tools 元工具。"""
    return [search_tools]


def get_registry_system_prompt(config=None) -> str:
    """生成扩展工具的系统提示词。"""
    from . import _ensure_registry

    _ensure_registry()
    registry = ToolRegistry.get_instance()
    # 子代理只展示可用的扩展工具
    allowed = None
    if config and config.is_sub:
        allowed = config.current_agent.allowed_tools_set
    categories: dict[str, list[str]] = {}
    for name, entry in registry.get_all_entries().items():
        if name not in registry.get_core_names():
            if allowed is not None and name not in allowed:
                continue
            # 格式: 工具名(简短描述)
            short_desc = entry.tool.description.split("。")[0].split(".")[0]
            categories.setdefault(entry.category, []).append(f"{name}({short_desc})")
    if not categories:
        return ""
    cat_lines = []
    for cat, tools in categories.items():
        cat_lines.append(f"  - {cat}: {', '.join(tools[:5])}")
    return (
        "# 扩展工具\n"
        f"你有 {search_tools.name} 工具可用于发现以下扩展工具(按需搜索加载):\n"
        + "\n".join(cat_lines)
        + f"\n⚠️ 重要规则:当需要使用上面列出的工具时,必须先调用 {search_tools.name} 搜索加载。"
        + "在搜索之前禁止说'我无法做到'、'我没有这个能力'、'我是文本AI'等拒绝性话语。"
    )


# ── 注册表初始化 ──────────────────────────────────────────────


def init_registry(all_tools: list[Tool]):
    """从全量工具列表初始化注册表。

    Args:
        all_tools: 所有工具的 Tool 对象列表
    """
    registry = ToolRegistry.get_instance()
    keywords_map = _build_extended_keywords()
    categories_map = _build_tool_categories()
    for t in all_tools:
        is_core = t.name in CORE_TOOL_NAMES
        keywords = keywords_map.get(t.name, [])
        category = categories_map.get(t.name, "其他")
        registry.register(t, keywords, category, is_core=is_core)
