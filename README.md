# Codex 版预测生成式支架系统（PGH）· 梦境版

PGH 梦境版（6.2）是供 **Codex** 使用的个人长期协作与记忆骨架。它把工作空间、用户档案、AI 人格、长期工作记忆、私有记忆池、每日代谢、钩子与技能组织成可部署的 Markdown 文件系统。

**当前发布：v6.2.3。** 白天保留完整 L0 会话转写，次晨由 Codex 原生自动化任务调用每日做梦（`daily-dream`）。目标逻辑日为周日时，日链条件转调周级做梦（`weekly-dream`）；季度点只转季度归档检测（`quarterly-archive detect`）。整套系统只有一条每日原生自动化任务。

架构入口：

- [架构说明书](./workspace/02%20Meta%20Zone/Architecture/README.md)
- [排程访谈与原生自动化任务契约](./docs/schedule_interview.md)
- [PGH 设计主文档](./docs/Predictive%20Generative%20Harness%20System%20v6.0.md)
- [核心层与 Codex 适配层分流](./docs/核心分流.md)

---

## 运行边界

本仓发布的记忆系统只供 Codex 运行：

- 会话入口：Codex。
- L0：`<CODEX_HOME>/sessions/` 与 `archived_sessions/`。
- 自动入口：Codex 原生自动化任务。
- 日链提示：`使用 $daily-dream 处理最近一个已经闭合的逻辑日；严格执行事务闸，并报告提交收据。`
- 禁止入口：`launchd`、`systemd`、Windows 任务计划程序、无界面命令行包装器、其他 AI 软件。

机器休眠、关机或应用不可用造成缺勤时，次日首个真人会话的 `week-sync` 检出断档并按上限补跑。

---

## 文件结构

### Codex 运行时

| 路径 | 角色 |
|---|---|
| `.codex/AGENTS.md` | Codex 主控：启动序列、行为规则、记忆路由与初始化协议 |
| `.codex/config.toml` | Codex 运行配置 |
| `.codex/hooks/` | 时间感知、思考协议与会话身份注入 |
| `.codex/skills/` | 每日做梦、周级做梦、季度归档与工作固化技能 |
| `.codex/agents/` | 检索与长文件读写代理 |

### 工作空间

公开骨架与本机现役工作空间使用同一套坐标；英文目录与机器文件名保持一致，面向人的说明使用中文。

| 路径 | 角色 |
|---|---|
| `workspace/00 Focus Zone/` | 当前周工作台 `_current.md` 与周归档 |
| `workspace/01 Projects Zone/` | 项目本体、结论、材料与推进记录 |
| `workspace/02 Meta Zone/` | 架构说明、区域规则与 `ITERATION_LOG.md` |
| `workspace/03 Communication Zone/` | 多智能体部署的通信总线与公告板 |
| `workspace/04 Learning Zone/` | 学习材料与消化产物 |
| `workspace/05 Reading Zone/` | 阅读材料与笔记 |
| `workspace/06 Writing Zone/` | 写作项目与成稿 |
| `workspace/Long_Term_Memory/` | `status.md`、`weekly.md` 与待裁事项 |
| `workspace/USER/` | 用户身份主档及按需子文件 |
| `workspace/SOUL/` | AI 人格模板 |
| `workspace/MEMORY/` | 情景记忆、语义记忆、代谢日志与事务探针 |

每个现役工作区都由 `00.{区域}_canon.md` 管辖。记忆判准的权威源是 `workspace/MEMORY/00.memory_agent.md`。

---

## 部署

在 Codex 中发送：

```text
这是 Codex 版 PGH 梦境系统（release v6.2.3）：https://github.com/Hang-Yuan/PGH-dreaming-for-codex 。请安装到本机；如果已有旧 PGH 内容，先备份并迁移。自动做梦只接 Codex 原生自动化任务。
```

部署流程：

1. 拉取当前仓库到临时目录。
2. 把 `.codex/` 部署到当前 Codex 运行时目录。
3. 把 `workspace/` 部署到用户确认的 `<WORKSPACE_ROOT>/`。
4. 替换工作空间、运行时、Python 与身份占位符。
5. 检测旧内容；先备份，再迁移 USER、SOUL、项目、工作台、长期工作记忆与两池。
6. 完成初始化访谈。
7. 通过 Codex 原生自动化任务管理能力创建或更新唯一一条每日 `cron` 任务，使其显示在 Codex 应用的“定时任务”页。
8. 回读自动化任务，确认状态、时刻、项目、模型、执行环境与提示词。

旧 `codex-code-harness` 只供迁移取证，禁止新装：
https://github.com/Hang-Yuan/codex-code-harness

---

## 首次初始化与排程

初始化访谈覆盖：

1. 用户档案、语言、IANA 时区、主要用途与隐私边界。
2. AI 名字、协作风格、当前处境、项目与本周主线。
3. 作息（通常几点睡、几点起）与 Codex 可用性，用来确定逻辑日界线和每日自动化任务时刻。

排程合同：

- 类型：Codex 原生独立项目自动化任务。
- 数量：恰好一条。
- 名称：每日做梦（`daily-dream`）。
- 时刻：日界线后 30 分钟。
- 提示：`使用 $daily-dream 处理最近一个已经闭合的逻辑日；严格执行事务闸，并报告提交收据。`
- 项目：`<WORKSPACE_ROOT>` 所在项目。
- 执行环境：`local`。
- 状态：用户确认后设为 `ACTIVE`。
- 周段与季度段：无独立自动化任务，由日链按目标逻辑日条件转调。

任务定义保存成功只证明配置已落盘。首跑验收还要同时满足：

- Codex 自动化任务历史存在计划触发终态记录；
- 对应逻辑日 `dream_receipts/YYYY-MM-DD.json` 为 `COMMITTED`；
- `last_dream.md` 已推进到同一天；
- 覆盖闸、决策闸与提交闸全部通过。

手工立即运行可以验证工作流；计划触发是否正常仍以 Codex 自动化任务历史为准。

---

## 记忆节律

- **白天**：不连续写记忆池。工作结论经 `close-node` 固化；其余信号完整留在 L0 转写。
- **次晨**：唯一原生自动化任务调用 `daily-dream`。A 段固化工作，B 段代谢两池，事务完成后写收据并推进探针。
- **周日目标日**：条件转调 `weekly-dream`。
- **季度点**：条件转调 `quarterly-archive detect`；`execute` 仍需用户当前 C 级授权。
- **断档**：`week-sync` 在次日首个真人会话按最早日期优先补跑，最多三个有效工作日。

道别不触发固化。每日原生自动化任务承担正常链，启动同步承担缺勤恢复。

---

## 自定义与安全

- 调整记忆阈值：编辑 `workspace/MEMORY/00.memory_agent.md`。
- 调整作息：同步修改 `AGENTS.md §时间感知` 与 `00.memory_agent.md §逻辑日期`，再更新同一条 Codex 自动化任务。
- 调整任务：只通过 Codex 自动化任务管理能力操作；不直接编辑自动化任务的 TOML 或状态数据库。
- 不创建第二条周任务或季度任务。
- 不向其他软件开放 `<WORKSPACE_ROOT>`、L0、记忆池或做梦收据。

---

## 许可

MIT。双语许可文本见 `LICENSE`；发生歧义时以英文原文为准。
