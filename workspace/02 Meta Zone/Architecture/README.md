---
title: PGH 架构说明书
type: architecture-index
version: 2.0
status: active
description: 架构说明书入口——系统结构、信息流、运行时与机械验收的描述层索引。
---

# PGH · 架构说明书

这份说明书面向首次部署和系统维护。公开模板的目录坐标与本机现役工作空间保持一致，中文负责解释语义，机器文件名不另造一套翻译。

## 阅读顺序

| 文件 | 内容 |
|---|---|
| `01_topology.md` | 工作空间、运行时与文件落点 |
| `02_agents.md` | 主代理与子代理的分工 |
| `03_memory_flow.md` | 会话转写如何代谢为记忆 |
| `04_work_memory_flow.md` | 工作结论如何固化 |
| `05_runtime.md` | Codex 运行时、钩子与原生排程 |
| `06_cadence_and_gates.md` | 自动节律与机械验收闸 |

## 这套系统是什么

一个人和 Codex 共用一套“文件系统即工作记忆”的工作空间。长期增长的内容按失效速度分层：区域规则负责边界，索引层承载当前状态，内容层按需读取。私有记忆池在夜间代谢，不进入白天启动注入。

自动做梦由 Codex 原生自动化任务触发；操作系统任务调度器和其他 AI 软件不接入本系统。

## 全景

```text
用户
  ↓
Codex 运行时
  ├─ 主控文件
  ├─ 钩子
  ├─ 技能
  └─ 子代理
  ↓
<WORKSPACE_ROOT>/
  ├─ 00 Focus Zone/
  ├─ 01 Projects Zone/
  ├─ 02 Meta Zone/
  ├─ 03 Communication Zone/
  ├─ 04 Learning Zone/
  ├─ 05 Reading Zone/
  ├─ 06 Writing Zone/
  ├─ Long_Term_Memory/
  ├─ USER/
  ├─ SOUL/
  └─ MEMORY/
```

## 权威源索引

| 信息 | 权威源 |
|---|---|
| 全局启动、行为纪律、时间感知 | Codex 主控文件 |
| 各工作区层级与写入边界 | 对应 `00.{区域}_canon.md` |
| 当前处境 | `Long_Term_Memory/status.md` |
| 跨周流水 | `Long_Term_Memory/weekly.md` |
| 用户身份 | `USER/USER.md` |
| AI 人格 | `SOUL/persona/persona_SOUL.md` |
| 记忆结构、判准与阈值 | `MEMORY/00.memory_agent.md` |
| 协议变更 | `02 Meta Zone/ITERATION_LOG.md` |
| 具体技能流程 | 对应 `SKILL.md` |

## 描述层声明

本目录是描述层；主控文件、区域 canon、记忆区权威源和技能正文是规定层。规定层与描述层冲突时以规定层为准，并在同一轮修正描述层。
