"""内置 Skill: 技能锻造"""

from uniclaw.tools.skill.loader import SkillDef, register_builtin
from uniclaw.context import APP_NAME

_SKILL_FORGE_PROMPT = f"""## 技能锻造

创建新的 Skill 或优化已有的自定义 Skill。

### 重要规则

⚠️ **只操作自定义 Skill**:本技能只允许创建新 Skill 和修改通过本技能创建的 Skill。

**禁止修改的 Skill**:
- `builtin` 来源的 Skill(如 code-review、commit、pr-create、memory-organize 等内置技能)
- 用户手动安装的 Skill(位于 `~/.claude/skills/`、`~/.codex/skills/`、`~/.agents/skills/` 等目录)
- 项目自带的 Skill(位于项目根目录的 `skills/`、`.claude/skills/` 等目录)

**允许操作的 Skill**:
- 位于 `.{APP_NAME}/skills/` 目录下(相对于当前工作目录),且由本技能创建的 Skill
- 判断方法:读取 Skill 文件,检查是否包含 `source: skill-forge` 标记

---

### 任务概述

根据用户参数 `$ARGUMENTS` 决定执行哪些任务。如果参数为空或包含"all",执行全部任务。

可选任务:
1. **创建 Skill** — 将常见模式总结为可复用技能
2. **优化 Skill** — 根据使用反馈改进已有的自定义 Skill

**参数示例**:
- `all` 或空: 执行所有任务
- `创建`: 只创建新 Skill
- `优化`: 只优化自定义 Skill
- `创建 优化`: 创建 + 优化

---

### 任务 1: 创建 Skill

**目标**: 从记忆和会话中识别可复用的模式,生成新的 Skill。

**重要**: 创建前必须检查是否已存在相似的 Skill,避免重复创建。如果已存在,应该优化而非新建。

**创建流程**:

1. **识别模式**
   分析记忆和会话,寻找:
   - 经常重复的操作流程
   - 固定的命令序列
   - 可以自动化的任务

2. **检查已有 Skill**
   使用 `Glob` 查找 `.{APP_NAME}/skills/*/skill.md`,使用 `Read` 读取内容,判断:
   - 是否已存在功能相似的 Skill?
   - 已有 Skill 是否需要改进?

   **处理策略**:
   a. **如果已存在相似 Skill 且需要改进** → 跳过创建,转为优化任务
   b. **如果已存在相似 Skill 且已完善** → 跳过,不做任何操作
   c. **如果不存在相似 Skill** → 继续创建新 Skill

3. **评估生成价值**
   对每个模式,评估:
   - 使用频率(是否经常需要?)
   - 复杂度(是否值得封装?)
   - 通用性(是否适用于多种场景?)

4. **捕获意图**
   在创建 Skill 前,确认:
   - 这个 Skill 应该让 AI 做什么?
   - 什么时候应该触发?(用户说什么话/什么场景)
   - 期望的输出格式是什么?
   - 是否需要测试用例来验证?

5. **生成 Skill 内容**
   对于有价值的模式,生成 Skill:

   a. **Skill 元数据**
   - name: 简短描述性名称
   - description: 何时使用此 Skill
   - triggers: 触发词列表(命令和自然语言)
   - tools: 需要的工具列表
   - source: "skill-forge"(必须添加,用于标识来源)

   b. **Skill Prompt**
   - 清晰的任务描述
   - 详细的执行步骤
   - 输出格式要求
   - 注意事项

4. **保存 Skill 文件**
   - 使用 `Write` 工具保存到 `.{APP_NAME}/skills/` 目录
   - 文件名格式: `.{APP_NAME}/skills/<skill-name>/skill.md`
   - 使用标准的 Skill Markdown 格式
   - **必须在 frontmatter 中添加 `source: skill-forge`**

**Skill 文件模板**:
```markdown
---
name: <skill-name>
description: <描述做什么 AND 何时使用,稍微积极主动一些>
triggers:
  - /<command>
  - <自然语言触发词>
tools:
  - Bash
  - Read
  - ...
when_to_use: <详细的使用场景描述>
argument_hint: [<参数说明>]
source: skill-forge
---

## <Skill 标题>

<任务描述>

### 步骤

1. ...
2. ...

### 输出格式

```
...
```

### 注意事项

- ...
```

**Skill 结构说明**:
- **name**: Skill 标识符,简短且唯一
- **description**: 主要触发机制,包含做什么 AND 何时使用
  - 写法要稍微"积极主动",避免触发不足
  - 示例: "创建数据图表。当用户提到数据可视化、图表、报表、dashboard、柱状图、折线图时使用"
- **triggers**: 触发词列表,包括命令和自然语言
- **tools**: 需要的工具列表
- **when_to_use**: 详细的使用场景描述
- **argument_hint**: 参数提示
- **source**: 必须是 "skill-forge"

**输出格式**:
```
## 🛠️ Skill 创建报告

### 识别的模式

1. [模式名称]
   - 频率: 高/中/低
   - 复杂度: 高/中/低
   - 通用性: 高/中/低
   - 决策: 创建新 Skill / 转为优化 / 跳过

### 创建的 Skill

#### <skill-name>
- 文件: .{APP_NAME}/skills/<skill-name>/skill.md
- 触发词: /<command>, <自然语言>
- 功能: ...
- 使用场景: ...

### 跳过的模式(已存在相似 Skill)

1. [模式名称]
   - 已有 Skill: <skill-name>
   - 原因: 已存在相似功能 / Skill 已完善
   - 建议: 转为优化任务 / 无需操作

### 创建统计
- 识别模式: N 个
- 创建 Skill: N 个
- 转为优化: N 个
- 跳过: N 个
```

---

### 任务 2: 优化 Skill

**目标**: 根据最近会话中的使用反馈,持续改进已有的自定义 Skill。

**重要**: 只优化 `source: skill-forge` 的 Skill,禁止修改其他来源的 Skill。

**优化流程**:

1. **加载自定义 Skill**
   - 使用 `Glob` 工具查找 `.{APP_NAME}/skills/*/skill.md` 文件
   - 使用 `Read` 工具读取每个 Skill 文件的内容
   - **检查 `source` 字段,只处理 `source: skill-forge` 的 Skill**
   - 跳过其他来源的 Skill(builtin、user、project 等)

2. **分析使用反馈**
   从最近会话中寻找 Skill 使用的痕迹:

   a. **Skill 调用记录**
   - 搜索会话中包含 Skill 名称或触发词的消息
   - 识别用户使用了哪些 Skill
   - 记录 Skill 被调用的次数和频率

   b. **执行问题**
   - Skill 执行是否失败?
   - 用户是否手动修正了 Skill 的输出?
   - 用户是否放弃了 Skill 并手动完成任务?
   - 用户是否抱怨 Skill 的效果?

   c. **改进建议**
   - 用户是否提出了改进意见?
   - 用户是否期望 Skill 能做更多事情?
   - Skill 的输出是否符合用户预期?

3. **识别优化机会**
   分析收集到的反馈,识别:

   a. **提示词问题**
   - 描述不清晰,导致 AI 理解偏差
   - 步骤不完整,遗漏关键环节
   - 输出格式不符合用户预期
   - 缺少必要的约束或注意事项

   b. **功能缺失**
   - 用户期望的功能未包含
   - 可以扩展的场景未覆盖
   - 相关的工具未配置

   c. **触发词问题**
   - 用户使用的自然语言未包含在触发词中
   - 触发词过于宽泛或过于狭窄
   - 触发词与实际功能不匹配

4. **执行优化**
   对于识别出的问题,采取相应的优化措施:

   a. **优化提示词**
   - 使用 `Read` 工具读取现有 Skill 文件
   - 分析问题根因
   - 修改提示词内容
   - 使用 `Write` 工具保存更新后的 Skill 文件
   - **保留原有名称**,不做修改
   - 记录修改内容和原因

   b. **扩展功能**
   - 在提示词中添加新的场景描述
   - 补充缺失的步骤或约束
   - 更新输出格式要求
   - 添加新的工具到 tools 列表

   c. **优化触发词**
   - 添加用户常用的自然语言触发词
   - 移除不常用或误导性的触发词
   - 确保触发词与功能匹配

   d. **优化描述(description)**
   - description 是触发机制的关键
   - 包含 Skill 做什么 AND 何时使用
   - 描述要稍微"积极主动"一些,避免触发不足
   - 示例: 不要写"创建图表",而是写"创建图表。当用户提到数据可视化、图表、报表、dashboard 时使用"

5. **优化原则**
   - **保留原名**: 更新已有 Skill 时,保留原有的 name 字段
   - **从反馈中泛化**: 不要只针对特定例子修改,要理解背后的原因
   - **保持精简**: 移除不起作用的内容,让 prompt 保持简洁
   - **解释原因**: 用"为什么"代替"必须",让 AI 理解意图
   - **查找重复工作**: 如果多个测试用例都写了类似的脚本,考虑打包到 Skill 中

6. **验证优化效果**
   - 对于重大修改,建议用户测试优化后的 Skill
   - 记录优化历史,便于追踪和回滚
   - 保留 `source: skill-forge` 标记

**优化策略**:

a. **保守优化**
   - 对于不确定的优化,保留原有内容
   - 使用注释或版本标记记录修改
   - 建议用户验证后再正式采用

b. **渐进优化**
   - 优先优化问题最严重的 Skill
   - 每次只做少量修改,避免引入新问题
   - 逐步迭代,持续改进

c. **用户确认**
   - 对于重大修改,向用户展示修改内容
   - 获取用户确认后再保存
   - 保留回滚能力

**输出格式**:
```
## 🔧 Skill 优化报告

### 分析的 Skill

1. [Skill 名称]
   - 文件: .{APP_NAME}/skills/<skill-name>/skill.md
   - 来源: skill-forge ✓ / 其他(跳过) ✗
   - 调用次数: N 次
   - 问题数量: N 个

### 跳过的 Skill(非自定义)

- [Skill 名称] - 来源: builtin/user/project

### 发现的问题

#### <skill-name>
1. [问题类型] 问题描述
   - 来源: [会话标题]
   - 严重程度: 高/中/低
   - 优化方案: ...

### 执行的优化

#### <skill-name>
- 修改内容: ...
- 修改原因: ...
- 影响范围: ...

### 优化统计
- 分析 Skill: N 个
- 跳过(非自定义): N 个
- 发现问题: N 个
- 执行优化: N 个

### 优化建议
- [建议用户测试优化后的 Skill]
- [建议关注的改进点]
```

**注意事项**:

- **保守原则**: 不确定的优化宁可不做
- **只改自定义**: 严格遵守只修改 `source: skill-forge` 的规则
- **用户确认**: 涉及功能变更的优化需要用户确认
- **渐进改进**: 每次只做少量修改,避免引入新问题
- **记录历史**: 记录每次优化的内容和原因

---

### 综合执行策略

当执行全部任务时,按以下顺序执行:

1. **先创建 Skill** — 基于记忆和会话中的模式创建新 Skill
   - 创建前检查是否已存在相似 Skill
   - 如果已存在且需要改进,转为优化任务
2. **再优化 Skill** — 根据使用反馈改进已有的自定义 Skill
   - 包括从创建任务转过来的需要优化的 Skill

这样可以避免:
- 重复创建已有的 Skill
- 基于过时内容创建 Skill
- 遗漏有价值的信息

### 通用注意事项

- **避免重复**: 创建前必须检查是否已存在相似 Skill,优先优化而非新建
- **source 标记**: 创建的 Skill 必须包含 `source: skill-forge`
- **只操作自定义**: 严格遵守只操作 `source: skill-forge` 的规则
- **保守原则**: 不确定的操作宁可不做
- **保持简洁**: Skill 内容应该精炼,避免冗长
- **用户优先**: 用户明确要求的操作优先执行"""


def register():
    """注册 skill-forge 技能"""
    register_builtin(
        SkillDef(
            name="skill-forge",
            description="技能锻造:创建新 Skill 和优化已有的自定义 Skill。只操作由本技能创建的 Skill,不修改内置或安装的 Skill。"
            "当用户要求创建 skill、生成 skill、优化 skill、改进 skill 时使用。",
            triggers=["/skill-forge", "/forge-skill", "skill-forge", "技能锻造"],
            tools=["Bash", "Read", "Write", "Glob", "memory_list", "memory_search", "session_list", "session_detail"],
            prompt=_SKILL_FORGE_PROMPT,
            file_path=__file__,
            source="builtin",
            when_to_use="用户要求创建 skill、生成 skill、优化 skill、改进 skill、技能锻造时",
            argument_hint="[all/创建/优化]",
        )
    )
