# database_system_cli

`database_system_cli` is the database CLI subproject inside `financial-data-platform`.
It is a traceable and verifiable financial data platform focused on US equity EOD data ingestion, validation, repair planning, and research reads.

`PROJECT.md` is the project specification. `PROGRESS.md` tracks implementation status.
This README is the quickstart for local development.

Architecture notes:

- `docs/architecture.md` records the Data Core / Terminal boundary and backend decision
  path for MySQL daily data versus future intraday bar storage.

## Development Setup

Install Poetry if it is not already available:

```bash
brew install pipx
pipx ensurepath
pipx install poetry
```

After installing Poetry, reopen the terminal or reload your shell, then verify:

```bash
poetry --version
```

Install project dependencies from the `database_system_cli/` directory:

```bash
poetry install
```

## Build And Test

Run the test suite:

```bash
poetry run pytest
```

Run the CLI entrypoint:

```bash
poetry run j21 --help
```

Estimate a multi-day EODHD Bulk EOD range before writing:

```bash
poetry run j21 ingest daily-range --from 2024-01-01 --to 2024-01-31 --dry-run
```

Execute with bounded per-day parallelism after reviewing the estimate:

```bash
poetry run j21 ingest daily-range --from 2024-01-01 --to 2024-01-31 --execute --yes --parallel --workers 4
```

Create and review missing daily-price repair plans:

```bash
poetry run j21 repair plan-daily-price --from 2024-01-01 --to 2024-01-31
poetry run j21 repair list --status pending_confirmation
poetry run j21 repair confirm --plan-id 123 --yes
poetry run j21 repair run --plan-id 123 --yes
```

Create and review bad-row quarantine/dedupe plans:

```bash
poetry run j21 quarantine plan-daily-price --from 2024-01-01 --to 2024-01-31 --issue-types duplicate_key,invalid_ohlcv,price_on_non_trading_day
poetry run j21 quarantine list --status pending_confirmation
poetry run j21 quarantine confirm --plan-id 456 --yes
poetry run j21 quarantine run --plan-id 456 --yes
```

`j21` is the user-facing CLI name. `fdp` remains available as a temporary
compatibility alias for older notes and scripts.

## Configuration

Copy the environment template before adding local secrets:

```bash
cp .env.example .env
```

Do not commit `.env`, API keys, database passwords, tokens, or private keys.

EODHD runtime controls are configured in `config/default.yaml` and can be overridden with
environment variables:

- `EODHD_MAX_RETRIES`
- `EODHD_RETRY_DELAY_SECONDS`
- `EODHD_MAX_REQUESTS_PER_MINUTE`
- `EODHD_DAILY_CALL_BUDGET`
- `EODHD_DAILY_RANGE_PARALLEL`
- `EODHD_DAILY_RANGE_MAX_WORKERS`
