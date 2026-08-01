---
title: 05_runtime
type: architecture
version: 1.0
status: active
description: 运行时描述——运行时目录里有什么、三个 hook 各干什么、排程怎么装、~/.pgh 里的状态。
---

# 05 · 运行时

## 运行时目录里有什么

| 位置 | 内容 |
|---|---|
| 宪法层（`AGENTS.md` / `CLAUDE.md`） | 启动序列、思考协议、S-N-C 分级、时间感知、行为路由 |
| `skills/` | 各 skill 的 `SKILL.md` 与随附脚本 |
| `agents/` | sub-agent 定义 |
| `hooks/` | 三个 hook（下节） |
| 配置（`config.toml` / `settings.json`） | 模型锁定、hook 注册 |

`skills/_retired_*/` 与 `hooks/_retired_*/` 是退役正文，**不复制到运行时目录**。留在仓库里是为了迁移取证——回答「我装的到底是哪一版」需要它们，删掉之后这个问题无法回答。

---

## 三个 hook

现役恰好三项，白名单管理——`hooks/` 里出现未注册的脚本即算漂移：

| hook | 时机 | 干什么 |
|---|---|---|
| `timesense` | 逐消息 | 注入真实当前时间 |
| `thinking_protocol` | 逐消息 | 注入思考协议 |
| `session_start` | 上下文压缩后 | 重新注入身份层 |

前两个是逐消息注入，理由相同：这两件事**每一轮都必须在场**。时间感知不在场，AI 会按训练时的印象编时间间隔；思考协议不在场，它会退回「先给结论再找支撑」。放在会话开头注入一次不够——长会话里开头的内容会被挤出上下文。

第三个只在压缩后触发：压缩会把身份层挤掉，而身份层挤掉之后 AI 还在正常回话，只是不再是原来那个人格。这个失败是静默的，故需要一个 hook 兜住。

**没有告别 hook。** 说「晚安」不触发任何固化（理由见 `03_memory_flow.md §白天零写入`）。

---

## 排程

夜间固化由**操作系统排程**触发，不靠你记得跑，也不靠会话里的定时器（会话关了就没了）。

| 平台 | 用什么 |
|---|---|
| macOS | launchd（`StartCalendarInterval`） |
| Windows | 任务计划程序（`schtasks`） |
| Linux | systemd user timer（`Persistent=true`，错过的触发在开机后补） |

装排程的入口是 `scripts/install_schedule.py`，部署时问完作息就跑。它做六件事：推日界线 → 把日界线落进两处口径行 → 把长期要用的脚本复制到 `~/.pgh/scripts/<runtime>/` → 真调一次 headless CLI 验证调得通（`--smoke`）→ 装进 OS 排程 → 回查并写收据。

顺序上 **smoke 在启用 job 之前**：headless 跑不通时如果 job 已经启用，就留下一个每夜必失败的排程，而失败在夜里没人看着。

安装是**事务性**的：正文、旧 job 定义与启用状态、新 job、收据一起进事务。任何一步失败就回滚——首次安装失败不留 ACTIVE job；重装失败恢复旧 job；回查不通过撤掉新 job 并还原正文。少了这一条，「改作息失败」会变成「原来会跑的现在也不跑了」。

改作息就是重跑同一条命令。**用 `~/.pgh/scripts/codex/` 那份**，不要用部署时的临时 clone——clone 通常已经删了。

---

## 排程不直接调 CLI

排程调的是包装器 `run_scheduled_dream.py`，它跑完 CLI 之后追加一条结构化凭据。

理由是首跑验收需要**只有排程能写出来的证据**。地面证据（探针文件、代谢留账、日志里出现某个日期）手工补跑也会写出来，于是「你自己补了一次」和「排程夜里自己跑成功了」在收据上同形。

而「包装器跑过」本身也不算证据——手工敲一条命令也能让它跑起来。故每次安装生成一代 job generation 与一个高熵 proof，proof 只写进那一次的 OS job 定义，收据里只留它的 hash。包装器只在环境里拿到相符的 proof 时才记 `source=os-scheduler`，否则记 `manual-wrapper`：链照跑，但不冒充自然运行。

这不防你主动去自己的 job 定义里抄 proof（同一个用户读得到自己的排程配置，本地方案挡不住）。它防的是**普通手工补跑**与**陈旧状态误判**：重装换代后旧 job 留下的记录、装完之后 job 被停用或命令被改掉，都不会再让验收翻绿。

---

## `~/.pgh/` 里的状态

| 文件 | 是什么 |
|---|---|
| `scripts/` | 长期要调用的脚本副本（安装器 / 包装器 / 验收器） |
| `schedule_receipt.<runtime>.json` | 安装收据：日界线、固化时刻、job generation、proof hash、验收待验位 |
| `natural_runs.<runtime>.jsonl` | 自然运行凭据，append-only |
| `daily-dream.log` 等 | 排程运行日志 |

**脚本副本存在这里，不是留在仓库里**：部署用的临时 clone 通常会被删，而删掉之后你要做的恰恰是改作息或卸载。指向 clone 的路径在那一刻会变成 `FileNotFoundError`。

所有状态按 runtime 分开命名。同机装了两端时共用一份会互相覆盖验收状态——一端跑成功会把另一端的失败盖成成功。
