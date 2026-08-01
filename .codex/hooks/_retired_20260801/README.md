# Retired hooks · 2026-08-01

These two hooks are kept for migration forensics only. They are **not registered** in
`config.toml` and must not be re-registered.

## `session_end.py`

Matched goodbye phrases (`晚安` / `今天就到这儿` / `收工`) and injected "call the full
daily-dream flow first".

Retired because consolidation moved off the goodbye and onto the OS schedule. Parting no
longer consolidates: the day's work stays in the session transcript overnight (the
transcript **is** the L0 source), and the scheduled run at day-boundary + 30 minutes
processes the just-closed logical day.

The goodbye trigger had a failure mode that could not be fixed in place — it ran while the
user was still present and mid-day work was still open, so it either consolidated an
unfinished day or consolidated nothing and left the user believing it had run. A schedule
that fires after the window closes has neither problem.

## `session_context_check.py`

Per-message context routing. Superseded by `thinking_protocol.py` plus the routing table in
`AGENTS.md §R`. Two hooks writing routing hints per message meant the effective route
depended on their relative order, which nothing enforced.

## Active hook inventory

The registered set is exactly three, whitelist-managed — an unregistered script in
`hooks/` is drift:

| hook | event | job |
|---|---|---|
| `timesense.py` | UserPromptSubmit | inject real current time |
| `thinking_protocol.py` | UserPromptSubmit | inject the thinking protocol |
| `session_start.py` | SessionStart (compact) | re-inject the identity layer |
