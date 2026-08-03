---
name: weekly-dream
description: Run the weekly work and memory branch for an explicitly named Sunday. Use when daily-dream delegates a Sunday target, when the user asks to backfill or audit one weekly branch, or when week-sync identifies a missing Sunday branch. Require --date and --bundle; never infer either. Detect quarter points through quarterly-archive but never execute a quarterly archive automatically.
---

# Weekly Dream

Run Steps 1–6 in order. This skill is a conditional child of `daily-dream`: it does not extract transcripts, install another schedule, commit independently, or advance `last_dream.md`.

The rule kernel is `<ASSISTANT_ROOT>/MEMORY/00.memory_agent.md`.

## Fixed return

Return exactly seven lines to the parent; unreached fields remain present as `not-executed`:

```text
weekly_status: CLOSED | REJECT <exact reason> | STOPPED step N <exact reason>
work_layer: panorama=<count> archive=<path> weekly=<written> current_state=<written|unchanged> new_week=<written>
ledger_diff: missing=<count> fixed=<count> pending=<count>
memory_ops: candidates=<before>-><after> clusters=<count> episodic_deleted=<count> semantic_up=<count> semantic_down=<count>
graduation: none | <count and titles>
quarterly: quarter_point=<bool> last_sunday=<bool> week_sections=<count> receipt=<verbatim child result|not-triggered>
handoff: present | absent | unread
```

## Step 1 · Validate the parent transaction

Require both `--date YYYY-MM-DD` and `--bundle /tmp/daily-dream/YYYY-MM-DD`. Reject with zero writes unless:

- the date is Sunday;
- bundle manifest date matches the argument and has no unexplained extraction error;
- the daily chain's phase-A completion receipt exists and matches the same logical date;
- the parent has a complete phase-B decision table with evidence anchors and before/after pool counts.

An `_本周.md` date block is not a phase-A receipt. Missing work consolidation would make the weekly archive permanently omit Sunday work.

## Step 2 · Consolidate the weekly work layer

Read `### 周日梦载荷交接` once before archive work. Absence is `handoff: absent`, not failure.

In order:

1. append `### 本周产出` to `_本周.md` with outputs, decisions, reversals, unresolved items, and truthful deploy status;
2. archive the finished week under `00 Focus Zone/_归档/`;
3. update the LTM time axis and detailed weekly record through storage-agent;
4. update current-state/main-line text only when the week materially changed it;
5. create the new `_本周.md` through `new-file`, carrying only genuine unresolved items.

Summary precedes archive; archive precedes the new weekly file.

## Step 3 · Reconcile ledger and artifacts

Compare weekly progress pointers with the actual work artifacts and load chains. Read content before classifying a difference; mtime alone is not evidence of substantive work. Repair confirmed omissions before the archive closes, and mark uncertain dates as pending. A zero difference is explicit.

## Step 4 · Run weekly pool metabolism

Use fresh full-file state and the kernel's current rules:

1. rescan capacity and clear the weekly promotion-candidate inventory;
2. horizontally consolidate active/review episodic rows, writing semantic body/evidence before deleting contributors;
3. recompute episodic decay from current evidence, never a historical deletion list;
4. review semantic hits/breaks, repair or demote by schema type, and enforce capacity;
5. rescan and report exact before/after counts plus every rule-level exception.

Pool-row changes are N-level and must be disclosed. Send MEMORY_LOG text to storage-agent; do not edit the log directly.

## Step 5 · Produce graduation candidates

Apply the kernel's stability and independent-distillation rules. Produce proposals and hook sandbox evidence only. USER, SOUL, AGENTS, skills, and hooks require a current C verdict and remain untouched by the unattended chain.

## Step 6 · Detect the quarterly boundary

Use the explicit Sunday `D`. `quarter_point` is true when `D + 7 days` crosses quarter/year or when unarchived weekly sections since the previous archive are at least 13. Report `last_sunday`, `week_sections`, and the result separately.

When true, invoke:

```text
$quarterly-archive --mode detect --date <D>
```

Include its result verbatim. When false, do not invoke it. Detect mode inventories and creates a C-level pending proposal; it never executes an archive.

## Boundaries

- Never infer date or bundle, and never process an open logical day.
- Never extract transcripts, install a second scheduler, commit, or advance the daily probe.
- Never read/write MEMORY_LOG or ITERATION_LOG directly.
- Weekly failure returns the exact stopping point; it does not fabricate closure.
