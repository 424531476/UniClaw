import httpx
from uniclaw.agent import AgentTask
from uniclaw.console.ui import info, ok, warn, err

# 子命令列表
SUBCOMMANDS = ["list", "set"]


def fetch_models(base_url: str, api_key: str) -> list[str]:
    """通过 base_url 和 api_key 获取可用模型列表
    
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


def cmd_model(args: str, task: AgentTask, config: dict) -> bool:
    """选择当前使用的模型

    支持以下功能:
    - 无参数:显示所有可用模型列表并交互式选择
    - <模型名称>:直接切换到指定模型(支持精确匹配)
    - <搜索关键词>:模糊搜索匹配的模型,如果只有一个结果则直接切换,否则列出供选择

    Args:
        args: 模型名称或搜索关键词
            - 如果为空,显示所有可用模型列表
            - 如果包含空格,作为搜索关键词过滤模型
            - 如果是完整模型名,直接切换
        task: 当前代理任务对象
        config: 配置字典,包含 model_name、OPENAI_BASE_URL、OPENAI_API_KEY 等配置
        
    Returns:
        bool: 始终返回 True 表示命令执行完成
    """
    base_url = config.get("OPENAI_BASE_URL")
    api_key = config.get("OPENAI_API_KEY")

    if not base_url or not api_key:
        warn("未配置 OPENAI_BASE_URL 或 OPENAI_API_KEY")
        return True

    try:
        models = fetch_models(base_url, api_key)
    except Exception as e:
        err(f"获取模型列表失败: {e}")
        return True

    if not models:
        warn("未找到可用模型")
        return True
    models.sort()
    # 如果指定了参数,尝试搜索或精确匹配
    if args:
        search_keyword = args.strip().lower()

        # 首先尝试精确匹配
        if args in models:
            config["model_name"] = args
            ok(f"✓ 已切换到: {args}")
            return True

        # 进行模糊搜索
        matched_models = [m for m in models if search_keyword in m.lower()]

        if not matched_models:
            err(f"未找到匹配的模型: {args}")
            info("提示: 输入不带参数的 /model 可查看所有可用模型")
            return True

        if len(matched_models) == 1:
            # 只有一个匹配结果,直接切换
            selected = matched_models[0]
            config["model_name"] = selected
            ok(f"✓ 已切换到: {selected}")
            return True

        # 多个匹配结果,使用通用选择逻辑
        models = matched_models
        info(f"\n找到 {len(matched_models)} 个匹配的模型:")

    # 无参数或搜索到多个结果时显示模型列表
    current = config.get("model_name")
    prompt_list = ["\n可用模型:"]
    for i, m in enumerate(models, 1):
        marker = " ← 当前" if m == current else ""
        prompt_list.append(f"  [{i}] {m}{marker}")

    if not config.get("interactive", True):
        info("\n".join(prompt_list))
        info("\n请使用 /model <模型名称> 切换模型")
        return True

    from uniclaw.console.run import tui_input

    choice = tui_input("\n".join(prompt_list) + "\n请输入模型编号 (回车取消): ").strip()
    if not choice:
        return True

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            config["model_name"] = models[idx]
            ok(f"✓ 已切换到: {models[idx]}")
    except ValueError:
        pass

    return True
