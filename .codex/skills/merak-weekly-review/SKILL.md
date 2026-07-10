---
name: merak-weekly-review
description: Review and archive [AI 名字]'s weekly work layer without directly metabolizing memory pools. Use on Sunday, for an explicit weekly review, or from the scheduled daily-review stage; audit the weekly ledger, align the main line, archive the week when authorized, and hand Sunday memory work to merak-dream.
---

# Merak Weekly Review

Close the weekly work-record stream. `merak-dream` owns Sunday episodic/semantic consolidation.

## Boundaries

- Read `_本周.md`, LTM current situation/timeline, and active project overview/progress files.
- Shared workbench/LTM/project writes require current authorization.
- Never read or write episodic/semantic pools or either private log in this skill.
- Quarterly deletion/archiving and identity-layer changes require explicit C verdict.
- Unattended scheduled mode must not wait for user input; held items remain explicit and the flow continues.

## Loading chain

**Upstream**: Sunday `merak-daily-review`; `merak-week-sync` Sunday reminder; explicit “weekly review / this week summary”.

**Downstream**: `_本周.md` summary/archive, new-week workbench, LTM timeline/current situation, active project pointers.

**Peer interface**: `merak-dream §7. Add the Sunday load when applicable` performs all weekly memory operations after the work layer is closed and the logical-day window has ended.

## Preparation

1. Resolve the logical date from `00.记忆区_agent.md §逻辑日期`.
2. Read `_本周.md` completely.
3. Read LTM `§当前处境` and `§时间轴`.
4. Identify active projects from weekly progress and read each `_overview.md`; follow only relevant progress pointers.
5. Determine whether the run is interactive or unattended.

## Workflow

### 1. Audit ledger versus filesystem

Treat `_本周.md` as the ledger and current-week file changes as evidence.

1. Collect files named in every `关联：` line.
2. Scan active project roots for Markdown files modified since the week start.
3. Exclude archives, static overviews, reference catalogs, and generated artifacts that are not work outputs.
4. Inspect only enough of each difference file to determine whether it is missing work.
5. Add confirmed missing events to the proposed weekly ledger; mark uncertain dates as `待确认`.
6. Mark checkboxes complete only when the progress record proves completion.

Do not treat mtime alone as proof of substantive work.

### 2. Build the weekly panorama

Summarize:

- task completion status
- core progress and concrete outputs
- decisions and reversals
- cross-project connections
- unexpected discoveries
- unresolved items

Filter unresolved items:

- absorbed by later work -> close as absorbed
- no longer supports the main/secondary contradiction -> drop with reason
- transactional/researchable -> delegate explicitly
- still live -> carry forward with exact breakpoint

### 3. Give Sherlock reflection space

In interactive mode, present the panorama and ask what felt especially important, changed, or remained unresolved. Incorporate that input before archiving.

In unattended mode, skip the wait and preserve a clearly labeled reflection gap; do not invent feelings or judgments.

### 4. Check main-line alignment

Compare the week against LTM `§当前处境`:

- Did the principal contradiction advance?
- Was a detour valuable enough to justify displacement?
- Is the current-situation snapshot stale?

Write shared LTM only with authorization; otherwise send a concrete replacement proposal .

### 5. Resolve current states truthfully

For every major work line, distinguish:

- experimentally advanced
- design-converged
- validated but not fully tested
- waiting for C verdict
- promoted/deployed
- blocked or untouched

For the current meta toolchain:

- MetaScale = meta-skill line; experimental candidate progress is separate from runtime promote.
- UltraScale = meta-orchestrator line; spec/test progress is separate from a deployable orchestrator.

Never rewrite “not promoted” as “no substantive progress.”

### 6. Prepare the weekly output block

When authorized, append `### 本周产出` to `_本周.md` with:

- core progress
- key outputs
- key decisions
- filtered carryovers
- memory status pointer: `Sunday memory consolidation handled separately by merak-dream`

Without authorization, .

### 7. Archive and open the next week

When authorized:

1. Archive `_本周.md` as `_归档/YYYY-Wnn.md`.
2. Insert the week at the top of LTM `§时间轴` and append its detailed week record.
3. Create the next `_本周.md` with the standard load chain; invoke `merak-new-file` for any new Markdown file.
4. Carry forward only surviving items from step 2.

Without authorization, prepare a  package listing every target file and exact proposed change.

### 8. Check the quarterly boundary

Trigger a quarterly proposal when either:

- the logical Sunday is the quarter's final Sunday, or
- 13 unarchived detailed-week sections have accumulated.

Quarterly archive targets are LTM, MEMORY_LOG, and ITERATION_LOG. Obtain explicit C verdict, then send the job to Kulou and verify the returned structure/counts. Do not infer authorization from the trigger.

### 9. Hand off Sunday memory work

Do not touch memory pools here.

- Scheduled 06:10 automation: after this skill completes, invoke `merak-dream` for the same Sunday logical date.
- Interactive full review: if Sherlock explicitly asks to include memory and the Sunday logical-day window is complete, invoke `merak-dream`; otherwise report that the scheduled run will do it.

## Completion report

Report the panorama, main-line judgment, files updated/proposed, carried items, archive state, quarterly trigger state, and Sunday dream handoff. Keep memory statistics out until merak-dream returns them.
