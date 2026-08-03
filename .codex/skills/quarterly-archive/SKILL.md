---
name: quarterly-archive
description: Detect or execute a quarterly archive for an explicitly named Sunday. Use detect mode when weekly-dream reaches a quarter point or the user asks whether a quarter is due. Use execute mode only after the user explicitly authorizes the archive in the current session. Require --mode and --date; never infer them or upgrade detect to execute.
---

# Quarterly Archive

`detect` evaluates and inventories; `execute` moves the inventoried ranges. Quarterly archive execution is C-level. The automatic night chain always stops at detect.

## Step 1 · Validate parameters and execution authority

Require `--date YYYY-MM-DD --mode detect|execute`; the date must be Sunday.

For execute, also require both the user's explicit archive authorization in the current human session and a matching quarter-archive pending item in the current-state authority file. A historical pending item is not current authorization; current authorization does not replace the detected inventory.

Any failure is a zero-write REJECT.

## Step 2 · Recompute the quarter point

Report separately:

- whether target Sunday plus seven days crosses quarter/year;
- unarchived weekly-section count since the previous quarterly archive;
- their OR result `quarter_point`.

False in detect mode is a normal zero-write completion. False in execute mode rejects a stale request.

## Step 3 · Detect mode: inventory and propose

Ask storage-agent to inventory, without moving content:

- the target quarter's detailed weekly-record sections;
- Focus Zone weekly archive files already present;
- target-quarter MEMORY_LOG entries and all currently dormant episodic rows.

Preserve the other two counts when one zone cannot be scanned, and name the failure. At a true quarter point, append one idempotent pending proposal containing the quarter and three counts. Create no archive file and remove no source content.

## Step 4 · Execute mode: move three zones in order

For each zone, create and verify the target before removing the source range:

1. move the quarter's weekly sections to the LTM archive and leave one pointer;
2. verify Focus weekly files are present; report missing weeks rather than inventing them;
3. move quarter MEMORY_LOG entries through storage-agent, verify strict UTF-8 and U+FFFD=0, then clear only rows still dormant at execution time.

Archive means move plus pointer, not copy or backup. Never delete an archive file. Stop before the next source deletion on a size, encoding, or load-chain failure.

## Step 5 · Verify, log, and clear pending state

Verify load-chain reachability, moved counts, source/target ranges, and dormant before/after counts. Finalize the archive log payload and send it to storage-agent. Remove only the matching pending item after every receipt passes.

## Boundaries

- Detect never executes; execute never accepts an unattended caller.
- Never infer date or mode, alter scheduling, or advance the daily probe.
- Never delete archive files or modify identity/runtime layers.
- Never read or write MEMORY_LOG/ITERATION_LOG directly.
