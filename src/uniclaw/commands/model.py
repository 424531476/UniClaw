import httpx
from uniclaw.config import AppConfig, save_config
from uniclaw.console.ui import info, ok, warn, err
from uniclaw.provider.types import Provider


def fetch_openai_models_sync(base_url: str, api_key: str) -> list[str]:
    """同步版本: 通过 base_url 和 api_key 获取可用模型列表

    Args:
        base_url: API 基础 URL
        api_key: API 密钥

    Returns:
        list[str]: 模型 ID 列表
    """
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = httpx.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [m["id"] for m in data.get("data", [])]


async def fetch_openai_models(base_url: str, api_key: str) -> list[str]:
    """异步版本: 通过 base_url 和 api_key 获取可用模型列表

    Args:
        base_url: API 基础 URL
        api_key: API 密钥

    Returns:
        list[str]: 模型 ID 列表
    """
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [m["id"] for m in data.get("data", [])]


def fetch_anthropic_models_sync(base_url: str, api_key: str) -> list[str]:
    """同步版本: 获取 Anthropic 可用模型列表。"""
    url = f"{base_url.rstrip('/')}/v1/models"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    resp = httpx.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [m["id"] for m in data.get("data", [])]


async def fetch_anthropic_models(base_url: str, api_key: str) -> list[str]:
    """异步版本: 获取 Anthropic 可用模型列表。"""
    url = f"{base_url.rstrip('/')}/v1/models"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [m["id"] for m in data.get("data", [])]


async def cmd_model(args: str, config: AppConfig) -> bool:
    """选择当前使用的模型

    支持以下功能:
    - 无参数:显示所有可用模型列表并交互式选择
    - <模型名称>:直接切换到指定模型(支持精确匹配)
    - <搜索关键词>:模糊搜索匹配的模型,如果只有一个结果则直接切换,否则列出供选择
    - 自动检测已配置的提供商(OpenAI / Anthropic),两个都配了可以切换

    Args:
        args: 模型名称或搜索关键词
        config: 配置对象

    Returns:
        bool: 始终返回 True 表示命令执行完成
    """
    # 检测已配置的提供商
    has_openai = bool(config.OPENAI_API_KEY and config.OPENAI_BASE_URL)
    has_anthropic = bool(config.ANTHROPIC_API_KEY)

    if not has_openai and not has_anthropic:
        warn("未配置任何 API Key,请先运行配置向导", config)
        return True

    # 选择提供商
    if has_openai and has_anthropic:
        # 两个都配了,让用户选择
        providers = [Provider.OPENAI, Provider.ANTHROPIC]
        current_provider = config.provider or Provider.OPENAI

        if not config.interactive:
            # 微信等非交互模式:打印提供商列表
            info(f"\n已配置的提供商:", config)
            for i, p in enumerate(providers, 1):
                marker = " ← 当前" if p == current_provider else ""
                info(f"  [{i}] {p.upper()}{marker}", config)
            info(f"  [3] 全部", config)
            info(f"当前提供商: {current_provider.upper()}", config)
            info("使用 /model <编号> 切换提供商,或 /model <模型名> 切换模型", config)
            # 非交互模式(微信等)默认显示全部
            selected_provider = None
        else:
            from uniclaw.console.run import tui_input
            provider_list = "\n".join(
                f"  [{i}] {p.upper()}" + (" ← 当前" if p == current_provider else "")
                for i, p in enumerate(providers, 1)
            )
            choice = await tui_input(
                f"\n已配置的提供商:\n{provider_list}\n  [3] 全部\n选择 (1-3, 回车使用当前): "
            )
            choice = choice.strip()
            if choice == "3":
                selected_provider = None  # 全部
            elif choice in ("1", "2"):
                selected_provider = providers[int(choice) - 1]
            elif choice == "":
                selected_provider = current_provider
            else:
                warn("无效选择", config)
                return True
    elif has_openai:
        selected_provider = Provider.OPENAI
    else:
        selected_provider = Provider.ANTHROPIC

    # 获取模型列表
    models = []
    if selected_provider in (Provider.OPENAI, None) and config.OPENAI_API_KEY:
        try:
            openai_models = await fetch_openai_models(config.OPENAI_BASE_URL, config.OPENAI_API_KEY)
            models.extend((Provider.OPENAI, m) for m in openai_models)
        except Exception as e:
            err(f"获取 OpenAI 模型列表失败: {e}", config)
            return True
    if selected_provider in (Provider.ANTHROPIC, None) and config.ANTHROPIC_API_KEY:
        try:
            anthropic_base = config.ANTHROPIC_BASE_URL or "https://api.anthropic.com"
            anthropic_models = await fetch_anthropic_models(anthropic_base, config.ANTHROPIC_API_KEY)
            models.extend((Provider.ANTHROPIC, m) for m in anthropic_models)
        except Exception:
            info("当前 Anthropic 兼容接口暂不支持自动获取模型列表", config)

    if not models:
        warn("未找到可用模型,请使用 /model <模型名称> 直接指定", config)
        return True

    # 如果指定了参数,尝试搜索或精确匹配
    if args:
        search_keyword = args.strip().lower()

        # 精确匹配
        for p, m in models:
            if args == m:
                config.model_name = args
                config.provider = p
                save_config(config)
                ok(f"✓ 已切换到: {args} ({p.upper()})", config)
                return True

        # 模糊搜索
        matched = [(p, m) for p, m in models if search_keyword in m.lower()]

        if not matched:
            err(f"未找到匹配的模型: {args}", config)
            info("提示: 输入不带参数的 /model 可查看所有可用模型", config)
            return True

        if len(matched) == 1:
            p, m = matched[0]
            config.model_name = m
            config.provider = p
            save_config(config)
            ok(f"✓ 已切换到: {m} ({p.upper()})", config)
            return True

        models = matched
        info(f"\n找到 {len(matched)} 个匹配的模型:", config)

    # 显示模型列表
    current = config.model_name
    prompt_list = ["\n可用模型:"]
    for i, (p, m) in enumerate(models, 1):
        marker = " ← 当前" if m == current else ""
        prompt_list.append(f"  [{i}] {m} ({p.upper()}){marker}")

    if not config.interactive:
        info("\n".join(prompt_list), config)
        info("\n请使用 /model <模型名称> 切换模型", config)
        return True

    from uniclaw.console.run import tui_input

    choice = (
        await tui_input("\n".join(prompt_list) + "\n请输入模型编号 (回车取消): ")
    ).strip()
    if not choice:
        return True

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            p, m = models[idx]
            config.model_name = m
            config.provider = p
            save_config(config)
            ok(f"✓ 已切换到: {m} ({p.upper()})", config)
    except ValueError:
        pass

    return True
