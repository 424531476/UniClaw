from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict
from uniclaw.context import Scope, get_app_dir
from uniclaw.tools.fs import Glob, Read, Write
from uniclaw.tools.shell import Grep
from uniclaw.tools.web import webSearch, webFetch
from uniclaw.utils.frontmatter import parse_frontmatter


@dataclass
class AgentDefinition:
    """专用代理类型的定义。"""

    name: str
    description: str = ""
    system_prompt: str = ""  # 附加指令,前置到基础系统提示之前
    model_name: str = ""  # 模型覆盖；"" 表示从父级继承
    tools: list = field(default_factory=list)  # 空列表 = 所有工具
    source: str = "user"  # "built-in" | "user" | "project"


def get_builtin_agent_definitions() -> Dict[str, AgentDefinition]:
    """获取内置专用代理定义"""

    BUILTIN_AGENT_DEFINITIONS: Dict[str, AgentDefinition] = {
        "general-purpose": AgentDefinition(
            name="general-purpose",
            description=("通用代理,用于研究复杂问题、" "搜索代码以及执行多步骤任务。"),
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
                "- 安全漏洞(注入、XSS、认证绕过等)\n"
                "- 性能问题\n"
                "- 代码质量和可维护性\n"
                "简洁具体。将发现分类为：严重 | 警告 | 建议。\n"
            ),
            tools=[Read.name, Glob.name, Grep.name],
            source="built-in",
        ),
        "researcher": AgentDefinition(
            name="researcher",
            description="用于探索代码库和回答问题的研究代理。",
            system_prompt=(
                "你是一名研究助理,专注于理解代码库。\n"
                "- 在回答之前彻底阅读和分析代码\n"
                "- 提供基于事实、有证据的答案\n"
                "- 引用具体的文件路径和行号\n"
                "- 保持简洁和专注\n"
            ),
            tools=[Read.name, Glob.name, Grep.name, webFetch.name, webSearch.name],
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
        "project-init": AgentDefinition(
            name="project-init",
            description="专门用于分析项目并生成 CLAUDE.md 文档的代理。",
            system_prompt=(
                "你是一个项目分析专家,专门用于生成 CLAUDE.md 文件。\n\n"
                "你的任务：\n"
                f"1. 使用 {Glob.name} 扫描项目目录结构,了解整体架构\n"
                f"2. 使用 {Read.name} 读取关键配置文件(pyproject.toml、package.json、Cargo.toml 等)\n"
                f"3. 使用 {Grep.name} 搜索项目中的重要模式和约定\n"
                f"4. 分析所有源代码文件,提取模块、类、函数、常量等信息\n"
                f"5. 检测项目类型、框架、依赖和构建工具\n"
                f"6. 生成或更新 CLAUDE.md 文件\n\n"
                "分析范围:\n"
                "- 所有源代码文件(.py、.js、.ts、.go、.rs、.java 等)\n"
                "- 配置文件(.toml、.json、.yaml、.cfg、.ini 等)\n"
                "- 构建和 CI/CD 文件(Makefile、Dockerfile、.github/workflows 等)\n"
                "- 文档和 README 文件\n"
                "- 测试文件和测试配置\n"
                "- 跳过所有以点(.)开头的目录(如 .git、.env、.vscode、__pycache__、node_modules 等)\n\n"
                "生成规则：\n"
                "- 保留现有 CLAUDE.md 中的有用内容(如自定义说明)\n"
                "- 更新过时的信息\n"
                "- 添加新发现的模块和功能\n"
                "- 保持文档简洁、结构清晰\n"
                "- 使用中文编写文档\n\n"
                f"最终使用 {Write.name} 工具将完整的 CLAUDE.md 写入文件。"
            ),
            tools=[Read.name, Glob.name, Grep.name, Write.name],
            source="built-in",
        ),
    }
    return BUILTIN_AGENT_DEFINITIONS


def load_agent_definitions_from_scope(
    root: Scope | Path = Scope.USER,
) -> Dict[str, AgentDefinition]:
    user_dir = get_app_dir(root) / "agents"
    defs = dict()
    for p in user_dir.glob("*.md"):
        metadata, system_prompt = parse_frontmatter(p)
        agent_def = AgentDefinition(
            name=metadata["name"],
            description=metadata.get("description", ""),
            system_prompt=system_prompt,
            model_name=metadata.get("model", ""),
            tools=metadata.get("tools", []),
            source="user",
        )
        defs[agent_def.name] = agent_def
    return defs


def load_agent_definitions(cwd: Path | None = None) -> Dict[str, AgentDefinition]:
    defs = dict(get_builtin_agent_definitions())
    defs.update(load_agent_definitions_from_scope(Scope.USER))
    if cwd:
        defs.update(load_agent_definitions_from_scope(cwd))
    return defs
