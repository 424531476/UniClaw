import platform

# 无需权限提示即可安全运行的前缀
_SAFE_PREFIXES = (
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "pwd",
    "echo",
    "printf",
    "date",
    "which",
    "type",
    "env",
    "printenv",
    "uname",
    "whoami",
    "id",
    "git log",
    "git status",
    "git diff",
    "git show",
    "git branch",
    "git remote",
    "git stash list",
    "git tag",
    "find ",
    "grep ",
    "rg ",
    "ag ",
    "fd ",
    "python ",
    "python3 ",
    "node ",
    "ruby ",
    "perl ",
    "pip show",
    "pip list",
    "npm list",
    "cargo metadata",
    "df ",
    "du ",
    "free ",
    "top -bn",
    "ps ",
    "curl -I",
    "curl --head",
    # "dir ",
)


_CHAIN_OPERATORS = (";", "&&", "||", "|", "`", "$(", "\n")


def is_safe_bash(cmd: str) -> bool:
    """如果命令是只读的且从不需要权限提示，则返回 True。

    拒绝包含 shell 链式操作符（;、&&、||、|、反引号、$(…)）的命令
    — 这些可能在安全前缀后执行任意代码。
    """
    c = cmd.strip()
    # 拒绝任何链接多个命令的命令
    if any(op in c for op in _CHAIN_OPERATORS):
        return False
    return any(c.startswith(p) for p in _SAFE_PREFIXES)


def bash_desc(cmd: str, config) -> str:
    """
    获取命令的描述

    使用 AI 分析命令行参数的功能和潜在安全风险。

    Args:
        cmd: 要分析的命令行字符串
        config: 配置对象，包含模型参数等信息

    Returns:
        AI 生成的命令描述和安全风险评估文本
    """
    from llm import chat

    # 构建提示词
    system_prompt = """你是一个命令行安全分析专家。请分析用户提供的 shell 命令，并返回以下信息：

1. **命令功能**：简要说明这个命令的作用和预期效果
2. **安全风险评估**：评估执行此命令可能带来的安全风险（如文件修改、系统配置更改、数据泄露等）
3. **风险等级**：给出风险等级（低/中/高）

请以简洁清晰的中文回答，控制在 200 字以内。

# 环境
- 平台：{platform}
""".format(
        platform=platform.system()
    )
    user_prompt = f"请分析以下命令：\n``bash\n{cmd}\n```"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        # 调用 LLM 进行分析
        response = chat(
            messages=messages,
            model_name=config["mini_model_name"],
        )

        return response.content
    except Exception as e:
        # 如果 AI 调用失败，返回错误信息
        return f"⚠️ 无法获取命令分析：{str(e)}"
