# financial-data-platform v0.0 Baseline

This file freezes the v0.0 project state before the v0.1 structural refactor.

## Scope

- Provider: EODHD paid API.
- Market: US.
- Database: local MySQL.
- Schemas: `us_share`, `a_share`, `system`.
- Main implemented workflows:
  - active US stock/ETF instrument ingest,
  - EODHD symbol-change-history reconciliation,
  - symbol-limited stock/ETF historical daily OHLCV ingest,
  - benchmark index historical daily OHLCV ingest,
  - US market calendar ingest,
  - task/API logging in `system`.

## v0.0 Tables

- `us_share.instrument`
- `us_share.instrument_identifier_history`
- `us_share.daily_price`
- `us_share.market_calendar`
- `system.ingestion_task_run`
- `system.api_call_log`
- `system.data_quality_check_run`
- `system.data_quality_issue`
- `system.repair_plan`

## v0.0 Design Notes

- `instrument_id` is the identity key.
- `symbol` and `provider_symbol` are retained for query convenience and provider audit.
- `instrument_identifier_history` stores ticker/provider-symbol changes.
- `daily_price` uses `unique(instrument_id, trade_date)` for idempotent writes.
- `daily_price` held stock, ETF, and index daily rows in v0.0.
- v0.1 will split data access and storage boundaries more explicitly.

## Verified Smoke Tests

- `AAPL.US`, `MSFT.US`, `SPY.US`: 3-year daily history, 2023-01-01 to 2025-12-31.
- `GSPC.INDX`, `DJI.INDX`, `IXIC.INDX`, `NDX.INDX`: 3-year daily index history.
- US market calendar: 2023-01-01 to 2025-12-31.
