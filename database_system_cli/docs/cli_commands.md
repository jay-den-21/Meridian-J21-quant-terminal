# CLI Commands

This file is the quick command reference for `database_system_cli`.

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
  --include-inactive
```
