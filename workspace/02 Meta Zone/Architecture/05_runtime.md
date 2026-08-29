---
title: 05 · Codex 运行时
type: architecture
version: 2.0
status: active
description: Codex 运行时、钩子、原生自动化任务与事务收据。
---

# 05 · Codex 运行时

## 三个落点

| 落点 | 内容 | 权限 |
|---|---|---|
| `<CODEX_HOME>/` | `AGENTS.md`、钩子、技能、代理 | Codex 读取与执行 |
| `<WORKSPACE_ROOT>/` | 用户内容、项目、工作台、记忆池、梦境收据 | 用户与 Codex |
| Codex 原生自动化任务数据区 | 自动化任务定义与运行历史 | 只经 Codex 自动化任务管理能力操作 |

其他命令行工具、桌面软件和系统任务调度器不在本发布包的运行边界内。

## 运行时文件

| 文件 | 作用 |
|---|---|
| `AGENTS.md` | 启动序列、权限、记忆路由、初始化协议 |
| `config.toml` | Codex 运行配置 |
| `hooks/timesense.py` | 注入当前真实时间 |
| `hooks/thinking_protocol.py` | 注入思考协议 |
| `hooks/session_start.py` | 会话启动与上下文压缩后重载身份层 |
| `skills/daily-dream/` | 唯一日级事务入口 |
| `skills/weekly-dream/` | 周日条件分支 |
| `skills/quarterly-archive/` | 季度 `detect` / `execute` 分支 |
| `agents/storage-agent.toml` | 长文件读写、日志与归档代理 |

## 唯一自动入口

Codex 原生自动化任务只保存一条状态为 `ACTIVE` 的每日独立项目任务：

- 名称（`name`）：`daily-dream`
- 提示词（`prompt`）：`使用 $daily-dream 处理最近一个已经闭合的逻辑日；严格执行事务闸，并报告提交收据。`
- 节律（`cadence`）：日界线后 30 分钟
- 项目（`project`）：`<WORKSPACE_ROOT>` 所在项目
- 执行方式（`execution`）：本地（`local`）

周日与季度逻辑完全留在技能内，不创建独立的周级或季度自动化任务。额外任务会造成重复回放和双写风险，发布边界闸必须判红。

## 自动化任务管理

创建、更新、查看、暂停和恢复统一走 Codex 原生自动化任务管理能力。部署与维护流程不得直接写自动化任务 TOML 或状态数据库。

## 两层证据

| 问题 | 证据 |
|---|---|
| 自动化任务当前是否存在并启用 | Codex 原生自动化任务回读 |
| 某次日链是否按计划触发 | Codex 自动化任务历史中的计划触发记录 |
| 目标逻辑日是否事务闭合 | `dream_receipts/YYYY-MM-DD.json` = `COMMITTED` |
| 探针是否推进 | `last_dream.md` 与提交收据同日 |
| 输入是否完整 | 覆盖收据状态为 `PASS` |
| 裁决是否绑定当前转写包 | 决策收据状态为 `PASS` |

自动化任务定义与梦境地面收据同时成立，才能判断系统健康。

## 故障恢复

- 自动化任务缺失或暂停：通过 Codex 原生管理能力修复同一任务。
- 自动化任务重复：保留用户确认的每日任务，删除重复项前取得明确授权。
- 计划触发失败：保留现场，按失败运行与梦境收据定位。
- 探针落后：`week-sync` 在首个真人会话按最早缺日优先补跑，最多三个有效工作日。
- 本地执行环境不可用：说明缺勤事实；不创建系统级替代调度。

完整排程合同见 `docs/schedule_interview.md`。
