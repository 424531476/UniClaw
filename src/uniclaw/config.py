"""配置管理模块 — 从 settings.json 加载持久化配置。

配置文件查找顺序:
1. 项目级:./.UniClaw/settings.json
2. 用户级:~/.UniClaw/settings.json
优先使用项目级配置。
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from uniclaw.provider.types import Provider
from uniclaw.spinner import BaseSpinner

if TYPE_CHECKING:
    from uniclaw.agent import AgentTask


class Permissions(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    ACCEPT_ALL = "accept-all"
    PLAN = "plan"


@dataclass
class AppConfig:
    """应用配置 dataclass,包含 LLM 配置、运行时状态和 Agent/Session 引用。"""

    # === LLM 配置 (从 settings.json 加载) ===
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    provider: str = ""  # Provider 枚举值,空字符串表示自动检测
    model_name: str = ""
    mini_model_name: str = ""
    multimodal_model_name: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float | None = None
    proxy_url: str = ""
    GITHUB_TOKEN: str = ""
    max_agent_depth: int = 3
    permission_timeout: int = 300

    # === 运行时状态 (不持久化) ===
    permission_mode: str = Permissions.AUTO
    verbose: bool = False
    depth: int = 0
    workspace: list[str] = field(default_factory=list)
    writable_dirs: list[str] = field(default_factory=list)
    tool_cancel_event: threading.Event = field(
        default_factory=threading.Event, repr=False
    )
    interactive: bool = True
    spinner: BaseSpinner = field(default=None, repr=False)  # type: ignore[assignment]

    @property
    def is_sub(self) -> bool:
        """是否为子代理(depth > 0)"""
        return self.depth > 0

    # === Agent 引用 (必填,session 通过 current_agent.session 访问) ===
    current_agent: "AgentTask" = field(default=None)  # type: ignore[assignment]
    parent_agent: "AgentTask | None" = field(default=None, repr=False)

    @property
    def root_dir(self) -> Path:
        """便捷属性,返回 current_agent.session.root_dir。"""
        return self.current_agent.session.root_dir

    def create_child_config(self, name: str, prompt: str) -> AppConfig:
        """创建子代理配置:新 session (同 root_dir),深度+1,复制其他字段。"""
        from uniclaw.tools.session.session import Session

        child_session = Session(root_dir=self.root_dir)
        from uniclaw.agent import AgentTask

        child_task = AgentTask(name=name, prompt=prompt, session=child_session)
        return AppConfig(
            current_agent=child_task,
            parent_agent=self.current_agent,
            depth=self.depth + 1,
            OPENAI_API_KEY=self.OPENAI_API_KEY,
            OPENAI_BASE_URL=self.OPENAI_BASE_URL,
            ANTHROPIC_API_KEY=self.ANTHROPIC_API_KEY,
            ANTHROPIC_BASE_URL=self.ANTHROPIC_BASE_URL,
            provider=self.provider,
            model_name=self.model_name,
            mini_model_name=self.mini_model_name,
            multimodal_model_name=self.multimodal_model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            proxy_url=self.proxy_url,
            max_agent_depth=self.max_agent_depth,
            permission_timeout=self.permission_timeout,
            permission_mode=self.permission_mode,
            verbose=self.verbose,
            interactive=self.interactive,
            spinner=self.spinner,
            workspace=list(self.workspace),
            writable_dirs=list(self.writable_dirs),
        )


def get_config_path() -> Path:
    """获取当前生效的配置文件路径(项目级优先)。
    项目级存在则返回项目级,否则返回用户级。
    """
    from uniclaw.context import get_app_dir, Scope

    project_path = get_app_dir(Path.cwd()) / "settings.json"
    if project_path.exists():
        return project_path
    return get_app_dir(Scope.USER) / "settings.json"


def is_first_launch() -> bool:
    """判断是否首次启动(配置文件不存在、读取失败或缺少 API Key)。"""
    path = get_config_path()
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    # 配置文件和环境变量都没有 API Key,视为严重问题
    import os
    has_openai = data.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    has_anthropic = data.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not has_openai and not has_anthropic:
        return True
    return False


async def run_setup_wizard() -> dict:
    """首次启动引导程序,提示用户填写必要配置并验证连通性。"""
    from uniclaw.commands.model import fetch_openai_models

    print("\n=== UniClaw 首次启动配置 ===\n")

    data: dict[str, Any] = {}

    # 预设 Base URL
    BASE_URL_MAP: dict[Provider, list[tuple[str, str]]] = {
        Provider.OPENAI: [
            ("https://api.openai.com/v1", "OpenAI"),
            ("https://openrouter.ai/api/v1", "OpenRouter"),
            ("https://generativelanguage.googleapis.com/v1beta/openai/", "Google"),
            ("https://api.xiaomimimo.com/v1", "小米 MiMo"),
            ("https://token-plan-cn.xiaomimimo.com/v1", "小米 MiMo 国内"),
        ],
        Provider.ANTHROPIC: [
            ("https://api.anthropic.com", "官方"),
        ],
    }

    # 第一步:选择 API 兼容协议
    protocols = list(BASE_URL_MAP.keys())
    while True:
        print("选择 API 兼容协议:")
        for i, p in enumerate(protocols, 1):
            print(f"  {i}. {p.upper()} 兼容")
        protocol_idx = input(f"选择 (1-{len(protocols)}, 默认 1): ").strip() or "1"
        if protocol_idx.isdigit() and 1 <= int(protocol_idx) <= len(protocols):
            protocol = protocols[int(protocol_idx) - 1]
            break
        print(f"无效选择,请输入 1-{len(protocols)}。\n")

    # 第二步:选择 Base URL
    urls = BASE_URL_MAP[protocol]
    while True:
        print(f"\n{protocol.upper()} 兼容 API Base URL:")
        for i, (url, name) in enumerate(urls, 1):
            print(f"  {i}. {url:<55} ({name})")
        url_choice = input(f"选择 (1-{len(urls)} 或直接输入 URL, 默认 1): ").strip() or "1"
        if url_choice.isdigit() and 1 <= int(url_choice) <= len(urls):
            base_url = urls[int(url_choice) - 1][0]
            break
        if url_choice.startswith("http"):
            base_url = url_choice
            break
        print("无效输入,请输入序号或完整 URL。\n")

    # 第三步:输入 API Key
    while True:
        api_key = input("API Key: ").strip()
        if api_key:
            break
        print("API Key 不能为空,请重新输入。\n")

    # 第四步:验证连通性并选择模型
    if protocol == Provider.ANTHROPIC:
        from uniclaw.commands.model import fetch_anthropic_models

        data["ANTHROPIC_API_KEY"] = api_key
        data["ANTHROPIC_BASE_URL"] = base_url
        data["provider"] = Provider.ANTHROPIC
        models = None
        try:
            models = await fetch_anthropic_models(base_url, api_key)
            print(f"可用模型: {len(models)} 个")
        except Exception:
            pass  # 部分兼容接口不支持 /v1/models,跳过

        if not models:
            print("该接口不支持自动获取模型列表,请手动输入模型名称。")
            model = input("模型名称: ").strip()
            if not model:
                print("模型名称不能为空,请重新配置。\n")
                return await run_setup_wizard()
            data["model_name"] = model
            data["mini_model_name"] = model
            print(f"已选择: {model}")
            _save_settings_json(data)
            print(f"\n配置已保存到: {get_config_path()}\n")
            return data
    else:
        data["OPENAI_BASE_URL"] = base_url
        data["OPENAI_API_KEY"] = api_key
        print("正在验证 API 连通性...")
        try:
            models = await fetch_openai_models(base_url, api_key)
            print(f"验证成功,可用模型: {len(models)} 个")
        except Exception as e:
            print(f"验证失败: {e}")
            print("请检查 Base URL 和 API Key 后重试。\n")
            return await run_setup_wizard()

    # 选择模型
    print(f"\n可用模型 ({len(models)} 个):")
    for i, m in enumerate(models, 1):
        print(f"  {i}. {m}")
    while True:
        choice = input(f"\n选择模型 (输入序号或名称, 默认 1): ").strip()
        if not choice:
            choice = "1"
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                model = models[idx]
                break
            print(f"序号无效,请输入 1-{len(models)}")
        elif choice in models:
            model = choice
            break
        else:
            print(f"未找到模型 '{choice}',请重新选择")
    data["model_name"] = model
    data["mini_model_name"] = model
    print(f"已选择: {model}")

    # 保存配置
    _save_settings_json(data)
    print(f"\n配置已保存到: {get_config_path()}\n")

    return data


def _load_settings_json() -> dict[str, Any]:
    """从 settings.json 读取原始数据,包含环境变量兜底和默认值。"""
    data: dict[str, Any] = {}
    path = get_config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # 环境变量兜底
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
        if not data.get(key):
            env_val = os.environ.get(key)
            if env_val:
                data[key] = env_val

    # 默认值
    defaults = {
        "temperature": 0.7,
        "max_tokens": None,
        "top_p": None,
        "multimodal_model_name": None,
        "max_agent_depth": 3,
        "permission_timeout": 300,
    }
    for k, v in defaults.items():
        if k not in data:
            data[k] = v

    # mini_model_name 默认等于 model_name
    if data.get("model_name") and not data.get("mini_model_name"):
        data["mini_model_name"] = data["model_name"]

    return data


def load_config(root_dir: Path, spinner: BaseSpinner) -> AppConfig:
    """从 settings.json 加载配置,内部创建 Session 和 AgentTask(name="root")。

    Args:
        root_dir: 工作目录
        spinner: 旋转器实例(子代理共享同一实例)
    """
    # 创建 Session 和 AgentTask
    from uniclaw.tools.session.session import Session

    session = Session(root_dir=root_dir)
    from uniclaw.agent import AgentTask

    task = AgentTask(name="root", prompt="", session=session)

    # root 任务拥有独立的 TodoList(内含 OverseerManager)
    from uniclaw.tools.todolist import TodoList

    task.todolist = TodoList()

    # 读取 settings.json
    data = _load_settings_json()

    return AppConfig(
        current_agent=task,
        spinner=spinner,
        OPENAI_API_KEY=data.get("OPENAI_API_KEY", ""),
        OPENAI_BASE_URL=data.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        ANTHROPIC_API_KEY=data.get("ANTHROPIC_API_KEY", ""),
        ANTHROPIC_BASE_URL=data.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        provider=data.get("provider", ""),
        model_name=data.get("model_name", ""),
        mini_model_name=data.get("mini_model_name", ""),
        multimodal_model_name=data.get("multimodal_model_name"),
        temperature=data.get("temperature", 0.7),
        max_tokens=data.get("max_tokens"),
        top_p=data.get("top_p"),
        proxy_url=data.get("proxy_url", ""),
        max_agent_depth=data.get("max_agent_depth", 3),
        permission_timeout=data.get("permission_timeout", 300),
    )


def create_sub_agent_config(
    root_dir: Path,
    name: str,
    prompt: str,
    model_name: str | None = None,
) -> AppConfig:
    """为无父代理的场景创建子代理配置 (scheduler 等)。深度默认为1。"""
    from uniclaw.spinner import NoopSpinner

    config = load_config(root_dir=root_dir, spinner=NoopSpinner())
    config.current_agent.name = name
    config.current_agent.prompt = prompt
    config.depth = 1
    if model_name:
        config.model_name = model_name
    return config


def _save_settings_json(data: dict[str, Any]) -> None:
    """保存原始数据到 settings.json。"""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_config(config: AppConfig) -> None:
    """保存配置到当前生效的 settings.json。
    只持久化 LLM 配置字段,过滤运行时状态。
    """
    defaults = {
        "OPENAI_API_KEY": "",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
        "provider": "",
        "model_name": "",
        "mini_model_name": "",
        "multimodal_model_name": "",
        "temperature": 0.7,
        "max_tokens": None,
        "top_p": None,
        "proxy_url": "",
        "max_agent_depth": 3,
        "permission_timeout": 300,
    }
    # 从 AppConfig 提取持久化字段
    cleaned = {}
    for key in defaults:
        cleaned[key] = getattr(config, key, defaults[key])

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
