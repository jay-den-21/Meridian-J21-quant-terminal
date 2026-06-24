# Progress

This file tracks implementation progress. `PROJECT.md` remains the project specification.

## Current Status

The project has a runnable, testable, and committable Python + Poetry scaffold.

Completed:

- Python package scaffold under `src/fdp`
- Poetry project metadata and dependency definitions
- CLI entrypoint through `poetry run fdp --help`
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
- `fdp ingest instruments --market US --source eodhd` command path
- Instrument ingestion service that parses, rejects unsupported/malformed rows, upserts valid rows, and records task/API summaries
- Unit tests for EODHD client URL construction, instrument row rejection, ingestion task logging, and CLI command registration
- `instrument_identifier_history` schema and migration for ticker/provider symbol history
- EODHD `symbol-change-history` client/parser and instrument rename reconcile before upsert
- Unit tests for symbol-change parsing, history upsert, and rename reconcile
- EODHD historical EOD client method for symbol-limited daily price pulls
- Daily price parser and OHLCV validation for `date/open/high/low/close/adjusted_close/volume`
- `fdp ingest history --symbols ... --from ... --to ...` command path
- Historical daily price ingestion service that looks up active instruments, calls EODHD, rejects invalid rows, upserts valid rows, and records task/API summaries
- Unit tests for historical EOD URL construction, daily price parsing, history ingestion, and CLI command registration
- Local MySQL migration applied through `0006_split_daily_tables`
- Real historical ingest smoke test: `AAPL,MSFT,SPY` from `2023-01-01` to `2024-01-01`, 750 rows inserted, 0 rows rejected, 0 duplicate `instrument_id + trade_date` groups
- Real 3-year stock/ETF historical ingest smoke test: `AAPL,MSFT,SPY` from `2023-01-01` to `2025-12-31`, 2256 rows inserted, 0 rows rejected, 0 duplicate `instrument_id + trade_date` groups across the 3 stock/ETF symbols and 4 benchmark indices
- EODHD `/symbol-change-history` access verified after plan upgrade: run_id 6 fetched 1062 rename rows, updated 44 existing instruments, and wrote 176 identifier-history rows
- EODHD index daily price ingestion through `fdp ingest indices`; real 3-year smoke test for `GSPC.INDX,DJI.INDX,IXIC.INDX,NDX.INDX` from `2023-01-01` to `2025-12-31` inserted 3009 rows with 0 rejected rows and 0 duplicate `instrument_id + trade_date` groups
- EODHD market calendar ingestion through `fdp ingest calendar`; latest real 3-year US calendar smoke test from `2023-01-01` to `2025-12-31` inserted 1096 calendar rows with 752 trading days and 344 non-trading days
- Unit tests for EODHD exchange-details client methods, market calendar parser/upsert, index daily ingest, market calendar ingest, and CLI command registration
- `market_calendar` early-close flag removed from v0.1 scope as a pseudo requirement; calendar keeps only trading-day semantics
- EODHD ingest workflows split into focused v0.1 modules under `sources/eodhd/ingest/`, with old `sources/eodhd/ingestion.py` kept as a compatibility facade
- v0.1 storage now keeps `instrument` as the only writable identity master, adds read-only `stock_instrument`/`etf_instrument`/`index_instrument` views, and writes new price ingest into `stock_daily_price`/`etf_daily_price`/`index_daily_price`
- `get_data/historical` wrappers now route stock, ETF, index, and market-calendar pulls through explicit reusable functions
- Data quality query builders now cover duplicate groups, missing trading-day rows, OHLCV constraints, and price rows on non-trading calendar dates
- Real post-split 3-year ingest smoke test: `AAPL,MSFT,SPY` from `2023-01-01` to `2025-12-31` wrote 2256 rows into split stock/ETF tables with 0 rejected rows
- Real post-split 3-year index ingest smoke test: `GSPC.INDX,DJI.INDX,IXIC.INDX,NDX.INDX` from `2023-01-01` to `2025-12-31` wrote 3009 rows into `index_daily_price` with 0 rejected rows
- Post-split DB verification found 0 duplicate `instrument_id + trade_date` groups in stock, ETF, and index price tables
- Known data-quality finding: `DJI.INDX` has one EODHD price row on `2024-12-25`, while `market_calendar` marks that date as non-trading; this should be recorded by the future validate workflow, not auto-corrected

Not started:

- `fdp validate` command that executes quality checks and writes `system.data_quality_check_run` / `system.data_quality_issue`
- ID mapping ingestion for CUSIP/ISIN/FIGI/LEI/CIK validation
- Repair plan workflow
- Database-backed access functions
- Real `fdp ingest daily`, `fdp validate`, and `fdp repair` subcommands

## Next Step

Start validate/access workflow:

- add independent `fdp validate daily-price` execution that records issues, including price rows on non-trading days
- add an explicit operator-controlled skip/manual-review path for future rename-history API outages
- add database-backed access functions for research reads
