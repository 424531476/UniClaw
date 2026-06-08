"""配置管理模块 — 从 settings.json 加载持久化配置。

配置文件查找顺序:
1. 项目级:./.UniClaw/settings.json
2. 用户级:~/.UniClaw/settings.json
优先使用项目级配置。
"""

import json
import os
from enum import StrEnum
from pathlib import Path


class Permissions(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    ACCEPT_ALL = "accept-all"
    PLAN = "plan"


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
    """判断是否首次启动(配置文件不存在)。"""
    return not get_config_path().exists()


def run_setup_wizard() -> dict:
    """首次启动引导程序,提示用户填写必要配置并验证连通性。"""
    from uniclaw.commands.model import fetch_models

    print("\n=== UniClaw 首次启动配置 ===\n")

    data = {}
    url_map = {
        "1": "https://api.openai.com/v1",
        "2": "https://openrouter.ai/api/v1",
        "3": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "4": "https://api.xiaomimimo.com/v1",
        "5": "https://token-plan-cn.xiaomimimo.com/v1",
    }

    while True:
        print("常见 API Base URL:")
        print("  1. https://api.openai.com/v1                          (OpenAI)")
        print("  2. https://openrouter.ai/api/v1                       (OpenRouter)")
        print("  3. https://generativelanguage.googleapis.com/v1beta/openai/ (Google)")
        print("  4. https://api.xiaomimimo.com/v1                      (小米 MiMo)")
        print("  5. https://token-plan-cn.xiaomimimo.com/v1            (小米 MiMo 国内)")

        url_choice = input("选择 (1-5 或直接输入 URL, 默认 1): ").strip()
        base_url = url_map.get(url_choice, url_choice) or "https://api.openai.com/v1"

        api_key = input("API Key: ").strip()
        if not api_key:
            print("API Key 不能为空,请重新输入。\n")
            continue

        data["OPENAI_BASE_URL"] = base_url
        data["OPENAI_API_KEY"] = api_key

        print("正在验证 API 连通性...")
        try:
            models = fetch_models(base_url, api_key)
            print(f"验证成功,可用模型: {len(models)} 个")
            break
        except Exception as e:
            print(f"验证失败: {e}")
            print("请检查 Base URL 和 API Key 后重试。\n")
            data.clear()

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
    save_config(data)
    print(f"\n配置已保存到: {get_config_path()}\n")

    return data


def load_config() -> dict:
    """从 settings.json 加载配置,返回字典。
    项目级优先,不存在则读用户级。
    环境变量作为兜底。
    """
    data = {}
    path = get_config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # 环境变量兜底
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
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


def save_config(data: dict) -> None:
    """保存配置到当前生效的 settings.json。
    合并默认值,过滤掉下划线开头的内部键和运行时字段。
    """
    # 合并默认值(用户未设置的项也写入,方便查看和修改)
    defaults = {
        "OPENAI_API_KEY": "",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
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
    merged = {**defaults, **data}

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    runtime_keys = {"verbose", "permission_mode", "depth", "writable_dirs"}
    cleaned = {
        k: v for k, v in merged.items()
        if not k.startswith("_") and k not in runtime_keys
    }
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
