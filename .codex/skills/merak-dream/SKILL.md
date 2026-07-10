---
name: merak-dream
description: Replay [AI 名字]'s Codex user-session transcripts and run controlled nightly memory metabolism. Use for the scheduled post-06:00 memory automation, missed-dream backfills, Sunday memory consolidation, or an explicit request to run/check [AI 名字]'s dream. Exclude subagent, automation, and internal-control turns.
---

# Merak Dream

Run [AI 名字]'s off-line memory metabolism from its own Codex transcripts. Keep work-history archiving in `merak-daily-review`; this skill only extracts and metabolizes reusable schema.

## Boundaries

- Read the rule kernel first: `<ASSISTANT_ROOT>/MEMORY/00.记忆区_agent.md`.
- Treat Codex JSONL transcripts as external, read-only L0. Never edit or relocate them.
- Replay only sessions whose effective `thread_source` is `user`. Exclude `subagent` and `automation` sessions.
- Do not reconstruct project history inside memory files. Project facts stay in project files, `_本周.md`, or LTM.
- Do not read or write `MEMORY_LOG.md` or `ITERATION_LOG.md` directly. Send exact finalized text to storage-agent.
- Only USER, SOUL, AGENTS protocol structure, skills, hooks, and whole-file deletion require C-level authorization. Pool-internal operations are N-level and must be disclosed in the dream log.
- Daytime continuous writes are disabled. `merak-close-node` is the sole in-presence exception and may write L1 only when a node is explicitly closed and at least two independent events support the schema.

## Inputs and outputs

Inputs:

- `<CODEX_HOME>/sessions/**/*.jsonl`
- `<CODEX_HOME>/archived_sessions/*.jsonl`
- USER, [AI 名字] SOUL, and `AGENTS.md §R` identity-layer context loaded at startup; pool files are not startup-loaded and must be read in full at Step 3
- `_本周.md` and project progress only when checking whether an event was already fixed in the work library

Outputs:

- Updated [AI 名字] `episodic_memory.md` and `semantic_memory.md`
- Evidence additions to `_archive/semantic_archive.md` when semantic changes occur
- A single dream summary appended to `MEMORY_LOG.md` by storage-agent
- `<ASSISTANT_ROOT>/MEMORY/last_dream.md` updated only after the entire transaction succeeds

## Workflow

### 1. Resolve the logical date and coverage

Use the rule kernel's `§逻辑日期`: before 06:00, the logical date is the previous physical date.

Logical date `D` covers physical time `[D 06:00, D+1 06:00)`. A production dream must not run before that window closes; the normal automation runs at 06:10.

At the scheduled 06:10 run, `target D = current logical date - 1 day` (equivalently, the previous physical date). Never process the current logical date whose transcript window is still open.

Read `last_dream.md` if present:

- Probe already at or beyond the requested date: return a no-op unless [用户称呼] explicitly requests a force audit; never double-count the date.
- Normal scheduled run: process the most recent completed logical date only.
- Missed dream: backfill at most the latest three effective workdays, oldest first.
- A date with no substantive user session is a valid zero-input dream; record it without inventing signals.

Never advance `last_dream.md` past an earlier failed date.

### 2. Extract the complete user-session bundle

Run:

```bash
<PYTHON_BIN> <CODEX_HOME>/skills/merak-dream/scripts/extract_daily_transcripts.py \
  --date YYYY-MM-DD
```

The script writes a transient bundle under `/tmp/merak-dream/YYYY-MM-DD/` and prints a JSON summary. Inspect `manifest.json` before reading `transcript.md`.

Hard checks:

- `errors` must be empty, or every error must be explained before continuing.
- No included source may have `thread_source=subagent` or `thread_source=automation`.
- Runtime scaffolding (`recommended_plugins`, injected AGENTS text, environment context, subagent notifications, Codex internal continuation context, and turn-aborted frames) must not appear as user evidence.
- A turn whose user side contains only internal control frames must be absent in full, including its assistant continuation output.
- The manifest window must be `06:00 -> next-day 06:00`, not the natural calendar day.
- Read all of `transcript.md` in chunks. Do not substitute recent context, the final turn, `_本周.md`, or a compact summary for the transcript bundle.
- **强制真读硬约束**：必须真读 `transcript.md` 全文，**严禁用 compact 上下文 / 当前会话记忆 / `_本周.md` 摘要顶替 L0 真读**。在场时段也不例外——dream 是离线代谢，输入只能是转写，不能是"记得今天干了什么"。

### 3. Load the comparison baseline

Read both pool files in full before judging new signals:

- `episodic_memory.md`: candidate, active, review, and dormant intermediate schema
- `semantic_memory.md`: non-injected active semantic schema and promotion candidates

Compare against the already-loaded USER, [AI 名字] SOUL, and AGENTS §R identity layer. The subtraction baseline is mandatory: without it, a hit cannot be distinguished from a new schema.

Count pool states and apply `§两池容量阈值`. Report counts even if there are no changes.

### 4. Replay and classify every substantive exchange

Walk the bundle chronologically. For each candidate observation:

1. Separate event direction from schema direction.
2. Check whether the event direction is already fixed in the work library. Report a missing work record; do not silently write shared history from the dream.
3. Apply identity-layer filtering.
4. Apply P/C axes against the schema that existed at that point.
5. Drop `P=hit + C=neutral` and ordinary identity-layer confirmations.
6. Preserve explicit confirmations of intermediate episodic/semantic schema as strengthening evidence.

Keep raw evidence anchors as logical date + session id + turn id. Do not store whole chat passages in pool files.

### 5. Apply episodic operations

Execute the kernel's `§episodic 状态机`, `§生成`, `§L0→L1 升格抽象红线`, `§升星`, and `§episodic 衰减` exactly. These headings are the single authority for state names, evidence thresholds, daily operations, and Sunday-only operations; do not reconstruct them from this skill.

Record every create/strengthen/correct/wake/delete decision with evidence anchors before touching the file. Apply all accepted operations as one pool transaction.

### 6. Apply semantic operations

Execute `§升格判准`, `§项目语境快轨`, `§升格动作`, `§横向统合`, and `§semantic 衰减` from the kernel. The kernel alone defines daily exceptions, the Sunday gate, capacity behavior, and project-context handling.

Keep semantic off the startup path. Pool-internal operations are disclosed N-level transactions; identity/runtime graduation remains a C proposal.

### 7. Add the Sunday load when applicable

For a Sunday logical date, execute the kernel's weekly-only operations: `§横向统合`, both decay sections, capacity actions, project-context review, and `§毕业`.

When `§毕业` requires independent distillation or hook sandbox tests, spawn mutually isolated agents with only the artifact and target-format rules. Produce a proposal; never modify identity/runtime targets without C authorization.

### 8. Commit as one transaction

Commit in this order:

1. Write pool bodies and semantic evidence.
2. Re-read touched entries and verify counts/state invariants.
3. Finalize one compact dream log entry and send it to storage-agent.
4. Confirm storage-agent's write and U+FFFD check.
5. Update `last_dream.md` to the completed logical date.

If any earlier step fails, do not advance the probe. Preserve source files and report the exact failure.

## Completion report

Report only:

- logical date and session/turn coverage
- before/after pool counts
- created, strengthened, corrected, consolidated, decayed, awakened, or deleted entries
- missing work-library records and C-level proposals
- probe status and whether Sunday load ran

Do not narrate project work or paste transcript content into the report.
