---
name: create-project
description: 新建项目流程。建项目目录 + `_overview.md` + 同步 portfolio。AGENTS.md §项目工作加载判定为新建项目时调用。
---

# create-project

新建项目的标准建设流程。**职责仅限"建项目入口这件事"**——建好 `_overview.md` 与 portfolio 登记后交棒。推进容器（`_progress/` + 管家文件 + 节点）由 `write-progress` skill 全权负责。

## 加载链

**上游**：`AGENTS.md §项目工作加载` — 判定为新建项目时调用。

**下游**：
- `01 Projects/[新项目]/_overview.md`（创建）
- `01 Projects/00.projects_agent.md §Portfolio`（追加新项目一行）

**同级联动**：
- `new-file` skill — 新建 `_overview.md` 时强制补加载链
- `write-progress` skill — 用户首次需要推进记录时调用，由它建 `_progress/` 容器与管家文件
- `_reference/` — 首次需要文献时直接建（建里面的 `.md` 仍先过 `new-file`）

---

## 步骤

### 1. 信息收集

向用户确认以下要素（一次性问完，允许部分留空）：

- **项目名称**（目录名 + `_overview.md` 标题）——优先英文；纯业务中文场景可保留中文
- **项目目标**（一两句话）
- **关键人物**（至少含[用户称呼]自己；若有合作者列出）
- **当前阶段**（探索期 / 起步期 / 已有积累迁入 等）
- **项目类型**（理论研究 / 课程教学 / 事务管理 / 商业项目 / 系统工程 / 其他）——决定推进管家命名 / 是否启用文献管理
- **是否需要跨项目引用**（默认显式隔离；若有则记录）

### 2. 建项目目录与结构规划

建项目根目录：

```
01 Projects/[项目名]/
```

**本步骤只建根目录 + 步骤 3 建 `_overview.md`。其余子目录按需由对应 skill 建立**（简化结构图，便于操作时一眼看出要建什么）：

```
01 Projects/[项目名]/
├── _overview.md       ← 项目入口（必建，步骤 3）
├── [项目主文档].md     ← 项目核心产出（按需）
├── _progress/         ← 推进记录容器（首次需要时由 write-progress skill 建）
├── _reference/        ← 外部素材容器（首次需要时直接建）
└── _archive/          ← 归档容器（首次归档时建）
```

**完整结构规范 + 各部分职能 + 命名约定**见 `01 Projects/00.projects_agent.md §项目内部结构规范`（权威源）。本 skill 不重复。

### 3. 建 `_overview.md`

调用 `new-file` skill 确认加载链字段后，按以下骨架填入：

```markdown
---
title: [项目名]
type: project-overview
status: 活跃
project_type: [理论研究 / 课程 / 事务 / 商业 / 系统工程 / 其他]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# [项目名]

## 加载链（上下游）

**上游：** `01 Projects/00.projects_agent.md` — 任务涉及 [项目名] 时加载。

**管辖文件（下游）：**
- （待项目展开后补充）

**同级联动：**
- （按需补充）

---

## 项目概览

**目标**：[一两句话]

**关键人物**：[列出]

**当前阶段**：[一句话]

---

## 当前状态

**总体逻辑**：[项目内部推进的总线索；起步阶段写"初始化中"]

**进展节点**：
- （起步阶段为空，随推进追加）

**断点 / 下一步**：
- （起步阶段写"待与用户对齐第一个工作目标"）

---

## 项目文件

### 核心文档
- `_overview.md` — 本文件
- （项目主文档命名待定，按需补充）

### 子目录（按需建立）
- `_progress/` — 推进记录容器（首次需要推进记录时由 write-progress skill 建立）
- `_reference/` — 外部素材 / 文献（首次需要文献时直接建）
- `_archive/` — 归档（第一次归档时建）

---

## 管理规则

通用规则见 `01 Projects/00.projects_agent.md`（portfolio / 生命周期 / 跨引用 / 命名 / 骨架通则）。

推进记录写入见 `write-progress` skill。

理论研究 / 系统工程等需要持续推理链的项目，首次进入推进记录时交给 `write-progress` 建 `_progress/`；段间转换标记定义权威源 = write-progress §2.3 追加与扩展（本模板不复制标记清单）。

[若 project_type = 理论研究]

---

## 相关项目

- （若有跨项目互通授权，列出对方项目路径）
```

### 4. 后续 skill 交接

本 skill 完成项目入口建设后，按用户实际需求依次接力：

| 触发 | 调用 skill | 建什么 |
|---|---|---|
| 用户首次需要推进记录（"开始记录推进 / 写一下今天进展"等） | `write-progress` | `_progress/` 容器 + 管家文件 + 首节点 |
| 用户进入第一个实质内容产出（写理论 draft / 课程大纲等） | （直接建主文档，无 skill 介入） | `[项目主文档].md` |
| 首次归档旧版本 | （直接建 `_archive/` 移入文件） | `_archive/` |

本 skill 不预建空目录、不替其他 skill 占位——保持项目入口干净，子容器按需生长。

### 5. 更新项目区 portfolio

向 `01 Projects/00.projects_agent.md §Portfolio 全项目索引` 追加一行：

```
| [项目名] | 活跃 | YYYY-MM-DD | 项目初始化 |
```

S 级静默执行。

### 6. 跨项目互通登记（如适用）

若步骤 1 中确认需要与既有项目互通：

1. 在新项目 `_overview.md §相关项目` 写入对方路径
2. 在对方 `_overview.md §相关项目` 写入本项目路径（**C 级确认**）
3. 向 `00.projects_agent.md §跨项目授权索引` 追加一行

### 7. 反馈

向用户汇报：
- 建好的目录结构与 `_overview.md` 路径
- portfolio 已同步
- 下一步选项：开始推进工作（将调 write-progress） / 直接建项目主文档 / 暂停

---

## 注意

- **建目录前确认重名**：检查 `01 Projects/` 下是否已有同名项目
- **路径用 ASCII 安全字符**：骨架英文，内容可中文
- **创建即记 portfolio**：步骤 5 是 S 级静默执行
- **不写入 `_本周.md`**：新建项目本身不算工作进展
- **步骤 3 后交棒**：项目入口建好 + portfolio 同步即本 skill 终点；后续容器由对应 skill 按需接力（见步骤 4）





