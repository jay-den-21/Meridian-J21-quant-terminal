# Progress

This file tracks implementation progress for `database_system_cli`. `PROJECT.md` remains the project specification.

## Current Status

The project has a runnable, testable, and committable Python + Poetry scaffold.

Completed:

- Python package scaffold under `src/fdp`
- Poetry project metadata and dependency definitions
- CLI entrypoint through `poetry run j21 --help`; `fdp` remains as a temporary compatibility alias
- Configuration templates through `.env.example` and `config/default.yaml`
- Alembic scaffold with an empty `versions/` directory
- Smoke test scaffold under `tests/`
- README quickstart for setup, build, test, CLI, and configuration
- Initial SQLAlchemy table definitions for `us_share` and `system`
- Initial Alembic migration for platform schemas and core tables
- First EODHD instrument parser slice for active stock/ETF rows
- MySQL upsert statement builders for `instrument`, legacy `daily_price`, and split stock/ETF/index daily price tables
- Unit tests for metadata, EODHD symbol parsing, and upsert SQL generation
- EODHD Exchange Symbols client with API call summary fields
- `j21 ingest instruments --market US --source eodhd` command path
- Instrument ingestion service that parses, rejects unsupported/malformed rows, upserts valid rows, and records task/API summaries
- Unit tests for EODHD client URL construction, instrument row rejection, ingestion task logging, and CLI command registration
- `instrument_identifier_history` schema and migration for ticker/provider symbol history
- EODHD `symbol-change-history` client/parser and instrument rename reconcile before upsert
- Unit tests for symbol-change parsing, history upsert, and rename reconcile
- EODHD historical EOD client method for symbol-limited daily price pulls
- Daily price parser and OHLCV validation for `date/open/high/low/close/adjusted_close/volume`
- `j21 ingest history --symbols ... --from ... --to ...` command path
- Historical daily price ingestion service that looks up active instruments, calls EODHD, rejects invalid rows, upserts valid rows, and records task/API summaries
- Unit tests for historical EOD URL construction, daily price parsing, history ingestion, and CLI command registration
- Local MySQL migration applied through `0006_split_daily_tables`
- Real historical ingest smoke test: `AAPL,MSFT,SPY` from `2023-01-01` to `2024-01-01`, 750 rows inserted, 0 rows rejected, 0 duplicate `instrument_id + trade_date` groups
- Real 3-year stock/ETF historical ingest smoke test: `AAPL,MSFT,SPY` from `2023-01-01` to `2025-12-31`, 2256 rows inserted, 0 rows rejected, 0 duplicate `instrument_id + trade_date` groups across the 3 stock/ETF symbols and 4 benchmark indices
- EODHD `/symbol-change-history` access verified after plan upgrade: run_id 6 fetched 1062 rename rows, updated 44 existing instruments, and wrote 176 identifier-history rows
- EODHD index daily price ingestion through `j21 ingest indices`; real 3-year smoke test for `GSPC.INDX,DJI.INDX,IXIC.INDX,NDX.INDX` from `2023-01-01` to `2025-12-31` inserted 3009 rows with 0 rejected rows and 0 duplicate `instrument_id + trade_date` groups
- EODHD market calendar ingestion through `j21 ingest calendar`; latest real 3-year US calendar smoke test from `2023-01-01` to `2025-12-31` inserted 1096 calendar rows with 752 trading days and 344 non-trading days
- Unit tests for EODHD exchange-details client methods, market calendar parser/upsert, index daily ingest, market calendar ingest, and CLI command registration
- `market_calendar` early-close flag removed from v0.1 scope as a pseudo requirement; calendar keeps only trading-day semantics
- EODHD ingest workflows split into focused v0.1 modules under `sources/eodhd/ingest/`, with old `sources/eodhd/ingestion.py` kept as a compatibility facade
- v0.1 storage now keeps `instrument` as the only writable identity master, adds read-only `stock_instrument`/`etf_instrument`/`index_instrument` views, and writes new price ingest into `stock_daily_price`/`etf_daily_price`/`index_daily_price`
- `get_data/historical` wrappers now route stock, ETF, index, and market-calendar pulls through explicit reusable functions
- Data quality query builders now cover duplicate groups, missing trading-day rows, OHLCV constraints, and price rows on non-trading calendar dates
- Operator-confirmed repair workflow added for missing daily-price issues: `repair plan-daily-price`, `repair list`, `repair confirm`, and `repair run` create/preview/confirm/execute backfill plans against existing `system.repair_plan`
- Repair execution backfills by immutable `instrument_id`, not by ticker guessing, and only marks the linked `data_quality_issue` resolved after the target daily-price row exists
- Repair workflow hardened after adversarial review: logical duplicate missing issues share one active plan, stale provider symbols are rejected before API calls, and confirmed plans are claimed as `executing` before external backfill starts
- Operator-confirmed quarantine workflow added for bad existing daily-price rows: `system.quarantine_plan`, `system.quarantined_daily_price_row`, and `j21 quarantine plan-daily-price/list/confirm/run`
- Quarantine execution archives source row payload/hash before deleting rows for `invalid_ohlcv` and `price_on_non_trading_day`, then resolves the linked `data_quality_issue` only after post-action verification
- Quarantine workflow hardened after adversarial review: confirm/run previews source rows, execution claims the plan, locks source rows, checks actual delete rowcount, and refuses to silently resolve stale non-trading issues while rows remain
- Operator-confirmed dedupe workflow added for `duplicate_key` daily-price groups: exact duplicate payloads are deduped through the quarantine archive/delete path, while conflicting duplicate payloads are rejected for manual review
- EODHD API calls now use a centralized retry/progress policy: up to 5 retries, default 61-second waits, retryable transient status/network failures, and CLI-visible `request`/`retrying`/`success`/`failed` messages without printing API tokens
- `j21 validate daily-price` command now executes duplicate, missing loaded trading-day row, OHLCV, and non-trading-day price checks, then writes `system.data_quality_check_run` and `system.data_quality_issue`
- Database-backed research read layer added through `fdp.research.DailyPriceReader`, with method-level dates overriding reader defaults and strict `ValueError` behavior for missing or partial date ranges
- `j21 research daily-prices` command added as a thin CLI wrapper around the Python research reader
- EODHD Bulk EOD endpoint wrapped through `EodhdClient.get_bulk_eod(...)`
- `j21 ingest daily` added as the bulk daily update path: one EODHD bulk request, active stock/ETF instrument matching, OHLCV validation, split-table upsert, and task/API audit logging
- `j21 ingest daily-range` added as a guarded multi-day Bulk EOD path: dry-run by default, `--execute --yes` gated writes, per-day transactions, optional bounded parallel workers, request-rate throttling, and pre-run API-call/storage budget checks
- Real active stock+ETF daily bulk backfill completed for `2018-08-01` to `2022-07-07`: 990 trading days, 49,201,725 rows fetched, 31,612,511 rows inserted, 17,589,214 unmatched active-universe rows rejected, 990 HTTP requests, 99,000 estimated API-call cost, and 0 failed days
- Post-backfill DB verification passed: `stock_daily_price` and `etf_daily_price` both cover all 990 trading days in `2018-08-01..2022-07-07`, with 0 duplicate `(instrument_id, trade_date)` groups and no missing trading-day sample
- Full MySQL backup created after the active bulk run and before delisted rerun: `/private/tmp/j21-daily-backfill-delisted/backups/j21_mysql_contains-delisted_pre-delisted-rerun_20260707_035632.sql.gz`; name is explicit because the live DB already contained inactive/delisted rows
- EODHD delisted/inactive universe workflow added through `j21 ingest delisted-instruments --market US`; idempotent rerun fetched 58,322 rows, accepted 53,645 stock/ETF/fund rows, rejected 4,677 unsupported/malformed rows, and left lifecycle duplicate keys at 0
- Real EODHD delisted-symbol-list payload does not include a delisting date field, so the workflow can reliably set `instrument.is_active = false` and write lifecycle events, but `instrument.delisted_date` remains `NULL` unless a later source supplies a date
- Inactive history smoke test passed: `j21 ingest history --symbols TWTR.US --from 2022-10-20 --to 2022-10-28 --include-inactive` fetched and inserted 6 `stock_daily_price` rows with `instrument.is_active = false`
- Legacy `us_share.daily_price` was removed after verification: it had 5,265 rows and only one row not already represented in split tables, the known bad holiday row `DJI.INDX` on `2024-12-25`
- Live DB Alembic version was reconciled from the older dirty-workflow revision `0022_quarantine` back onto the clean migration chain, then upgraded through `0009_bulk_unmatched`.
- EODHD runtime knobs added to `config/default.yaml` / `.env.example`: max retries, retry delay, request rate, daily API-call budget, daily-range parallel flag, and worker count
- Documentation workflow rule added to `AGENTS.md`: when human-facing Markdown docs are updated, matching HTML docs and the `PROGRESS.md` board must be kept in sync when applicable
- `PROJECT.md` / `PROJECT.html` audience rule documented: Markdown is the Codex/AI-facing specification source, while HTML is the shared readable board for user and Codex/AI
- User-operated ingest workflow rule added to root and subproject `AGENTS.md`: small smoke tests and read-only validation can be run by Codex/AI, while large API-consuming ingest defaults to user-operated CLI execution unless explicitly delegated
- `j21 ingest history` now supports `--instrument-status active|inactive|all`; legacy `--include-inactive` remains compatible as `all`, and conflicting new/old flags are rejected
- Bulk EOD unmatched staging added through Alembic `0009_bulk_unmatched`: unmatched rows are stored in `system.bulk_unmatched_daily_price_observation` with raw payload, OHLCV fields, classification status, and exact-match routing metadata
- `j21 ingest daily` now writes unmatched Bulk EOD rows into the system staging table instead of only counting them as rejected
- Bulk unmatched review/classification CLI added: `j21 research bulk-unmatched summary/list/classify`
- Bulk unmatched routing CLI added: `j21 ingest bulk-unmatched-route --dry-run` previews matched rows, while `--execute --yes` writes high-confidence stock/ETF/index rows to split daily price tables
- Focused verification for the bulk unmatched workflow passed: storage schema/upsert, CLI registration/conflict behavior, EODHD ingest, and classifier/route tests passed with 54 targeted tests; focused ruff checks passed
- `app_log` snapshot schema cleanup added through Alembic `0010_app_log_snapshots` and `0011_drop_us_share_snapshots`: API playground/search/screener/quote/live/websocket snapshots are copied out of `us_share`, verified by count, and legacy `us_share` snapshot tables are dropped so `us_share` stays focused on canonical market data and instrument master data
- Real post-split 3-year ingest smoke test: `AAPL,MSFT,SPY` from `2023-01-01` to `2025-12-31` wrote 2256 rows into split stock/ETF tables with 0 rejected rows
- Real post-split 3-year index ingest smoke test: `GSPC.INDX,DJI.INDX,IXIC.INDX,NDX.INDX` from `2023-01-01` to `2025-12-31` wrote 3009 rows into `index_daily_price` with 0 rejected rows
- Post-split DB verification found 0 duplicate `instrument_id + trade_date` groups in stock, ETF, and index price tables
- Resolved one vendor data-quality issue manually after EODHD fixed the source data: deleted stale `DJI.INDX` `2024-12-25` row from `index_daily_price`; all four benchmark indices now have 752 rows for `2023-01-01` to `2025-12-31`, and verified non-trading index price rows are 0
- Real validate smoke test: `j21 validate daily-price --from 2023-01-01 --to 2025-12-31 --asset-types stock,etf,index` completed with 0 issues and wrote check runs for stock, ETF, and index price tables
- Repository layout migrated so the database CLI system now lives under `financial-data-platform/database_system_cli/`; project docs, source, tests, Alembic migrations, and config moved together, while the repository root is reserved for the future app
- `docs/architecture.md` added to record the Data Core / Terminal boundary, MySQL daily-data decision, Parquet recommendation for high-volume intraday bars, and large-run guardrails for 15-year daily / 1-year 5m loads
- Shared `fdp.get_data` Job layer added for instrument, historical stock/ETF/index, calendar, Bulk EOD, daily-range, and Bulk unmatched workflows; CLI, terminal menu, and direct Python callers now share parameter resolution, preflight, runtime, progress, and structured result contracts
- `j21 menu` added as a bilingual Chinese/English arrow-key terminal workflow with basic/advanced prompts, target-table/API/storage preflight, equivalent CLI preview, default-cancel confirmation, and `tqdm` progress
- Typer ingest commands now invoke the shared Jobs and support `--output text|json`; JSON stdout is a single versioned result object while operational progress is routed to stderr
- Historical stock/ETF Job execution now resolves canonical/provider symbols through the instrument master, commits each symbol independently under one aggregate task run, preserves completed work on cancellation/failure, and stops on fatal auth/entitlement, DB, or repeated global transient failures
- Terminal menu and shared Job verification covers non-TTY rejection, default-cancel behavior, JSON output, parameter precedence, API-budget preflight, isolated symbol failure, fatal stop, and parent-run finalization
- Shared Job/menu quality gate passes 136 tests plus Ruff/compileall; a real-DB `daily-range --dry-run` for `2024-01-02` resolved 1 trading day, 45,848 estimated rows, 0.03 GB, and 100 estimated API-call cost without calling EODHD or writing data
- Scoped maintainer/agent context is now defined at the docs, shared Job, terminal menu, EODHD provider, storage, Alembic, quality, repair, quarantine, and research boundaries; parent `AGENTS.md` files provide deterministic routing, and `docs/architecture.md/.html` trace the current executable flows with Mermaid diagrams and exact code paths

Not started:

- ID mapping ingestion for CUSIP/ISIN/FIGI/LEI/CIK validation

## Next Step

- add an explicit operator-controlled skip/manual-review path for future rename-history API outages
- decide the next delisted-date source: EODHD Fundamentals/Corporate Actions, Nasdaq/FINRA lists, or manual enrichment, because the EODHD delisted symbol list does not expose delist dates
- plan point-in-time universe membership so active-only backtests can be clearly separated from survivorship-bias-aware research
- extend delisted historical backfill in small, budgeted batches after date-source and universe policy are settled
- run a small real-date smoke after applying migration `0009_bulk_unmatched`: one-day `j21 ingest daily --date ...`, then `bulk-unmatched summary/list/classify`, dry-run route, and `validate daily-price`
- after small smoke passes, user can run larger `daily-range`; Codex/AI should verify row counts, duplicate `(instrument_id, trade_date)`, unmatched status distribution, and route candidates after the user-run ingest
- use `poetry run j21 menu` for the next user-operated small ingest smoke, review its preflight/equivalent command, then compare the resulting `ingestion_task_run` with the same deterministic CLI workflow
