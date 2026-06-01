"""内置 Skill 注册"""

from tools.skill.loader import SkillDef, register_builtin

# ── code-review ────────────────────────────────────────────────

_CODE_REVIEW_PROMPT = r"""## 代码审查

对指定目标进行多维度代码审查。

### 目标

如果用户指定了参数 `$ARGUMENTS`,审查该目标(文件路径、PR 编号等)。
否则审查当前未提交的变更:先运行 `git diff --cached`,如果没有暂存内容则运行 `git diff`。

如果 diff 为空,告知用户没有可审查的变更并结束。

### 审查维度

按以下维度逐一分析,每个维度独立评估:

1. **🔒 安全性**
   - SQL 注入、XSS、命令注入、路径遍历
   - 敏感信息硬编码(密钥、密码、token)
   - 权限检查缺失、输入校验不足

2. **🐛 正确性**
   - 边界条件未处理(空值、空列表、溢出)
   - 逻辑错误、条件反转
   - 异常处理缺失或不当
   - 并发安全问题

3. **⚡ 性能**
   - 不必要的循环或重复计算
   - N+1 查询模式
   - 大对象未释放、内存泄漏风险
   - 可缓存但未缓存的计算

4. **🧹 代码质量**
   - 命名不清晰、不符合项目惯例
   - 代码重复、可提取为公共函数
   - 函数过长、职责不单一
   - 魔法数字、硬编码字符串

5. **📖 可读性**
   - 缺少必要注释(复杂逻辑、非显而易见的设计决策)
   - 抽象层次不一致
   - 控制流过深(嵌套 if/for)

### 输出格式

```
## 📋 代码审查报告

**审查范围**: [描述审查了什么]
**变更文件数**: N
**变更行数**: +N / -N

### 发现的问题

按严重程度排序:

🔴 **严重** — 必须修复
- [文件:行号] 问题描述
  > 修复建议: ...

🟡 **警告** — 建议修复
- [文件:行号] 问题描述
  > 修复建议: ...

🔵 **建议** — 可选改进
- [文件:行号] 问题描述
  > 修复建议: ...

### 总结

[一句话总结变更质量和主要风险]
```

### 注意事项

- 只报告**实际存在的问题**,不要猜测或列出"可能"的问题
- 如果代码质量很好,直接说"未发现明显问题"
- 不要审查未变更的代码
- 对于大型 diff(>500 行),重点关注变更部分,不要逐行审查"""


register_builtin(
    SkillDef(
        name="code-review",
        description="审查代码变更,检查安全性、正确性、性能、代码质量和可读性问题。"
        "当用户要求审查代码、检查变更、review diff 时使用。"
        "支持审查当前未提交的变更、指定文件或 PR。",
        triggers=["/code-review", "/review", "code-review"],
        tools=["Bash", "Read", "Grep"],
        prompt=_CODE_REVIEW_PROMPT,
        file_path=__file__,
        source="builtin",
        when_to_use="用户要求审查代码、检查变更、review、找 bug、安全检查时",
        argument_hint="[文件路径或 PR 编号]",
    )
)

# ── commit ──────────────────────────────────────────────────────

_COMMIT_PROMPT = r"""## AI Commit

分析当前变更,自动生成规范的 commit message 并提交。

### 步骤

1. **获取变更内容**
   - 运行 `git diff --cached` 查看已暂存的变更
   - 如果没有暂存内容,运行 `git diff` 查看未暂存的变更
   - 如果都没有变更,告知用户"没有可提交的变更"并结束

2. **生成 Commit Message**
   - 格式遵循 Conventional Commits:`<type>(<scope>): <description>`
   - type 选项:
     - `feat` — 新功能
     - `fix` — Bug 修复
     - `refactor` — 重构(不改变行为)
     - `docs` — 文档变更
     - `style` — 代码格式(不影响逻辑)
     - `test` — 测试相关
     - `chore` — 构建/工具/依赖变更
     - `perf` — 性能优化
     - `ci` — CI/CD 相关
   - scope:变更影响的模块或文件(可选)
   - description:简短描述,不超过 50 字符,使用中文
   - body:如有必要,补充变更动机和上下文(可选)
   - footer:如有 breaking change,标注 `BREAKING CHANGE: <描述>`

3. **向用户确认**
   展示以下内容并询问确认:
   - 变更文件列表(`git status --short`)
   - 生成的 commit message
   - 选项:确认提交 / 修改 message / 取消

4. **执行提交**
   - 如果有未暂存的变更:`git add -A`
   - `git commit -m "<message>"`
   - 输出提交结果

### 用户自定义参数

如果用户提供了参数 `$ARGUMENTS`,将其作为 commit message 的参考或补充说明:
- 如果参数看起来像完整的 commit message,直接使用
- 如果参数是简短描述,将其融入生成的 message 中
- 如果参数为空,完全由 AI 生成"""


register_builtin(
    SkillDef(
        name="commit",
        description="分析当前 git 变更,自动生成 Conventional Commits 格式的 commit message 并提交。"
        "当用户要求提交代码、commit、git commit 时使用。",
        triggers=["/commit", "commit"],
        tools=["Bash"],
        prompt=_COMMIT_PROMPT,
        file_path=__file__,
        source="builtin",
        when_to_use="用户要求提交代码、commit、git commit、提价代码时",
        argument_hint="[commit message 或描述]",
    )
)

# ── pr-create ──────────────────────────────────────────────────

_PR_CREATE_PROMPT = r"""## 创建 Pull Request

分析当前分支的变更,自动生成 PR 标题和描述,创建 GitHub PR。

### 前置检查

1. 检查 gh CLI 是否可用:`gh auth status`
   - 如果不可用,提示用户安装 GitHub CLI 并运行 `gh auth login`
2. 检查当前是否在非 main/master 分支上:`git branch --show-current`
   - 如果在 main/master 上,提示用户先创建功能分支

### 步骤

1. **获取变更信息**
   - `git branch --show-current` — 当前分支名
   - `git diff main...HEAD --stat` — 变更统计
   - `git diff main...HEAD` — 完整 diff
   - `git log main...HEAD --oneline` — 提交历史
   - 如果 main 不存在,尝试 master、develop

2. **生成 PR 内容**
   - **标题**:遵循 Conventional Commits 格式,如 `feat(auth): 添加 OAuth2 登录支持`
   - **描述**包含以下部分:
     - ## 变更概述 — 简要说明做了什么
     - ## 变更动机 — 为什么需要这个变更
     - ## 影响范围 — 涉及哪些模块
     - ## 测试说明 — 如何验证变更

3. **向用户确认**
   展示生成的标题和描述,询问:
   - 确认创建
   - 修改标题/描述
   - 取消

4. **创建 PR**
   - `gh pr create --title "<title>" --body "<body>"`
   - 如果用户指定了参数 `$ARGUMENTS`,将其作为 PR 的补充说明融入 body
   - 输出 PR 链接

### 注意

- 如果当前分支已有 PR,提示用户并显示 PR 链接
- 如果有未提交的变更,提醒用户先提交
- 标题不超过 72 字符"""


register_builtin(
    SkillDef(
        name="pr-create",
        description="分析当前分支的 git 变更,自动生成 PR 标题和描述,通过 gh CLI 创建 GitHub PR。"
        "当用户要求创建 PR、提 PR、pull request 时使用。",
        triggers=["/pr-create", "/pr", "pr-create"],
        tools=["Bash"],
        prompt=_PR_CREATE_PROMPT,
        file_path=__file__,
        source="builtin",
        when_to_use="用户要求创建 PR、提 PR、pull request、merge request 时",
        argument_hint="[补充说明]",
    )
)
