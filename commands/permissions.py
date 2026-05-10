from console.ui import info, ok, warn, err


def cmd_permissions(args: str, state, config) -> bool:
    """权限规则管理: list, remove <type> <pattern>"""
    from tools.security import list_permission_rules, remove_permission_rule

    parts = args.strip().split()

    if not parts or parts[0] == "list":
        rules = list_permission_rules()
        if not rules:
            warn("暂无保存的权限规则")
            return True
        info(f"\n共 {len(rules)} 条权限规则:\n")
        for i, r in enumerate(rules, 1):
            created = r.get("created", "")
            print(f"  {i}. [{r['type']}] {r['pattern']}  (创建: {created})")
        print(f"\n使用 /permissions remove <type> <pattern> 删除规则")
        return True

    if parts[0] == "remove" and len(parts) >= 3:
        rule_type = parts[1]
        pattern = " ".join(parts[2:])
        if remove_permission_rule(rule_type, pattern):
            ok(f"已删除规则: [{rule_type}] {pattern}")
        else:
            err(f"未找到规则: [{rule_type}] {pattern}")
        return True

    warn("用法: /permissions [list] 或 /permissions remove <type> <pattern>")
    return True
