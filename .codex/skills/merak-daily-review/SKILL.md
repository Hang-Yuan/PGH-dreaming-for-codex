---
name: merak-daily-review
description: Consolidate [AI 名字]'s current-day work into project progress, the weekly workbench, and handoff records without touching memory pools. Extract the full session bundle for the logical date, then fix work events into authority layers. Use on goodbye/session-end, an explicit daily summary request, or as the work-layer stage of the scheduled 06:10 automation before merak-dream.
---

# Merak Daily Review

Close the work-record stream for one logical day. Memory extraction is owned by `merak-dream`; this skill never writes episodic or semantic pools.

## Boundaries

- Paths under <ASSISTANT_ROOT> and <CODEX_HOME> may be updated within existing S/N authority.
- Shared `_本周.md`, LTM, USER, and project authority files remain read-only unless [用户称呼] explicitly authorizes the write.
- Do not read/write `MEMORY_LOG.md` or `ITERATION_LOG.md` directly.
- Do not read or write `episodic_inbox.md`, `episodic_memory.md`, or `semantic_memory.md` in this workflow.
- Run idempotently: the scheduled automation may revisit work already recorded by a goodbye-triggered run.

## Loading chain

**Upstream**: `session_end.py` goodbye signal; explicit “daily review / today summary / [AI 名字] handoff”; scheduled 06:10 automation stage A.

**Downstream**: active project `_overview.md` and `_progress/`; `_本周.md`; `merak-weekly-review` on a Sunday logical date.

**Peers**: `merak-close-node` for closed work nodes; `merak-write-progress` for project reasoning chains; `merak-dream` for off-line schema metabolism.

## Workflow

### 1. Resolve the logical date

Use `00.记忆区_agent.md §逻辑日期`. All work records and handoff dates use the logical date; current-time display uses physical time.

### 2. Extract the full session bundle for logical date D

This is the first execution action of work-library consolidation: locate the full set of the day's active sessions before fixing any work event. Consolidation runs "locate the full day's sessions (this step) -> reconstruct timeline -> fix into authority layers (steps 3-6)".

Run:

```bash
<PYTHON_BIN> <CODEX_HOME>/skills/merak-dream/scripts/extract_daily_transcripts.py \
  --date YYYY-MM-DD
```

The script writes a transient bundle under `/tmp/merak-dream/YYYY-MM-DD/` and prints a JSON summary. Inspect `manifest.json` before reading `transcript.md`.

Hard checks:

- `errors` must be empty, or every error must be explained before continuing.
- No included source may have `thread_source=subagent` or `thread_source=automation`.
- Runtime scaffolding must not appear as user evidence.
- The manifest window must be `06:00 -> next-day 06:00`.
- Read all of `transcript.md` in chunks. Do not substitute recent context, the final turn, `_本周.md`, or a compact summary for the transcript bundle.

### 3. Reconstruct the full work timeline

List every substantive phase from the session bundle in chronological order before judging importance. Do not collapse a long day into the final incident.

For each phase classify:

- work event: what was done, chosen, built, tested, or rejected
- project conclusion: a result that belongs in a project authority file
- closed node: a solved subproblem or completed continuous work segment
- unresolved item: a live decision, dependency, or C-level verdict
- architecture/protocol change: belongs in ITERATION_LOG via storage-agent during the implementation turn, not as memory

### 4. Close missed nodes

If a node is factually closed but `merak-close-node` has not run, invoke it.

- Present the main-document judgment required by that skill.
- In unattended scheduled mode, do not block: hold C-level document writes and continue.
- The close-node memory exception is governed by its own skill; daily-review itself still does not touch a pool.

### 5. Fix work events into the correct authority layer

Use the single-authority rule:

| Content | Destination |
|---|---|
| project reasoning / decision chain | project `_progress/` via `merak-write-progress` |
| project status / breakpoint | project `_overview.md` |
| durable project conclusion | project main document after C verdict |
| current-week actions and outputs | `_本周.md §进展记录` |
| current-situation change | LTM §当前处境 after authorization |

Do not duplicate an entry already present for the same logical date and files. Extend it only with genuinely missing phases.

### 6. Update the weekly workbench

When authorized, append one date block to `_本周.md §进展记录`:

```markdown
### YYYY-MM-DD（周X）

**项目 / 工作线**（`root/path`）
关联：`file1` · `file2`

- 完成的动作、决定与当前断点。
```

Keep reasoning detail in project files.

### 7. Route unresolved items

- S/N items: leave the next action in the project/workbench.
- C items: state the exact target, proposed change, and why a verdict is required; do not imply completion.

### 8. Add the Sunday work review

If the logical date is Sunday, invoke `merak-weekly-review` for work-layer review and week archiving. In unattended mode it must not wait for reflection or C verdicts.

Memory consolidation is not part of this call; the scheduled automation invokes `merak-dream` after work-layer stages finish.

### 9. Complete the handoff

Report in natural language:

- logical date and work phases captured
- files updated
- closed nodes and unresolved verdicts
- whether weekly work review ran
- confirm that memory metabolism is deferred to merak-dream

For a goodbye-triggered run, finish the workflow before answering the goodbye.

## Do not

- Do not scan or clear an inbox.
- Do not nominate or promote semantic entries.
- Do not use a work summary as a substitute for transcript replay.
- Do not invent completion when a C-level shared write was held.
