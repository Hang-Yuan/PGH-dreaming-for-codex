---
title: semantic_memory.md
type: memory-pool
layer: semantic
target_file: <ASSISTANT_ROOT>/MEMORY/semantic_memory.md
created: YYYY-MM-DD
updated: 2026-06-27
---

# MEMORY semantic_memory

## 加载链（上下游）

**上游**：`AGENTS.md §B · 启动序列` — 本文件**不在启动序列读入**（v5.6.0 退出启动注入）。在夜间被 dream 作为代谢对照基线读取。

**管辖文件（下游）：**
- `_archive/semantic_archive.md` — 本文件所有证据、命中、演化记录的详记。

**同级联动：**
- `episodic_memory.md` — semantic 条目升格来源或降级去处。
- `00.memory_agent.md` — 升降、衰减、毕业规则（唯一权威源）。
- `MEMORY_LOG.md` — 记忆代谢流水。
- `USER/USER.md` / `SOUL/persona/persona_SOUL.md` / `~/.codex/skills/` — 毕业目标（终态身份层）。

---

## 文件职责

本文件是语义级 schema 的**中间工作区**（4-6 星，等毕业进身份层）。**不启动注入**——白天对运行时不可见，仅在夜间被 dream 作为代谢对照基线读取（代谢期是 semantic 唯一被读取的时机）。主文件极简；证据、来源、命中记录、演化记录全部写入 `_archive/semantic_archive.md`。

升降星 / 毕业规则：权威源 = `00.memory_agent.md §升格判准 / §semantic 衰减 / §毕业`。

---

## 条目格式

### [条目标题]
- **强度**：★★★★ / ★★★★★ / ★★★★★★候选
- **状态**：活跃组 / 备用 / 需要修订 / 毕业候选
- **类型**：程序 / 语义 / 混合
- **预测情境**：[何时调用这条 schema]
- **行动预期**：[模型应如何预测或行动]
- **证据指针**：`_archive/semantic_archive.md §[条目ID]`

---

## 活跃组

> 初始为空。由 dream 日级快轨 / 周日横向统合写入（N 级，MEMORY_LOG 留账）。

<!-- 活跃组示例（用户实际有 schema 时按此格式填入）：

### [示例 schema 标题：某类情境下的稳定预测]
- **强度**：★★★★
- **状态**：活跃组
- **类型**：程序
- **预测情境**：[何时调用]
- **行动预期**：[如何预测或行动]
- **证据指针**：`_archive/semantic_archive.md §S001`

-->

---

## 升格候选池

> daily-dream 日级代谢提名写入；weekly-dream 每周强制清空（升格进活跃组 / 退回 episodic / 删）。不启动注入。条目格式同活跃组，状态字段写「升格候选」。

（当前空）

---

## 备用组

> 活跃组满载时，被退出的低优先级 schema 暂存于此。初始为空。

---

## 毕业候选

> 6 星候选 + 跨周稳定 + [用户称呼] C verdict 后毕业到 USER / persona_SOUL / skill。初始为空。
