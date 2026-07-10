# CLI Commands

This file is the quick command reference for `database_system_cli`.

## Two Equivalent Ingest Entry Points

For a human-operated, bilingual arrow-key workflow:

```bash
poetry run j21 menu
```

For scripts, AI tools, reproducible notes, and automation:

```bash
poetry run j21 ingest --help
```

Both routes call the same `fdp.get_data` Jobs. The menu does not start a shell
subprocess. Before execution it shows the resolved parameters, their sources,
target tables, API/storage estimate, Job module, and an equivalent CLI command.
Confirmation defaults to **No**.

All migrated ingest commands support `--output text|json`. JSON mode emits one
versioned `JobResult` on stdout and sends progress events to stderr:

```bash
poetry run j21 ingest daily --market US --date 2026-07-07 --output json
```

## Instrument Master

Refresh active instruments and identifier history:

```bash
poetry run j21 ingest instruments --market US
```

The command uses EODHD symbol-change history before the current exchange list.
It writes canonical instruments and identifier history; it does not guess rename
relationships.

## Historical Stock And ETF EOD

Load a small explicit symbol set:

```bash
poetry run j21 ingest history \
  --symbols AAPL,MSFT,SPY \
  --asset-types stock,etf \
  --from 2024-01-01 \
  --to 2024-01-31 \
  --instrument-status active
```

`--symbols` accepts canonical symbols such as `AAPL` and provider symbols such
as `AAPL.US`; lookup is performed through the instrument master. Use
`--instrument-status inactive` to fetch only inactive/delisted symbols, or
`all` for both. Empty symbols are rejected because full-universe history should
use Bulk EOD.

Each symbol is committed independently under one aggregate task run. An isolated
404/no-data symbol is recorded and the batch continues. Authentication,
entitlement, database, or repeated global transient failures stop later symbols.

## Index And Calendar

```bash
poetry run j21 ingest indices \
  --provider-symbols GSPC.INDX,DJI.INDX,IXIC.INDX,NDX.INDX \
  --from 2024-01-01 \
  --to 2024-12-31

poetry run j21 ingest calendar --market US --from 2024-01-01 --to 2024-12-31
```

## One-Day Bulk EOD

```bash
poetry run j21 ingest daily \
  --market US \
  --date 2026-07-07 \
  --asset-types stock,etf
```

Matched rows enter the canonical split price tables. Unmatched provider rows are
retained in `system.bulk_unmatched_daily_price_observation` for later
classification and routing.

## Daily Range Bulk EOD

Estimate a date range before writing:

```bash
poetry run j21 ingest daily-range --from 2024-01-01 --to 2024-01-31 --dry-run
```

Execute after reviewing the estimate:

```bash
poetry run j21 ingest daily-range \
  --from 2024-01-01 \
  --to 2024-01-31 \
  --execute \
  --yes \
  --parallel \
  --workers 4
```

Large API-consuming `daily-range --execute --yes` runs default to user-operated CLI execution.
Codex/AI should prepare the command and then verify database state after the user runs it.

Relevant controls:

- `--parallel/--sequential`: enable or disable bounded per-day parallel ingestion.
- `--workers`: worker count when parallel mode is enabled.
- `--max-requests-per-minute`: request-rate throttle; must be at or below EODHD's 1000 requests/minute ceiling.
- `--max-api-calls`: daily-range API-call budget guard.
- `--max-estimated-gb`: storage estimate guard.

Runtime defaults live in `config/default.yaml` and can be overridden with:

- `EODHD_MAX_RETRIES`
- `EODHD_RETRY_DELAY_SECONDS`
- `EODHD_MAX_REQUESTS_PER_MINUTE`
- `EODHD_DAILY_CALL_BUDGET`
- `EODHD_DAILY_RANGE_PARALLEL`
- `EODHD_DAILY_RANGE_MAX_WORKERS`

## Delisted Instruments

Load EODHD inactive/delisted stock+ETF universe:

```bash
poetry run j21 ingest delisted-instruments --market US
```

This writes inactive instruments to `us_share.instrument` and records delisting facts in
`us_share.instrument_lifecycle_event`. It is idempotent and does not backfill all
delisted historical prices by default. The current EODHD delisted symbol list does not
return a delisting date, so `instrument.delisted_date` can remain `NULL` until another
source supplies that date.

Run a small inactive-symbol historical price smoke test only when explicitly needed:

```bash
poetry run j21 ingest history \
  --market US \
  --symbols TWTR.US \
  --from 2022-10-20 \
  --to 2022-10-28 \
  --instrument-status inactive
```

Compatibility note: `--include-inactive` is still accepted and means
`--instrument-status all`. Use `inactive` when you only want delisted/inactive
symbols and want to avoid spending API calls on active instruments.

## Bulk Unmatched Workflow

`j21 ingest daily` and `j21 ingest daily-range` first write matched stock/ETF
rows into split daily price tables. Bulk EOD rows that cannot match the current
instrument universe are stored in `system.bulk_unmatched_daily_price_observation`
instead of being discarded.

Inspect unmatched rows:

```bash
poetry run j21 research bulk-unmatched summary --from 2024-01-01 --to 2024-01-31
poetry run j21 research bulk-unmatched list --from 2024-01-01 --to 2024-01-31 --status unresolved
```

Classify unresolved rows with strict provider-symbol matching:

```bash
poetry run j21 research bulk-unmatched classify --from 2024-01-01 --to 2024-01-31
```

Preview routeable high-confidence rows:

```bash
poetry run j21 ingest bulk-unmatched-route --from 2024-01-01 --to 2024-01-31 --dry-run
```

Execute only after reviewing the preview:

```bash
poetry run j21 ingest bulk-unmatched-route --from 2024-01-01 --to 2024-01-31 --execute --yes
```

Routing only writes rows that strictly matched an existing stock/ETF/index
`instrument_id`. Fund, preferred, notes, and unknown rows remain in staging for
later review or schema expansion.
