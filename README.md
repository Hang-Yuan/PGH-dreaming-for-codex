# Predictive Generative Harness for Codex · dreaming

PGH **dreaming for Codex**（6.1）是一套给 Codex CLI 使用的个人长期协作骨架。它把"用户档案 / AI persona / 长期记忆 / 周工作台 / 项目区 / 记忆代谢 / hooks / skills"做成一套可部署的 Markdown 文件结构，让 Codex 在每次会话启动时自动加载、按规则写入、跨会话保持上下文。

**dreaming 这一代的核心变化**：记忆代谢从"每条消息实时判断写入"翻转为**白天零写入、夜间集中代谢**——白天对话只把工作结论固化进工作库，全部校准信号以原文留在会话转写里；夜间由 `merak-dream` 流程无人值守回放当天转写，统一做提取、升格、衰减。实时写入层（旧版的 `memory_signal` hook + `episodic_inbox` 收件箱）整层退役。

**与 Codex 默认行为的差别**：默认情况下 Codex 是无状态的；PGH 把长期上下文外置成结构化文件，让 Codex 启动时沿加载链读取，逐消息通过 hook 获得提醒，再由 skill 把值得保留的信息分类写回本地知识库。

> 当前发布：v6.1.0 · semantic 退注入 + 白天零写入夜间代谢 + 记忆系统结构全景。`CHANGELOG.md` 记录模板发布，README 展示当前可部署入口。
> dreaming 重点：白天零写入 / 零注入、夜间 `merak-dream` 无人值守代谢、L0 = 会话转写、episodic 四态（活动 / 复审 / 候补 / 休眠）、semantic 退注入降为 dream 中间工作区、记忆规则单一权威源、storage-agent 文件 IO、06:10 定时无头代谢。
> 本仓库是 PGH **dreaming 线**的 Codex 端起点，与 Claude 端 [PGH-dreaming](https://github.com/Hang-Yuan/PGH-dreaming) 平行；两端共享同一套记忆代谢理念，各自适配自己的 runtime。
> PGH 主文档见 [docs/Predictive Generative Harness System v6.0.md](./docs/Predictive%20Generative%20Harness%20System%20v6.0.md)。

---

## 架构

PGH dreaming 的文件分三类，**部署 / 阅读 / 写入** 角色不同：

### 一、骨架文件（部署时复制到本地，AI 启动时读取）

这部分是 PGH 的 **运行时骨架**，每个 Codex 会话启动都会读取它们：

| 路径 | 角色 | 读 / 写 |
|---|---|---|
| `.codex/AGENTS.md` | 全局指令主控（启动序列 / 系统原则 / 行为规则 / 记忆系统 / 故障恢复）| AI 启动必读，不写 |
| `.codex/config.toml` | hooks 配置 | AI 启动读取，不写 |
| `.codex/hooks/*.py` | 逐消息 hook（时间感知 / 思考协议 / 节点收尾 / 会话结束）| AI 触发，不写 |
| `.codex/skills/merak-*/SKILL.md` | 工作流（merak-dream / merak-daily-review / merak-weekly-review / merak-close-node / merak-write-progress / merak-create-project / merak-new-file / merak-week-sync / merak-due-diligence / merak-manage-research-reference）| AI 按情境调用，不写 |
| `.codex/agents/*.toml` | sub-agent 定义（通用检索 / 文件 IO 等）| AI 调用，不写 |
| `assistant/00 专注区/00.专注区_agent.md` | 专注区规则 agent | AI 按需读，不写 |
| `assistant/01 项目区/00.项目区_agent.md` | 项目区规则 agent | AI 按需读，不写 |
| `assistant/MEMORY/00.记忆区_agent.md` | 记忆系统规则 agent（全部判准 / 阈值 / 状态机 / 授权的单一权威源）| AI 按需读，不写 |

### 二、用户内容文件（部署时为空模板，AI 在初始化访谈和后续会话中动态写入）

这部分是 **用户专属内容**，PGH 部署时只提供空骨架；首次初始化访谈和后续会话中由 AI 动态生成：

| 路径 | 角色 | 何时写入 |
|---|---|---|
| `assistant/USER/USER.md` | 用户身份主档 | §0 阶段 1 基础信息访谈后写入；后续从语义记忆毕业补充认知模式 / 协作注意事项 |
| `assistant/USER/[子文件].md` | USER 子文件（个人经历 / 心理画像 / 信念体系 / 兴趣起源 等）| §0 阶段 3 AI 拆解访谈结果后**动态决定建什么**（不预设数量 / 名字） |
| `assistant/SOUL/persona/persona_SOUL.md` | AI persona | §0 阶段 1.2 写入身份 / 风格；行为模式由 dream 从语义记忆毕业 |
| `assistant/长期记忆.md` | 当前处境 / 时间轴 / 详细周录 | §0 阶段 1.3 写入当前处境；后续 daily-review / weekly-review 维护 |
| `assistant/00 专注区/_本周.md` | 当前周工作台（任务 / 进展 / 产出）| daily-review / weekly-review / week-sync 维护 |
| `assistant/01 项目区/[项目]/` | 用户项目目录 | §0 阶段 1.3 + 后续会话调 `merak-create-project` skill 建 |
| `assistant/MEMORY/episodic_memory.md` | 1-3 星情景候选（活动 / 复审 / 候补 / 休眠四态），不启动注入 | dream 夜间代谢写入；close-node ≥2 事件可日间直升 |
| `assistant/MEMORY/semantic_memory.md` | 4-6 星语义 schema 的 dream 中间工作区（不启动注入）| dream 升格写入 |
| `assistant/MEMORY/last_dream.md` | 最近一次 dream 的逻辑日期探针（一行）| dream 完成时覆盖；week-sync 启动核对 |
| `assistant/MEMORY/MEMORY_LOG.md` | 记忆代谢流水 | 升格 / 升星 / 衰减 / 归档时由 dream（经 storage-agent）写入 |
| `assistant/ITERATION_LOG.md` | 架构 / skill / 协议变更日志 | 变更发生时经 storage-agent 写入 |

### 三、参考文档（部署时复制，用户和 AI 都按需阅读）

| 路径 | 角色 |
|---|---|
| `README.md` | 本文件 |
| `CHANGELOG.md` | 模板版本迭代记录 |
| `docs/Predictive Generative Harness System v6.0.md` | PGH 设计主文档（理念 / 理论 / 工程实现，脱敏版）|

---

## 部署

把以下指令发给 Codex：

```text
这是 PGH dreaming for Codex（release v6.1.0）链接 https://github.com/Hang-Yuan/PGH-dreaming-for-codex ，帮我装到本机。如果我已经有旧 PGH 系统，把我已有的内容迁移过来。
```

AI 会按 `.codex/AGENTS.md §-1 部署 / 迁移协议` 自己完成：

1. 拉取或下载当前 PGH 仓库（release v6.1.0）到临时目录
2. 复制骨架文件到 `<CODEX_HOME>`（通常是 `~/.codex`），复制用户内容空模板到指定的 `<ASSISTANT_ROOT>/`
3. 替换占位符（assistant 路径 / Codex 配置目录路径 / Python 命令等）
4. 检测是否有旧 PGH 系统：有则备份并迁移已有用户内容到 dreaming 当前结构；无则保留 §0 启动首次初始化访谈
5. 完成后删除 §-1 节，进入 §0 初始化或正常启动序列

PGH 不管 Codex 本身的安装——上游官方安装完后再把上面的指令发给 Codex。

---

## 首次初始化

部署完成后，Codex 启动会读到 `.codex/AGENTS.md` 顶部的 `§0 初始化引导`。

初始化分三段，AI 主动引导，不需要你手填模板：

- **阶段 1 · 基础信息（5 分钟，必做）**
  - 用户档案：称呼 / 语言 / 时区 / 主要用途 / 隐私边界
  - AI 助手期望：AI 名字 / 风格期望
  - 当下处境 + 项目导入：1-3 个月重点 / 当下项目 / 本周主线 / 近期截止

- **阶段 2 · 故事访谈（30 分钟左右，必做）**
  - AI 主动引导你讲受教育与起点 / 工作与项目轨迹 / 自我认知 / 价值与信念 / 行为模式
  - 你可以让 AI 直接读你的工作文件夹路径或电脑上的相关内容
  - AI 边听边追问，鼓励你发散

- **阶段 3 · AI 拆解 + 动态建文件 + 用户预览**
  - AI 拆解访谈内容 → 动态决定建几个 USER 子文件、叫什么名（不预设数量 / 名字）
  - 给你写入预览，你确认后写入

完成后 AI 删除 `§0` 整节，下次启动进入正常启动序列。

---

## Hook

| Hook | 触发 | 作用 |
|---|---|---|
| `session_start.py` | compact 后 | 重新注入身份层（persona SOUL + USER）|
| `thinking_protocol.py` | 每条消息 | 注入四步思考协议 |
| `session_context_check.py` | 每条消息 | 提示节点收尾和项目加载 |
| `session_end.py` | 告别语 | 触发 daily-review（含排定当晚 dream）|

> dreaming 不再有逐消息的记忆信号 hook（旧版 `memory_signal.py`）——记忆判断从实时改为夜间回放，白天的 hook 只管思考协议和节点提醒。时间感知由 AGENTS.md §R 承担。

---

## 记忆架构

PGH dreaming 使用"一个只读源 + 两个记忆池"的三层骨架，按白天编码、夜间巩固组织：

- `assistant/MEMORY/` 之外的 **L0 = 会话转写**：Codex 运行时自动落盘的 jsonl（`<CODEX_HOME>/sessions/` + `archived_sessions/`），当日全部对话的完整记录——零维护、零写入成本，是 dream 夜间回放的唯一输入。
- `episodic_memory.md`（**L1**）：1-3 星情景级候选 schema，活动 / 复审 / 候补 / 休眠四态，**不启动注入**。
- `semantic_memory.md`（**L2**）：4-6 星稳定语义 schema 的 dream 中间工作区，**不启动注入**——白天不进运行时上下文，仅夜间被 dream 作为代谢对照基线读取。

**昼夜节律**：

- **白天**：零记忆写入。工作结论经 close-node 固化进工作库（项目主文档 / progress / `_本周`）；校准信号以原文留在 L0 转写里。
- **夜间（dream）**：可由 daily-review 道别时排定，或由 `<CODEX_HOME>/automations/` 的 06:10 定时任务在全新无头进程里自动跑——无人值守回放前一闭合逻辑日的全量转写，升星、≥2 独立事件升格、单事件入候补、项目语境快轨升 semantic、全部操作写 MEMORY_LOG 留账。
- **周日**：日级之上加周级载荷——升格候选裁决、横向统合、衰减执行、毕业候选生成、周归档。

`MEMORY_LOG.md` 只记录记忆系统代谢；项目结论写项目主文档；当前处境写 `长期记忆.md`。

毕业路径：6 星候选 + 跨周稳定 + 用户 C 级 verdict → `USER/` / `SOUL/persona/persona_SOUL.md` / `<CODEX_HOME>/skills/`。

---

## 自定义

PGH dreaming 优先让 AI 通过初始化和后续会话动态维护文件。需要手动改时：

- 改 `assistant/` 中的 Markdown，让 Codex 在下次会话核对加载链 / frontmatter / 隐私残留
- 新增 sub-agent：在 `.codex/agents/` 自行新建 TOML（需要其他领域如学术研究 / 商业项目等由用户自建）
- 调整记忆阈值：改 `assistant/MEMORY/00.记忆区_agent.md`
- 调整 hook：改 `.codex/hooks/*.py`
- 新增 skill：在 `.codex/skills/` 新建目录 + `SKILL.md`

---

## 设计原则

- **加载链导航，不靠模型硬记忆**：每个文件声明上游 / 下游 / 同级联动
- **单一权威源**：每条信息只在一个地方定义，其他地方只放摘要和指针
- **默认遗忘**：低置信信号自然消失，高价值信号复现后才上行
- **白天零写入、零注入、夜间集中代谢**：记忆判断需要完整上下文，集中到夜间回放比逐条实时判更准、更省
- **身份层需确认**：USER / SOUL / skill 的稳定改动必须经过明确授权
- **运行时分流**：PGH Core 不绑定具体 CLI；`.codex/` 只负责 Codex 接入

---

## 许可

MIT。
