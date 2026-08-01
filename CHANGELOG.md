# CHANGELOG

Predictive Generative Harness for Codex · **dreaming** 线的模板版本迭代记录。

## 版本号规则

- 本仓库是 PGH **dreaming 线**的 Codex 端起点，版本从 `v6.0.0` 起，与 Claude 端 [PGH-dreaming](https://github.com/Hang-Yuan/PGH-dreaming) 平行编号。
- dreaming 与旧 PGH 5.x 模板线分流：两条线互不追溯、互不升级。旧线用户若要迁到 dreaming，按 `§-1` 重新部署。
- 每次发布只记录公开模板结构、入口协议、初始化流程、hook / skill / assistant 骨架变化。

## v6.2.0 · 排程驱动固化 + daily-dream 单链 + skill 更名去前缀 + 架构说明书

与 Claude 端 v6.2.0 对齐。固化触发从「会话内道别」翻转为**操作系统排程**。旧路径依赖「道别 → 排一次性任务 → 会话恰好活到触发时刻」，这条链任一环挂掉就静默丢一天，且只能靠次日人工发现。本版把触发装进 launchd / 任务计划程序 / systemd timer，与会话生死无关。

### 节律与排程

- **新增 `scripts/install_schedule.py`**：部署期问作息（入睡 / 起床 / 夜间留机 / IANA 时区），推出该部署的**日界线**（02:00–06:00 任一整点），把固化排在日界线 + 30 分钟，装进操作系统排程后回查并写收据。长期要调用的脚本同时复制到 `~/.pgh/scripts/<runtime>/`，临时 clone 删掉也不断路。
- **日界线改为部署期变量**：模板里的 `06` 只是默认值，安装时按作息答案改写两处口径行（`AGENTS.md §时间感知` + `MEMORY/00.memory_agent.md §逻辑日期`）。原先 v6.1.0 写死的 `06:10 定时无头代谢`一并作废——早睡早起的部署者用固定值会每天把一段工作归到错误的日子，且全程不报错。
- **`extract_daily_transcripts.py` 自解析窗口**：日界线与 IANA 时区都从排程收据读（顶层字段优先，早期安装的 `acceptance` 嵌套兜底），并把取值来源打到 stderr。`--boundary-hour` / `--timezone` 降级为覆盖用参数，正常流程不传——传死值会整体平移抽取窗口，而 manifest 的日期、计数、路径全都自洽，平移在输出里看不出来。
- **新增 `scripts/verify_first_run.py`**：首跑验收。核排程自己写进 `~/.pgh/natural_runs.<runtime>.jsonl` 的结构化凭据 + 地面证据 + 验收当刻的 job 状态。凭据只在带着安装期写进 job 定义的 proof 时才记 `source=os-scheduler`，手工跑包装器记 `manual-wrapper` 且翻不绿。
- **新增 `scripts/run_scheduled_dream.py`**：排程调用的包装器，含 in-flight 锁与事务边界。
- **`--smoke` 是 `READY` 的前提**：加了它才跑 headless 实跑，且跑在启用 job **之前**——跑不通就回滚正文与排程。不加不会阻止安装，但收据落 `state=INSTALLED_SMOKE_NOT_RUN`，永远到不了 `READY`；「CLI 真能被调起来」无法从静态检查推出，而排程的真跑在夜里没人看着。事后可用 `--smoke-only` 单独补跑。

### skills

- **skill 名去掉 v5 线前缀**：`merak-close-node` → `close-node`，`merak-write-progress` → `write-progress`，`merak-create-project` → `create-project`，`merak-new-file` → `new-file`，`merak-week-sync` → `week-sync`。那个前缀是 v5 线的命名遗留，两端命名从此对齐。**从 v5 / v6.0–v6.1 升上来的部署要同步改现役文件里的旧名**——`scripts/audit_stale_routes.py` 会抓残留。
- **三 skill 合并为 `daily-dream` 单链**：`merak-daily-review` / `merak-weekly-review` 退役进 `.codex/skills/_retired_20260801/`，`merak-dream` 改名 `daily-dream` 并吸收工作固化——phase A 工作固化 → phase B 记忆代谢，目标逻辑日为周日时追加周段。三个独立 skill 各自读一遍转写、各自判一次日期，边界重叠处会重复固化或漏固化；单链把日期解析、真读转写、事务提交收在一处。
- **道别不再触发固化**：`daily-dream` 明确不在「晚安 / 收工 / 今天到这」时调用。当日工作在 L0 转写里过夜，由次晨排程处理。
- `week-sync` 首会话增加断档核查，查出昨夜事务未闭合时提示补跑。

### hooks

- **收敛到三项**：留 `timesense.py` / `thinking_protocol.py` / `session_start.py`；退役 `session_end.py`（按告别语触发固化，机制整体作废）与 `session_context_check.py`（逐消息提醒，与 `AGENTS.md §行为路由` 规则重复），移入 `hooks/_retired_20260801/`，部署时不复制。`config.toml` 同步摘掉两处注册——只删脚本不摘注册会让运行时每轮报一次找不到命令。

### 文档

- **新增 `docs/architecture/`**：七份架构说明书（`README` / `01_topology` / `02_agents` / `03_memory_flow` / `04_work_memory_flow` / `05_runtime` / `06_cadence_and_gates`）。
- **新增 `docs/schedule_interview.md`**：作息访谈的规格与推算规则单一权威源——四问的问法、日界线推算、夜间留机的平台差异（锁屏 / 关显示器可以，**合盖不行**：macOS 合盖默认睡眠，接电源也不解除）、各状态的复位动作。`AGENTS.md §0` 只留问法与动作。
- `assistant/MEMORY/00.记忆区_agent.md` 更名 `00.memory_agent.md`，与 Claude 端同名。

### 机械闸

- **新增 `scripts/audit_stale_routes.py`**：现役权威树的旧路由机械闸。指向已退役 skill（含 `merak-week-sync` 这类 v5 旧名）、写死固化时刻、写死逻辑日窗口、把告别当固化触发——四类都不会报错，只会让新部署跑在一个已不存在的架构上。判据可 grep，历史区（`_retired_*/` / CHANGELOG / ITERATION_LOG）不在扫描范围。
- 随仓发布四套回归（`test_install_schedule` / `test_verify_first_run` / `test_stale_routes` / `test_release_boundary`），部署后可自查。

## v6.1.0 · semantic 退注入 + 全量活跃会话复盘 + 记忆系统结构

dreaming 起点之后第一次 feature 级更新，与 Claude 端 v6.1.0 对齐：记忆架构（semantic 退出启动注入）、daily-review / dream 升级为当日全量活跃会话复盘、记忆区 agent 补全结构性全景节、Focus Zone 周工作台机制。

### 记忆架构变化

- **semantic 退出启动注入**：`semantic_memory.md` 从"启动注入层"降级为 **dream 中间工作区**——白天不进运行时上下文，仅夜间被 dream 作为代谢对照基线读取。白天运行时的共同世界模型底座收缩为 **USER + SOUL + AGENTS.md §R 三件套身份层**。
- **升格门重构**：跨情景 episodic → semantic 的唯一升格门为**周日横向统合**；`★★★ 再命中` 定义为**怀疑触发器**（标 `待统合簇` 留周日判去向），避免母结构的多个表面各自单条升格、碎片化 semantic。
- **代谢对照基线显式化**：两轴判定本质是差分运算，对照基线 = 现有 schema 全集三层（episodic / semantic / 身份层）。

### skills

- **daily-review / dream 升级为当日全量活跃会话复盘**：`merak-daily-review` 从"当前对话"扩展到"当日全部活跃会话转写"——先跑 `extract_daily_transcripts.py` 拉全量会话包，再逐类固化工作，一天多窗口开工也只需一次道别兜底。`merak-dream` 强制真读转写全文，禁用 compact 上下文 / 摘要顶替 L0。
- **06:10 定时无头代谢**：`<CODEX_HOME>/automations/` 每日 06:10 拉全新无头进程跑 daily-review→(周日)weekly-review→dream，处理前一闭合逻辑日，探针幂等 + 强制真读——记忆代谢不再依赖人在场。

### 文档

- `assistant/MEMORY/00.记忆区_agent.md`：新增 `## 记忆系统结构` 全景节（schema 定义 / 信息流与分流 / 代谢对照基线 / 生命周期）。
- `assistant/00 专注区/00.专注区_agent.md`：专注区是按周切片的工作台，不是工作节律模板。
- `.codex/AGENTS.md §R` 思考协议：协议是"遇到问题就启动的处理机"（不止每轮开头）；执行中遇新问题返回 ② 重检索。

## v6.0.0 · PGH dreaming for Codex 新起点

dreaming 把记忆代谢从"每条消息实时判断写入"翻转为**白天零写入、夜间集中代谢**。这是相对旧 5.x 模板线的一次范式重构，不是补丁，因此另起新线、新仓库、新版本号。

### 范式变化

- **实时写入层整层退役**：删除旧版逐消息的 `memory_signal` hook 与 `episodic_inbox.md` 收件箱。白天对话不再实时判断记忆信号，校准信号以原文留在会话转写里。
- **L0 重定义为会话转写**：记忆代谢的唯一输入源改为 Codex 运行时自动落盘的 jsonl 转写（`<CODEX_HOME>/sessions/` + `archived_sessions/`）——完美保真、零维护。
- **新增 `merak-dream` skill**：夜间无人值守代谢执行者，回放当日转写完成全部提取、升星、升格、衰减。
- **昼夜节律**：白天 close-node 把工作结论固化进工作库；夜间 dream 做全部 schema 代谢；周日 dream 额外承担候选裁决、横向统合、衰减、毕业候选与周归档。

### 记忆池变化

- `episodic_memory.md`（L1）引入**四态**：活动 / 复审 / 候补 / 休眠。单事件信号入候补态等复现；停工项目的模式降入休眠态，免衰减、不占容量、重启即唤醒。
- **项目语境快轨**：高强度工作期同项目多个有效工作日复现的模式可带项目标注快速升 semantic，停工后自动降回 episodic 休眠。
- 记忆池内操作（升降格 / 衰减 / 统合）为 N 级自治，全部写 MEMORY_LOG 留账；只有身份层写入与结构变更需要用户 C 级 verdict。

### hooks / skills

- hooks（4）：`session_start.py`（compact 后重注入身份层）/ `thinking_protocol.py` / `session_context_check.py` / `session_end.py`。删除 `memory_signal.py`。
- skills（10）：`merak-dream` / `merak-daily-review` / `merak-weekly-review` / `merak-close-node` / `merak-write-progress` / `merak-create-project` / `merak-new-file` / `merak-week-sync` / `merak-due-diligence` / `merak-manage-research-reference`。
- `.codex/agents/*.toml` 承担检索与文件 IO（storage-agent 承接两 log 读写、长文件落盘、dream 转写分段回放）；记忆规则单一权威源在 `assistant/MEMORY/00.记忆区_agent.md`。

### 部署

发 `release v6.0.0` 链接给 Codex，由 AI 按 `§-1` 自己完成下载、占位符替换、旧系统检测与迁移、验证、自删。无一键脚本。
