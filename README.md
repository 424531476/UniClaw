# UniClaws - 友灵龙虾 🦞

[![Python Version](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**UniClaws（友灵龙虾）** 是一个基于大语言模型的智能代理系统，提供交互式命令行界面，支持文件操作、Shell 命令执行、网络搜索等丰富功能。通过模块化的工具系统和权限管理机制，帮助用户高效完成各种编程和文本处理任务。

## ✨ 特性

- 🤖 **智能代理**: 基于 LangChain 和 OpenAI API 的对话式 AI 助手
- 🛠️ **丰富的工具集**: 内置文件系统操作、Shell 命令、网络搜索、技能系统等工具
- 🔒 **权限管理**: 支持多种权限模式（自动/手动/全部接受），保障操作安全
- 💭 **实时反馈**: 显示思考过程、工具调用详情和 Token 使用情况
- 📊 **上下文管理**: 自动监控和管理对话上下文长度，支持压缩优化
- 🎯 **技能系统**: 可扩展的技能机制，支持自定义任务模板和工作流
- 🌐 **跨平台支持**: 兼容 Windows、Linux 和 macOS 系统

## 📋 目录

- [安装](#-安装)
- [快速开始](#-快速开始)
- [配置说明](#-配置说明)
- [使用指南](#-使用指南)
- [工具系统](#-工具系统)
- [架构设计](#-架构设计)
- [常见问题](#-常见问题)

## 🚀 安装

### 前置要求

- Python 3.14 或更高版本
- uv 包管理器（推荐）

### 安装步骤

**使用 uv 安装依赖**

```
# 安装项目依赖
uv sync

# 或者安装开发依赖（包含测试工具）
uv sync --group dev
```

**配置环境变量**

在项目根目录创建 `.env` 文件：

```
# OpenAI API 配置
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1

# 模型配置
MODEL_NAME=openai/gpt-5.4
MINI_MODEL_NAME=  # 可选，用于简单任务的快速小模型
TEMPERATURE=0.7
MAX_TOKENS=1024
TOP_P=1.0

# 权限模式 (auto/manual/accept-all/plan)
PERMISSION_MODE=auto

# 代理配置（可选）
PROXY_URL=http://127.0.0.1:7890
```

**运行项目**

```
# 使用 uv 运行
uv run python main.py

# 或者直接运行（需要先激活虚拟环境）
uv run main.py
```

**常用 uv 命令**

```
# 添加新依赖
uv add <package-name>

# 添加开发依赖
uv add --dev <package-name>

# 运行测试
uv run pytest tests/ -v

# 更新依赖
uv lock --upgrade
```

## 🎯 快速开始

### 启动交互式会话

```
python main.py
```

启动后将进入 REPL (Read-Eval-Print Loop) 交互界面：

```
D:\code\learn\UniClaws  5.23% » 你好，请介绍一下自己
💭 [思考中]
我是一个AI助手...

📝 [回复]
你好！我是 友灵龙虾 助手...
```

### 基本用法

- **直接输入**: 与 AI 助手进行对话
- **! 命令**: 执行 Shell 命令（例如 `!ls -la`）
- **空行**: 跳过当前输入
- **Token 提示**: 右侧显示当前上下文使用率（颜色指示：绿色<40%，黄色40-70%，红色>70%）

## ⚙️ 配置说明

### 环境变量配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `OPENAI_API_KEY` | OpenAI API 密钥 | 必需 | `sk-xxx` |
| `OPENAI_BASE_URL` | API 基础 URL | OpenAI 官方地址 | `https://api.openai.com/v1` |
| `MODEL_NAME` | 主模型名称（用于复杂任务） | 无 | `openai/gpt-5.4`, `gpt-4o` |
| `MINI_MODEL_NAME` | 迷你模型名称（用于简单任务，可选） | 自动使用 MODEL_NAME | `gpt-3.5-turbo` |
| `TEMPERATURE` | 生成温度（创造性） | `0.7` | `0.0`-`2.0` |
| `MAX_TOKENS` | 最大输出 token 数 | `1024` | `512`, `2048` |
| `TOP_P` | 核采样概率 | `1.0` | `0.9` |
| `PERMISSION_MODE` | 权限模式 | `auto` | `auto`/`manual`/`accept-all`/`plan` |
| `PROXY_URL` | HTTP 代理地址 | 无 | `http://127.0.0.1:7890` |

### 权限模式说明

- **auto**: 自动批准读取类操作，对写入和不安全的 Bash 命令询问用户
- **manual**: 所有工具调用都需要用户手动确认
- **accept-all**: 自动批准所有操作（谨慎使用）
- **plan**: 计划模式（开发中）

## 📖 使用指南

### 交互式会话功能

#### Token 使用监控

会话界面会实时显示当前上下文的 Token 使用率：

- 🟢 **绿色 (<40%)**: 使用率低，空间充足
- 🟡 **黄色 (40-70%)**: 使用率中等，注意控制
- 🔴 **红色 (>70%)**: 使用率高，接近限制

#### 事件类型展示

系统会显示以下事件类型：

- 💭 **思考中**: AI 的思考过程
- 📝 **回复**: AI 的文本回复
- 🤖 **助手元数据**: 工具调用数量、参数、Token 使用统计
- 🔧 **工具执行**: 工具名称、调用 ID、执行结果

### 快捷命令

在 REPL 中输入 `!` 开头的命令可直接执行 Shell 命令：

```
D:\code\learn\UniClaws  5.23% » !python --version
  $ python --version
Python 3.14.0
```

## 🛠️ 工具系统

UniClaws 提供了丰富的内置工具，AI 助手可以自动调用这些工具完成任务。

### 文件系统工具

- **Read** - 读取文件内容（支持指定行范围和偏移量）
- **Write** - 写入或创建文件（自动创建父目录，返回差异报告）
- **Edit** - 精确替换文件中的字符串（支持统一差异格式）
- **Glob** - 根据通配符模式搜索文件（如 `*.py`, `**/*.txt`）

### Shell 工具

- **Bash** - 执行 Shell 命令（支持超时控制，跨平台兼容）
- **Grep** - 在文件中搜索文本模式（优先使用 ripgrep，支持正则表达式）
- **search_files_with_everything** - 使用 Everything 引擎快速搜索文件名（仅 Windows）
- **get_current_time** - 获取当前系统时间

### Web 工具

- **webfetch** - 抓取网页内容并提取纯文本（自动清理 HTML 标签）
- **websearch** - 使用 DuckDuckGo 执行网络搜索（返回格式化的搜索结果）

### 技能系统

- **skill_tool** - 执行预定义的技能任务（可扩展的自定义工作流）
- **skill_list** - 查看可用技能列表及详细信息

> 💡 **提示**: AI 会根据任务需求自动选择合适的工具，无需手动调用。所有工具都具备完善的错误处理和权限控制机制。

## 🏗️ 架构设计

### 核心组件

```
UniClaws/
├── main.py                 # 程序入口
├── agent.py                # 核心代理逻辑（消息循环、工具调用）
├── llm.py                  # LLM 流式响应封装
├── config.py               # 配置管理（环境变量加载）
├── context.py              # 上下文管理和提示词构建
├── compaction.py           # 上下文压缩和优化
│
├── console/                # 控制台交互界面
│   ├── run.py             # REPL 主循环
│   └── ui.py              # UI 渲染和颜色输出
│
├── tools/                  # 工具系统
│   ├── __init__.py        # 工具注册
│   ├── fs.py              # 文件系统工具（Read/Write/Edit/Glob）
│   ├── shell.py           # Shell 工具（Bash/Grep/Everything）
│   ├── web.py             # Web 工具（webfetch/websearch）
│   ├── security.py        # 安全检查（is_safe_bash）
│   └── skill/             # 技能系统
│       ├── loader.py      # 技能加载器
│       └── tools.py       # 技能工具
│
├── utils/                  # 实用工具
│   ├── frontmatter.py     # Markdown Frontmatter 解析
│   └── truncation.py      # 文本截断和长度控制
│
└── tests/                  # 测试用例
    ├── test_frontmatter.py
    └── test_utils.py
```

### 工作流程

1. **用户输入** → REPL 接收用户消息
2. **上下文构建** → 添加系统提示词和历史消息
3. **LLM 推理** → 流式调用 OpenAI API
4. **工具调用** → 解析工具调用请求，检查权限
5. **权限验证** → 根据权限模式决定是否询问用户
6. **工具执行** → 执行工具并收集结果
7. **结果反馈** → 将工具结果返回给 LLM
8. **循环迭代** → 重复步骤 3-7 直到任务完成

### 数据流

```
User Input
    ↓
AgentState (messages history)
    ↓
LLM Stream Response
    ↓
AssistantEvent (content + tool_calls)
    ↓
Permission Check
    ↓
Tool Execution
    ↓
ToolEvent (result)
    ↓
Update AgentState
    ↓
Next Iteration or Final Response
```

## ❓ 常见问题

### Q: 如何更换 LLM 提供商？

A: 修改 `.env` 文件中的 `OPENAI_BASE_URL` 和 `MODEL_NAME`，支持任何兼容 OpenAI API 的服务商（如 Azure OpenAI、Ollama、LocalAI 等）。

### Q: Token 使用率过高怎么办？

A: 系统会自动进行上下文压缩。你也可以：
- 开始新的会话（重启程序）
- 减少单次对话的长度
- 使用更简洁的提示词

### Q: 如何启用 Everything 搜索？

A: 
1. 下载并安装 [Everything](https://www.voidtools.com/)
2. 确保 `es.exe` 在系统 PATH 中
3. 重启 UniClaws

### Q: 权限模式如何选择？

A:
- **开发环境**: 使用 `accept-all` 提高效率
- **生产环境**: 使用 `auto` 或 `manual` 保证安全
- **敏感操作**: 始终使用 `manual` 模式

### Q: 支持哪些操作系统？

A: 支持 Windows、Linux 和 macOS。部分工具（如 Everything 搜索）仅在 Windows 上可用。

### Q: 如何调试工具调用？

A: REPL 界面会显示详细的工具调用信息：
- 工具名称和参数
- 调用 ID
- 执行结果（截断至 3000 字符）
- Token 使用统计

## 📄 许可证

本项目采用 MIT 许可证。

---

**Made with ❤️ by UniClaws Team**
