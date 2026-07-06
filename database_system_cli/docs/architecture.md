# Data Core / Terminal Architecture

This document records the architecture boundary for `database_system_cli` and the future
data terminal. It is a decision document, not an implementation branch.

## Current Decision

Keep `database_system_cli` as the Data Core:

- MySQL remains the authoritative store for daily OHLCV, instruments, identifier history,
  task runs, API calls, quality issues, repair plans, and quarantine plans.
- Daily stock/ETF/index data continues to use normalized SQL tables because it needs
  constraints, joins, validation, repair, and auditability.
- The future data terminal should not mutate the Data Core tables directly.

For intraday bars, do not default to all-bars-in-MySQL:

- A 1-year 5-minute all-US-stock load is a bar store problem, not a relational OLTP
  problem.
- The recommended target is a split backend:
  - SQLite or MySQL catalog for instruments, datasets, partitions, and quality metadata.
  - Parquet files for high-volume bars such as `stk_price_5m`.
- MySQL can still be used for small smoke tests or selected high-value universes.

## Data Core Boundary

Data Core owns:

- provider adapters and API retry policy
- instrument identity and identifier history
- daily OHLCV storage
- market calendar
- ingestion run logs
- API call logs
- data quality issues
- human-confirmed repair/quarantine/dedupe workflows
- research read APIs that read stored data

Data Core must not own:

- chart rendering
- technical-indicator UI state
- backtest UI state
- terminal-specific watchlists, layouts, or dashboards
- speculative automatic vendor-data correction

## Terminal Boundary

The future data terminal should consume Data Core through stable read APIs or exported
datasets. It may own:

- charting
- technical indicators
- backtest orchestration
- local cache indexes
- user watchlists
- UI state

It should treat Data Core as source-of-truth metadata plus validated datasets, not as a
scratch database for interface behavior.

## Daily Historical Load

Goal: 15 years of US stock daily data.

Recommended path:

1. Run `instrument` ingest first, including symbol-change-history reconciliation.
2. Use current `instrument_id` as the immutable identity key.
3. Pull historical daily data by provider symbol, with bounded parallelism.
4. Write to `stock_daily_price` with `instrument_id + trade_date` uniqueness.
5. Validate duplicate, missing, OHLCV, and calendar issues after each batch.

Do not use Bulk EOD to backfill 15 years by date unless there is a specific reason.
EODHD documents Bulk whole-exchange requests as 100 API call units per request. A
15-year trading-day loop would consume roughly `15 * 252 * 100 = 378,000` call units,
before retries. Per-symbol historical EOD requests are usually more call-efficient for
one-time backfill.

Operational guardrails:

- Bound request rate below EODHD's documented 1000 requests/minute ceiling.
- Use retry with explicit wait on transient HTTP/network failures.
- Keep an API-call budget per run.
- Split a full-market 15-year run into batches by instrument id or provider symbol.
- Record run ids and data-quality validation after every batch.

## Symbol-Change Verification

The expected `FB -> META` behavior is:

- `instrument.instrument_id` remains stable.
- `instrument.symbol` and `instrument.provider_symbol` use the current standard values.
- `instrument_identifier_history` records the old and new ticker/provider-symbol values
  with validity windows and source.
- Newly written `stock_daily_price.symbol` uses the current standard symbol.
- Historical identity is recovered through `instrument_identifier_history`, not by
  creating a second instrument row.

This only proves current active-instrument continuity. It is not survivorship-bias-free
until delisted/inactive instruments and point-in-time universe membership are added.

## Intraday 5-Minute Load

Goal: 1 year of 5-minute bars.

EODHD's Intraday API supports intervals including `5m`, and the documentation says
`5m`/`1h` intervals have a maximum request range of 600 days. EODHD also documents that
each Intraday request consumes 5 API call units.

Recommended path:

1. Start with a smoke universe, for example `SPY`, `QQQ`, `AAPL`, `MSFT`, `META`.
2. Add explicit intraday tables or a Parquet bar store before all-market ingestion.
3. Store timestamps with provider timezone semantics documented at ingest time.
4. Validate row counts, duplicate timestamps, and obvious OHLCV errors.
5. Only then scale beyond the smoke universe.

Do not load all active US stocks into MySQL 5-minute tables by default. Even if API
budget is acceptable, the resulting row count can be hundreds of millions of rows for
one year depending on session coverage. That should be a Parquet-bar-store workload.

## Backend Recommendation

Use a two-layer backend:

```text
Data Core metadata and daily bars:
  MySQL

High-volume intraday bars:
  Parquet partitioned by asset_type / interval / year / symbol or instrument_id

Optional local catalog for terminal:
  SQLite
```

Rationale:

- MySQL is correct for constrained relational metadata and audited daily data.
- Parquet is correct for wide scans, chart windows, backtest reads, and bulk bars.
- SQLite is useful as a portable terminal catalog but should not replace the Data Core
  source-of-truth database.

## Config And Alembic Alignment

Current baseline:

- `.env.example` supports `FDP_DATABASE_URL` and individual MySQL fields.
- `alembic/env.py` already reads SQLAlchemy URL through `fdp.config.database_url_from_env()`.
- `pyproject.toml` still exposes `fdp = "fdp.cli:app"` as the CLI entrypoint.

Follow-up alignment:

- If the user-facing command is standardized as `poetry run j21 ...`, add a new script
  alias while keeping `fdp` temporarily for backwards compatibility.
- Keep retry/rate/budget settings in config and `.env.example` once the parallel-ingest
  branch is merged.
- Do not add Parquet dependencies until the intraday storage branch is implemented.

## References

- EODHD API limits: <https://eodhd.com/financial-apis/api-limits>
- EODHD Bulk API: <https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends>
- EODHD Intraday API: <https://eodhd.com/financial-apis/intraday-historical-data-api>
