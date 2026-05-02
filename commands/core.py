import httpx
import json
import os
from datetime import datetime
from pathlib import Path
from compaction import compact_messages, estimate_tokens
from console.ui import info, ok, warn, err


def cmd_compact(args: str, state, config) -> bool:
    """手动压缩对话历史"""
    focus = args.strip() if args else ""
    model_name = config.get("model_name")
    before = estimate_tokens(state.messages, model_name)
    state.messages = compact_messages(state.messages, config, focus=focus)
    after = estimate_tokens(state.messages, model_name)
    saved = before - after
    ok(f"✓ 对话已压缩: {before} → {after} tokens（节省 {saved} tokens）{'（聚焦: ' + focus + '）' if focus else ''}")
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
    """选择当前使用的模型
    
    参数说明:
        args: 模型名称或搜索关键词
            - 如果为空，显示所有可用模型列表
            - 如果包含空格，作为搜索关键词过滤模型
            - 如果是完整模型名，直接切换
        
    返回值:
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

    # 如果指定了参数，尝试搜索或精确匹配
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
            # 只有一个匹配结果，直接切换
            selected = matched_models[0]
            config["model_name"] = selected
            ok(f"✓ 已切换到: {selected}")
            return True
        
        # 多个匹配结果，使用通用选择逻辑
        models = matched_models
        info(f"\n找到 {len(matched_models)} 个匹配的模型:")

    # 无参数或搜索到多个结果时显示模型列表
    current = config.get("model_name")
    info("\n可用模型:")
    for i, m in enumerate(models, 1):
        marker = " ← 当前" if m == current else ""
        print(f"  [{i}] {m}{marker}")

    try:
        from prompt_toolkit import prompt
        choice = prompt("\n请输入模型编号 (回车取消): ").strip()
    except ImportError:
        choice = input("\n请输入模型编号 (回车取消): ").strip()
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


def cmd_cwd(args: str, _state, _config) -> bool:
    """显示或更改当前工作目录"""
    if not args.strip():
        # 无参数时显示当前工作目录
        current_dir = os.getcwd()
        info(f"当前工作目录: {current_dir}")
    else:
        # 有参数时切换到指定目录
        import pathlib
        target_path = pathlib.Path(args.strip()).resolve()
        if not target_path.exists():
            err(f"目录不存在: {args.strip()}")
            return True
        if not target_path.is_dir():
            err(f"不是目录: {args.strip()}")
            return True
        try:
            os.chdir(str(target_path))
            ok(f"工作目录已切换到: {target_path}")
        except Exception as e:
            err(str(e))
    return True


def cmd_skills(_args: str, _state, config) -> bool:
    """列出所有可用的技能"""
    from tools.skill.loader import load_skills
    
    skills = load_skills()
    if not skills:
        warn("当前没有可用的技能")
        return True
    
    # 按来源分组
    groups = {
        "builtin": ("【内置技能】", []),
        "user": ("【用户技能】", []),
        "project": ("【项目技能】", [])
    }
    
    for skill in skills:
        if skill.source in groups:
            groups[skill.source][1].append(skill)
    
    info(f"\n可用技能 (共 {len(skills)} 个):\n")
    
    # 统一处理每个分组
    for source_key, (title, skill_list) in groups.items():
        if not skill_list:
            continue
        
        print(title)
        for skill in skill_list:
            triggers = ", ".join(skill.triggers[:3])
            if len(skill.triggers) > 3:
                triggers += f" (+{len(skill.triggers) - 3})"
            print(f"  • {skill.name}: {skill.description}")
            print(f"    触发器: {triggers}")
            if skill.when_to_use:
                print(f"    使用时机: {skill.when_to_use}")
            if skill.argument_hint:
                print(f"    参数提示: {skill.argument_hint}")
            print()
    
    return True


def cmd_export(args: str, state, _config) -> bool:
    """导出当前对话消息到文件"""
    from pathlib import Path
    from context import get_app_dir, Scope
    import json
    from datetime import datetime
    
    # 确定导出路径和格式
    if args.strip():
        # 用户提供了路径
        export_path = Path(args.strip())
        # 如果是相对路径，转换为绝对路径
        if not export_path.is_absolute():
            export_path = Path.cwd() / export_path
        # 根据扩展名决定格式
        use_json = export_path.suffix.lower() == '.json'
    else:
        # 使用默认路径：get_app_dir()/"exports"，默认使用 md 格式
        exports_dir = get_app_dir(Scope.USER.value) / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成带时间戳的文件名，默认使用 .md 格式
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = exports_dir / f"conversation_{timestamp}.md"
        use_json = False
    
    # 确保父目录存在
    export_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        if use_json:
            # JSON 格式导出
            export_data = {
                "exported_at": datetime.now().isoformat(),
                "message_count": len(state.messages),
                "total_input_tokens": state.total_input_tokens,
                "total_output_tokens": state.total_output_tokens,
                "turn_count": state.turn_count,
                "messages": state.messages
            }
            
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
        else:
            # Markdown 格式导出
            md_content = f"""# 对话导出

