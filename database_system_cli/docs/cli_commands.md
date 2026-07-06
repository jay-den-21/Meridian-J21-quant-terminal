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
