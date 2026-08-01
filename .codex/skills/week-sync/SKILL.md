---
name: week-sync
description: Run [AI 名字]'s lightweight startup synchronization. Use automatically on every new/compacted session to summarize the current week and last work breakpoint, verify the last_dream probe, backfill up to three missed effective workdays through daily-dream, and remind about an unfinished Sunday work review.
---

# Week Sync

Restore work orientation and verify that the off-line memory loop survived the previous night.

## Boundaries

- Read-only except when a missing dream triggers the N-level `daily-dream` backfill.
- Do not read episodic/semantic pools during a healthy startup.
- Do not edit `_本周.md`, LTM, or project files.
- Do not inspect MEMORY_LOG directly; use storage-agent only when probe/log consistency is disputed.

## Loading chain

**Upstream**: `AGENTS.md §B · 启动序列` step 5.

**Inputs**: `_本周.md`, `<ASSISTANT_ROOT>/MEMORY/last_dream.md`.

**Peers**: `daily-dream` for missed-date recovery; `daily-dream 周段` for Sunday work review.

## Startup workflow

### 1. Summarize the week

Read `_本周.md` task list and latest substantive progress date. Report:

- current week and weekday position
- checked/total task count, explicitly noting when ledger checkboxes lag real progress
- one-sentence latest progress summary

### 2. Verify the dream probe

Use `00.memory_agent.md §逻辑日期`.

```text
expected completed dream date = current logical date - 1 calendar day
```

Read `last_dream.md §完成探针`.

- Probe >= expected date: healthy; say nothing extra.
- Probe behind: identify missed dates and determine which are effective workdays from `_本周.md`/week archives.
- Probe missing or unparsable: treat as a failed probe, not proof that no dream ran.

### 3. Backfill missed dreams

On the **first human session of the day**, when the probe is behind, invoke `daily-dream` in the background oldest-first for at most the latest three missed effective workdays. One logical day per run.

- Do not ask for permission: pool operations are N-level and this is the survival backstop. Say one line before starting (“last night's consolidation didn't run; I'm backfilling <date> in the background”), then report the result.
- On later sessions the same day, report status only — the first session already dispatched it.
- Never skip an earlier failed date and advance the probe past it.
- If more than three effective workdays are missing, process the latest allowed window and report the older accepted signal loss.
- If extraction or commit fails, **leave the probe unchanged** and report the exact failure. The next day's first session retries.

**Why automatic rather than a prompt**: a miss is caused by sleep, shutdown, or a dropped network — all of which happen overnight with nobody present. A prompt makes recovery depend on the user noticing it. One lost day is cheap; a lost week leaves the memory system with only its daytime half, and the loss is silent.

**The boundary hour is deployment-specific.** Read the current value from `AGENTS.md §时间感知` (written by `install_schedule.py` from the deployer's sleep/wake answers; any whole hour in 02:00–06:00). **Never assume 06:00 or a 06:10 run time.** For an early riser with a 03:00 boundary, work done at 04:00 already belongs to the new day; computing with 06:00 assigns it to the previous one, so both the “missed” and “healthy” verdicts land on the wrong date. The consolidation run fires at boundary + 30 minutes, so at physical times before the boundary the expected-date formula naturally points at the last closed logical day.

### 3b. Verify the first natural scheduled run

On the **first human session of the day**, also run the acceptance consumer:

```bash
python3 ~/.pgh/scripts/codex/verify_first_run.py --runtime codex --assistant-root <ASSISTANT_ROOT>
```

Use the copy under `~/.pgh/scripts/codex/` — the temporary clone used for deployment is usually gone.

Exit code 1 only means something is still pending (including the normal "expected time hasn't
arrived yet"); it is not an error. Read the pending items back to the user.

What it checks: the scheduler's own structured receipt (`~/.pgh/natural_runs.codex.jsonl`), plus
ground evidence, plus the job's state at verification time. A receipt only records
`source=os-scheduler` when the environment carried the proof that this install wrote into the OS
job definition; running the wrapper by hand records `manual-wrapper` and does not turn anything
green. That distinction is deliberate — when the schedule was never installed correctly, the user
has to remember to backfill every single day, and one forgotten day is silently lost.

**Never describe a manual wrapper run as "the first natural scheduled run has happened."** That is
only a wrapper success-path test. A natural run exists once the OS job fires on time (or catches up
on wake) and this script issues the receipt.

Once both `acceptance` flags are verified, stop running this step.

### 4. Check Sunday work review

Only on a Sunday logical date:

- If `_本周.md` already contains `### 本周产出`, do not remind.
- Otherwise say: `今天是周日，工作层周复盘还没完成。要现在开始吗？`

This reminder is for `daily-dream 周段`; Sunday memory consolidation remains the scheduled dream's job.

### 5. Restore the last breakpoint

From the latest substantive progress date, list every work segment:

```markdown
**上次工作**（YYYY-MM-DD）：
- [项目/工作线]：[一句话断点]
  → 关联文件：[file1] · [file2]
```

If the user's first message is “continue / continue yesterday / where were we,” immediately read the linked files and give a full breakpoint reconstruction.

## Completion

Keep the startup report concise. Include dream recovery only when it actually ran or failed. Do not expose internal system-report labels in ordinary conversation.
