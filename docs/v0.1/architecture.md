# v0.1 Architecture Plan

v0.1 reorganizes the project from a small ingest prototype into clearer layers:
provider adapters, storage, data quality, and reusable data-get scripts.

## Target Package Layout

```text
src/fdp/
  cli.py
  config.py

  sources/
    eodhd/
      client.py
      instruments.py
      prices.py
      calendar.py
      ingestion.py  # compatibility facade
      ingest/
        instruments.py
        daily.py
        calendar.py
        common.py
        models.py

  storage/
    schema.py
    tables.py
    upsert.py

  quality/
    checks/
      duplicate.py
      missing.py
      ohlcv.py

  get_data/
    historical/
      get_stk_daily.py
      get_etf_daily.py
      get_index_daily.py
      get_market_calendar.py
    realtime/
      __init__.py
```

## Current v0.1 Decisions

- `market_calendar` keeps only trading-day semantics.
- `early_close` is removed as a pseudo requirement.
- Historical data is the current priority.
- Realtime data keeps an empty namespace until a concrete source/endpoint is selected.
- Data quality checks live under `quality/checks`.
- User-facing reusable scripts live under `get_data/historical`.

## v0.1 Storage Shape

v0.1 uses a hybrid model:

- Keep `instrument` as the only writable identity master.
- Keep `instrument_identifier_history` as the ticker/provider-symbol history table.
- Add read-only instrument views for cleaner research reads:
  - `stock_instrument`
  - `etf_instrument`
  - `index_instrument`
- Split physical daily price storage:
  - `stock_daily_price`
  - `etf_daily_price`
  - `index_daily_price`
- Keep legacy `daily_price` during the transition, but new v0.1 ingest writes split tables.

This avoids two writable identity systems while still preventing stock, ETF, and index bars from becoming one large mixed price table.

## v0.1 Quality Checks

Current query builders live under `quality/checks`:

- `duplicate.py`: duplicate `instrument_id + trade_date` groups.
- `missing.py`: missing price rows on trading days.
- `ohlcv.py`: basic non-negative and high/low/open/close constraints.
- `calendar_alignment.py`: price rows that fall on non-trading calendar dates.
