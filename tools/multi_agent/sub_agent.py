from dataclasses import dataclass, field
from typing import Dict
from context import Scope, get_app_dir
from utils.frontmatter import parse_frontmatter


@dataclass
class AgentDefinition:
    """专用代理类型的定义。"""

    name: str
    description: str = ""
    system_prompt: str = ""  # 附加指令，前置到基础系统提示之前
    model_name: str = ""  # 模型覆盖；"" 表示从父级继承
    tools: list = field(default_factory=list)  # 空列表 = 所有工具
    source: str = "user"  # "built-in" | "user" | "project"


BUILTIN_AGENT_DEFINITIONS: Dict[str, AgentDefinition] = {
    "general-purpose": AgentDefinition(
        name="general-purpose",
        description=("通用代理，用于研究复杂问题、" "搜索代码以及执行多步骤任务。"),
        system_prompt="",
        source="built-in",
    ),
    "coder": AgentDefinition(
        name="coder",
        description="专门用于编写、阅读和修改代码的编程代理。",
        system_prompt=(
            "你是一个专门的编程助手。专注于：\n"
            "- 编写干净、地道的代码\n"
            "- 在修改之前先阅读和理解现有代码\n"
            "- 进行最小化的针对性更改\n"
            "- 绝不添加不必要的功能、注释或错误处理\n"
        ),
        source="built-in",
    ),
    "reviewer": AgentDefinition(
        name="reviewer",
        description="分析质量、安全性和正确性的代码审查代理。",
        system_prompt=(
            "你是一名代码审查员。分析代码的：\n"
            "- 正确性和逻辑错误\n"
            "- 安全漏洞（注入、XSS、认证绕过等）\n"
            "- 性能问题\n"
            "- 代码质量和可维护性\n"
            "简洁具体。将发现分类为：严重 | 警告 | 建议。\n"
        ),
        tools=["Read", "Glob", "Grep"],
        source="built-in",
    ),
    "researcher": AgentDefinition(
        name="researcher",
        description="用于探索代码库和回答问题的研究代理。",
        system_prompt=(
            "你是一名研究助理，专注于理解代码库。\n"
            "- 在回答之前彻底阅读和分析代码\n"
            "- 提供基于事实、有证据的答案\n"
            "- 引用具体的文件路径和行号\n"
            "- 保持简洁和专注\n"
        ),
        tools=["Read", "Glob", "Grep", "WebFetch", "WebSearch"],
        source="built-in",
    ),
    "tester": AgentDefinition(
        name="tester",
        description="编写和运行测试的测试代理。",
        system_prompt=(
            "你是一名测试专家。你的工作：\n"
            "- 为给定代码编写全面的测试\n"
            "- 运行现有测试并诊断失败原因\n"
            "- 关注边界情况和错误条件\n"
            "- 保持测试简单、可读且快速\n"
        ),
        source="built-in",
    ),
}


def load_agent_definitions_from_scope(
    scope: Scope = Scope.USER.value,
) -> Dict[str, AgentDefinition]:
    user_dir = get_app_dir(scope) / "agents"
    defs = dict()
    for p in user_dir.glob("*.md"):
        metadata, system_prompt = parse_frontmatter(p)
        agent_def = AgentDefinition(
            name=metadata["name"],
            description=metadata.get("description", ""),
            system_prompt=system_prompt,
            model=metadata.get("model", ""),
            tools=metadata.get("tools", []),
            source="user",
        )
        defs[agent_def.name] = agent_def
    return defs


def load_agent_definitions() -> Dict[str, AgentDefinition]:
    defs = dict(BUILTIN_AGENT_DEFINITIONS)
    defs.update(load_agent_definitions_from_scope(Scope.USER.value))
    defs.update(load_agent_definitions_from_scope(Scope.PROJECT.value))
    return defs
