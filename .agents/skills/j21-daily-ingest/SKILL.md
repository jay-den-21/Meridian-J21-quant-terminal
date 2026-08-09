---
name: j21-daily-ingest
description: Safely plan, execute, resume, and inspect Meridian J21 EODHD Bulk Daily tasks through CLI or MCP.
---

# J21 Daily Ingest

Use this skill when an operator asks to load one or more US Daily Bulk dates,
continue an interrupted task, inspect a checkpoint, or explain API cost.

## Required sequence

1. Read `database_system_cli/AGENTS.md` and the CLI tutorial.
2. Run preflight first. Report resolved dates, trading-day count, prerequisite
   refreshes, estimated API units, target tables, and storage estimate.
3. Do not execute unless the operator explicitly authorizes real provider calls.
4. Prefer the default auto-resume behavior. Use `--new-run` only when the operator
   explicitly wants to ignore verified reusable dates.
5. Keep automatic classify/route/validate enabled unless `--manual` is requested.
6. After execution, report `run_id`, work-unit counts, API units, published/pending
   rows, and `review_required`.

## CLI

```bash
poetry run j21 ingest daily-range \
  --from YYYY-MM-DD --to YYYY-MM-DD \
  --instrument-status all

poetry run j21 ingest daily-range \
  --from YYYY-MM-DD --to YYYY-MM-DD \
  --instrument-status all --execute --yes

poetry run j21 task list
poetry run j21 task status --run-id RUN_ID
```

Running the same immutable scope resumes an incomplete task or returns the prior
completed result without provider calls. `--new-run` forces a fresh task.

## MCP

Read tools are safe by default: `daily_preflight`, `daily_range_preflight`,
`task_list`, and `task_status`.

`daily_range_execute` is blocked unless the MCP server has
`J21_MCP_ENABLE_WRITES=1` and the call includes `confirm_execute=true`. Never ask
for or expose an API key, database URL, `.env`, or token in tool output.
