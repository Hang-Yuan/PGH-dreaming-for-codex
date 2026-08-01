---
name: daily-dream
description: Daily work consolidation plus memory metabolism as one chain. Invoked automatically with no arguments by the OS schedule after the day boundary; also on "run daily-dream", "backfill YYYY-MM-DD", "the dream missed a day", or when week-sync reports a gap and the user says to backfill. **Not** invoked on goodbyes ("that's it for today", "good night") — parting does not consolidate; the day's work is handled by the next morning's scheduled run.
updated: 2026-08-01
---

# Daily Dream

One chain, two phases: **phase A work consolidation** (work library) → **phase B memory metabolism** (memory pools). When the target logical date is a Sunday, a **weekly load** follows phase B. Execute steps 1→9 in order. Do not skip a step and do not downgrade one to "optional if needed".

The judgment criteria themselves live in `<ASSISTANT_ROOT>/MEMORY/00.memory_agent.md`. This skill holds pointers and execution ordering only.

## Boundaries

- Read the rule kernel first: `<ASSISTANT_ROOT>/MEMORY/00.memory_agent.md`.
- Treat Codex JSONL transcripts as external, read-only L0. Never edit or relocate them.
- Replay only sessions whose effective `thread_source` is `user`. Exclude `subagent` and `automation` sessions.
- Do not reconstruct project history inside memory files. Project facts stay in project files, `_本周.md`, or LTM.
- Do not read or write `MEMORY_LOG.md` or `ITERATION_LOG.md` directly. Send exact finalized text to storage-agent.
- Only USER, SOUL, AGENTS protocol structure, skills, hooks, and whole-file deletion require C-level authorization. Pool-internal operations are N-level and must be disclosed in the dream log.
- Daytime continuous writes are disabled. `close-node` is the sole in-presence exception and may write L1 only when a node is explicitly closed and at least two independent events support the schema.

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

Read the boundary hour from `00.memory_agent.md §逻辑日期` (mirrored in `AGENTS.md §时间感知`). **It is a deployment-specific value, not a constant**: `install_schedule.py` writes any whole hour in 02:00–06:00 from the deployer's sleep/wake answers. Before that hour, the logical date is the previous physical date.

Logical date `D` covers physical time `[D boundary, D+1 boundary)`. A production dream must not run before that window closes; the scheduled run fires at **boundary + 30 minutes**.

At the scheduled run, `target D = logical date at fire time - 1 day` — the just-closed window. Never process the current logical date whose transcript window is still open.

Do not hardcode 06:00 or 06:10 anywhere in this chain. For a deployer with a 03:00 boundary, work done at 04:00 already belongs to the new day; computing with 06:00 files it under the previous one and every consolidated entry lands on the wrong date, with nothing to raise an error.

Read `last_dream.md` if present:

- Probe already at or beyond the requested date: return a no-op unless [用户称呼] explicitly requests a force audit; never double-count the date.
- Normal scheduled run: process the most recent completed logical date only.
- Missed dream: backfill at most the latest three effective workdays, oldest first.
- A date with no substantive user session is a valid zero-input dream; record it without inventing signals.

Never advance `last_dream.md` past an earlier failed date.

### 2. Extract the complete user-session bundle

Run:

```bash
<PYTHON_BIN> <CODEX_HOME>/skills/daily-dream/scripts/extract_daily_transcripts.py \
  --date YYYY-MM-DD
```

The script writes a transient bundle under `/tmp/daily-dream/YYYY-MM-DD/` and prints a JSON summary. Inspect `manifest.json` before reading `transcript.md`.

Hard checks:

- `errors` must be empty, or every error must be explained before continuing.
- No included source may have `thread_source=subagent` or `thread_source=automation`.
- Runtime scaffolding (`recommended_plugins`, injected AGENTS text, environment context, subagent notifications, Codex internal continuation context, and turn-aborted frames) must not appear as user evidence.
- A turn whose user side contains only internal control frames must be absent in full, including its assistant continuation output.
- The manifest window must be `<boundary>:00 -> next-day <boundary>:00`, not the natural calendar day. `extract_daily_transcripts.py` resolves `<boundary>` itself (schedule receipt first, then the installed authority text) and prints which source it used; pass `--boundary-hour` only to override. **Never write 06:00 into this window** — it is deployment-specific, and a wrong value silently shifts the whole extraction window.
- **Do not pass `--timezone` either.** The script resolves the IANA zone from the schedule receipt (top-level field first, then the legacy `acceptance` nesting for machines installed before that field existed) and prints the source it used. Passing a zone explicitly overrides the receipt, so a hardcoded `Asia/Shanghai` in this command would move the whole window for every deployer outside that zone — and the manifest's dates, counts, and paths all stay self-consistent, so the shift is invisible in the output. Check the two stderr provenance lines (`boundary hour = …`, `timezone = …`) against the deployment; a `**兜底**` marker on either one means the receipt was unreadable and the window may be wrong.
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
