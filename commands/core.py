import httpx


def cmd_clear(_args: str, state, _config) -> bool:
    """清除当前会话上下文"""
    state.messages.clear()
    return True


def fetch_models(base_url: str, api_key: str) -> list[str]:
    """通过 base_url 和 api_key 获取可用模型列表"""
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = httpx.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [m["id"] for m in data.get("data", [])]


def cmd_model(args: str, _state, config) -> bool:
    """选择当前使用的模型"""
    base_url = config.get("OPENAI_BASE_URL")
    api_key = config.get("OPENAI_API_KEY")

    if not base_url or not api_key:
        print("⚠️ 未配置 OPENAI_BASE_URL 或 OPENAI_API_KEY")
        return True

    try:
        models = fetch_models(base_url, api_key)
    except Exception as e:
        print(f"⚠️ 获取模型列表失败: {e}")
        return True

    if not models:
        print("⚠️ 未找到可用模型")
        return True

    # 如果指定了模型名，直接检查并切换
    if args:
        if args in models:
            config["model_name"] = args
            print(f"✓ 已切换到: {args}")
        else:
            print(f"⚠️ 模型不存在: {args}")
        return True

    current = config.get("model_name")
    print("\n可用模型:")
    for i, m in enumerate(models, 1):
        marker = " ← 当前" if m == current else ""
        print(f"  [{i}] {m}{marker}")

    choice = input("\n请输入模型编号 (回车取消): ").strip()
    if not choice:
        return True

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            config["model_name"] = models[idx]
            print(f"✓ 已切换到: {models[idx]}")
    except ValueError:
        pass

    return True
