---
name: merak-close-node
description: Close a completed Tianxuan work node across project authority files, progress, weekly records, and handoff pointers. Use when a subproblem, decision, task, or continuous work segment has genuinely closed. Memory writing is limited to one controlled L1 exception with at least two independent events; all ordinary extraction waits for merak-dream.
---

# Merak Close Node

Synchronize a closed work node before changing direction. Keep project truth and reusable schema separate.

## Boundaries

- Shared project, LTM, USER, and weekly files require current authorization.
- Always make the main-document judgment explicit.
- Do not write semantic memory, identity layers, hooks, or runtime configuration.
- Do not read/write `episodic_inbox.md`; it is retired.
- The only in-presence pool write allowed is the L1 exception in `§记忆例外`.
- Send MEMORY_LOG text to storage-agent; never edit either private log directly.

## Loading chain

**Upstream**: model self-detection; explicit “close this / next / done”; daily-review missed-node scan.

**Downstream**: project main document/overview/progress, `_本周.md`, and optionally `episodic_memory.md`.

**Peers**: `merak-write-progress`, `merak-new-file`, `merak-daily-review`, `merak-dream`.

## Trigger test

A node is closed only if its local success criterion is met: a decision is fixed, a subproblem is solved, an artifact is delivered and checked, or the current segment has a stable breakpoint. Mere fatigue, context length, or topic drift is not closure.

If closure is ambiguous, ask. If the user explicitly ordered closure, proceed.

## Work-layer transaction

### 1. Locate the authority layer

Identify the active project/work line and read its `_overview.md` plus the progress pointer covering this node. For cross-project work, choose one primary authority source and use pointers elsewhere.

### 2. Judge the main document

Always output:

```text
主文档判断：[需要更新 / 不需要更新]
若需要：目标节 + 拟写入结论/证据
若不需要：具体理由
```

The main document needs updating when the node adds or changes any of:

- evidence, case, or data supporting/refuting an existing claim
- theoretical anchor or key definition
- literature support
- durable decision affecting a boundary or design principle
- top-level framework

Wait for C verdict before editing a shared main document. In unattended daily-review mode, hold the write and continue.

### 3. Update overview and progress

When authorized:

- `_overview.md`: current state, exact breakpoint, live questions, new file pointers
- `_progress/`: invoke `merak-write-progress` to preserve the reasoning chain
- mark transitions with the project's existing transition convention

Create Markdown files only through `merak-new-file`.

### 4. Update the weekly ledger

When authorized, append/extend the logical-date work block and update only checkboxes proven complete.

### 5. Record unresolved items

Leave each unresolved item with owner, dependency, next action, and authority target.

## 记忆例外

The normal path is **no daytime pool write**: Codex JSONL preserves the node and `merak-dream` extracts it at night.

Write directly to `episodic_memory.md` only when all conditions hold:

1. the node is explicitly closed;
2. at least two independent events—not repeated mentions of one event—support the same pattern;
3. the result is a reusable `trigger situation -> action/prediction`, not a project fact;
4. it passes `00.记忆区_agent.md §身份层前置过滤` and `§L0→L1 升格抽象红线`;
5. full-table comparison shows it is not an existing schema hit.

Then:

- write one-star `活动` L1 with `语境：跨情景` or the exact project context;
- if it hits an existing entry, strengthen that entry instead of creating another;
- never write a candidate from a single ordinary event;
- never promote to semantic here;
- send one compact log line to storage-agent with node, operation, and evidence anchors.

If any condition fails, write nothing; the transcript remains available to the dream.

## Verification

- Re-read touched project/work entries.
- Check pointers with `rg` and ensure new anchors are unique.
- If L1 changed, verify entry fields/state/count and U+FFFD=0.
- Report main-document verdict, files updated/proposed, current breakpoint, and whether the L1 exception fired.