**导出时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**消息数量**: {len(state.messages)}  
**总输入 Token**: {state.total_input_tokens}  
**总输出 Token**: {state.total_output_tokens}  
**对话轮次**: {state.turn_count}

---

"""
            
            # 添加消息内容
            for i, msg in enumerate(state.messages, 1):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                
                # 根据角色设置标题
                if role == "user":
                    md_content += f"## 用户 (第 {i} 条)\n\n"
                elif role == "assistant":
                    md_content += f"## 助手 (第 {i} 条)\n\n"
                elif role == "system":
                    md_content += f"## 系统 (第 {i} 条)\n\n"
                else:
                    md_content += f"## {role} (第 {i} 条)\n\n"
                
                # 添加内容
                if isinstance(content, str):
                    md_content += f"{content}\n\n"
                else:
                    # 如果内容是列表或其他类型，转换为字符串
                    md_content += f"```\n{content}\n```\n\n"
                
                md_content += "---\n\n"
            
            with open(export_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
        
        ok(f"✓ 对话已导出: {export_path}")
        info(f"导出格式: {'JSON' if use_json else 'Markdown'}")
        info(f"消息数量: {len(state.messages)}")
        info(f"总输入 Token: {state.total_input_tokens}")
        info(f"总输出 Token: {state.total_output_tokens}")
    except Exception as e:
        err(f"导出失败: {e}")
        return False
    
    return True


def cmd_memory(args: str, state, config) -> bool:
    """记忆管理：无参数列出详情，<关键词>搜索，consolidate 提取"""
    from tools.memory.memory import Memory
    from tools.memory.context import ai_select_memories
    from tools.memory.consolidate import consolidate_session
    from context import Scope

    query = args.strip()

    # /memory consolidate — 从当前对话提取记忆
    if query == "consolidate":
        if not state.messages:
            warn("当前没有对话消息")
            return True
        info("正在分析对话并提取记忆...")
        memories = consolidate_session(state.messages, config)
        if not memories:
            warn("未提取到值得保存的记忆")
            return True
        ok(f"✓ 已提取并保存 {len(memories)} 条记忆:")
        for mem in memories:
            print(f"  • [{mem.type}] {mem.name}: {mem.description}")
        return True

    # /memory — 列出所有记忆详情
    all_memories = Memory.load_all_memories(Scope.ALL.value)
    if not all_memories:
        warn("暂无记忆")
        return True

    # /memory <关键词> — AI 搜索相关记忆
    if query:
        results = ai_select_memories(query, all_memories, max_results=5)
        if not results:
            warn(f"未找到与「{query}」相关的记忆")
            return True
        info(f"\n找到 {len(results)} 条相关记忆:\n")
        for r in results:
            print(f"  [{r['type']}] {r['name']}")
            print(f"    {r['description']}")
            print(f"    置信度: {r['confidence']}  来源: {r['source']}  作用域: {r['scope']}")
            if r.get("freshness_text"):
                print(f"    {r['freshness_text']}")
            print()
        return True

    # 无参数 — 列出全部记忆详情
    info(f"\n共 {len(all_memories)} 条记忆:\n")
    for mem in all_memories:
        print(f"  [{mem.type}] {mem.name}")
        print(f"    {mem.description}")
        print(f"    置信度: {mem.confidence}  来源: {mem.source}  作用域: {mem.scope}")
        if mem.created:
            print(f"    创建时间: {mem.created}")
        if mem.last_used_at:
            print(f"    最后使用: {mem.last_used_at}")
        print()
    return True


def cmd_exit(_args: str, _state, _config) -> bool:
    """退出程序"""
    ok("再见！")
    raise SystemExit(0)

