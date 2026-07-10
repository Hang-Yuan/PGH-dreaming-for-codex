---
name: merak-week-sync
description: Run [AI 名字]'s lightweight startup synchronization. Use automatically on every new/compacted session to summarize the current week and last work breakpoint, verify the last_dream probe, backfill up to three missed effective workdays through merak-dream, and remind about an unfinished Sunday work review.
---

# Merak Week Sync

Restore work orientation and verify that the off-line memory loop survived the previous night.

## Boundaries

- Read-only except when a missing dream triggers the N-level `merak-dream` backfill.
- Do not read episodic/semantic pools during a healthy startup.
- Do not edit `_本周.md`, LTM, or project files.
- Do not inspect MEMORY_LOG directly; use storage-agent only when probe/log consistency is disputed.

## Loading chain

**Upstream**: `AGENTS.md §B · 启动序列` step 5.

**Inputs**: `_本周.md`, `<ASSISTANT_ROOT>/MEMORY/last_dream.md`.

**Peers**: `merak-dream` for missed-date recovery; `merak-weekly-review` for Sunday work review.

## Startup workflow

### 1. Summarize the week

Read `_本周.md` task list and latest substantive progress date. Report:

- current week and weekday position
- checked/total task count, explicitly noting when ledger checkboxes lag real progress
- one-sentence latest progress summary

### 2. Verify the dream probe

Use `00.记忆区_agent.md §逻辑日期`.

```text
expected completed dream date = current logical date - 1 calendar day
```

Read `last_dream.md §完成探针`.

- Probe >= expected date: healthy; say nothing extra.
- Probe behind: identify missed dates and determine which are effective workdays from `_本周.md`/week archives.
- Probe missing or unparsable: treat as a failed probe, not proof that no dream ran.

### 3. Backfill missed dreams

When the probe is behind, invoke `merak-dream` oldest-first for at most the latest three missed effective workdays.

- Do not ask for permission: pool operations are N-level and this is the survival backstop.
- Never skip an earlier failed date and advance the probe past it.
- If more than three effective workdays are missing, process the latest allowed window and report the older accepted signal loss.
- If extraction or commit fails, leave the probe unchanged and report the exact failure.

At physical times before 06:00, the expected formula naturally points to the prior completed logical day. The normal automation waits until 06:10, after the `[06:00, next-day 06:00)` transcript window closes.

### 4. Check Sunday work review

Only on a Sunday logical date:

- If `_本周.md` already contains `### 本周产出`, do not remind.
- Otherwise say: `今天是周日，工作层周复盘还没完成。要现在开始吗？`

This reminder is for `merak-weekly-review`; Sunday memory consolidation remains the scheduled dream's job.

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
