# v0.0 Progress Snapshot

This snapshot records the completed state before the v0.1 refactor.

## Completed

- Python/Poetry package scaffold.
- Typer CLI entrypoint.
- SQLAlchemy Core table definitions.
- Alembic migrations through `0004_simplify_market_calendar`.
- EODHD active instrument ingest.
- EODHD symbol-change-history access and reconciliation.
- `instrument_identifier_history` table and upsert path.
- Historical daily OHLCV ingest for selected stocks/ETFs.
- Historical daily OHLCV ingest for selected benchmark indices.
- Market calendar ingest based on EODHD exchange details.
- MySQL upsert builders for instrument, identifier history, daily price, and calendar rows.
- Task/API audit logging in `system.ingestion_task_run` and `system.api_call_log`.

## Last Verified Data

- Stock/ETF 3-year smoke test:
  - `AAPL.US`, `MSFT.US`, `SPY.US`
  - 2023-01-01 to 2025-12-31
  - 2256 rows inserted
  - 0 rejected rows
- Index 3-year smoke test:
  - `GSPC.INDX`, `DJI.INDX`, `IXIC.INDX`, `NDX.INDX`
  - 2023-01-01 to 2025-12-31
  - 3009 rows inserted
  - 0 rejected rows
- Market calendar smoke test:
  - 2023-01-01 to 2025-12-31
  - 1096 calendar rows
  - 752 trading days
  - 344 non-trading days

## v0.1 Direction

- Remove early-close logic from market calendar.
- Restructure ingestion code into provider/data-access/quality folders.
- Add reusable `get_data/historical/get_*.py` scripts.
- Split mixed price storage boundaries after schema decision.
