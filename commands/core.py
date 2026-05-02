import httpx
import os
from compaction import compact_messages, estimate_tokens


def cmd_compact(args: str, state, config) -> bool:
    """手动压缩对话历史"""
    focus = args.strip() if args else ""
    before = estimate_tokens(state.messages)
    state.messages = compact_messages(state.messages, config, focus=focus)
    after = estimate_tokens(state.messages)
    saved = before - after
    print(f"✓ 对话已压缩: {before} → {after} tokens（节省 {saved} tokens）{'（聚焦: ' + focus + '）' if focus else ''}")
    return True


def cmd_clear(_args: str, state, _config) -> bool:
    """清除当前会话上下文和屏幕"""
    import subprocess
    subprocess.run("cls" if subprocess.os.name == "nt" else "clear", shell=True)
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


def cmd_cwd(args: str, _state, _config) -> bool:
    """显示或更改当前工作目录"""
    if not args.strip():
        # 无参数时显示当前工作目录
        current_dir = os.getcwd()
        print(f"当前工作目录: {current_dir}")
    else:
        # 有参数时切换到指定目录
        import pathlib
        target_path = pathlib.Path(args.strip()).resolve()
        if not target_path.exists():
            print(f"错误: 目录不存在: {args.strip()}")
            return True
        if not target_path.is_dir():
            print(f"错误: 不是目录: {args.strip()}")
            return True
        try:
            os.chdir(str(target_path))
            print(f"工作目录已切换到: {target_path}")
        except Exception as e:
            print(f"错误: {e}")
    return True
