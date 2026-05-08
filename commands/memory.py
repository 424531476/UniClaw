from console.ui import info, ok, warn, err


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
