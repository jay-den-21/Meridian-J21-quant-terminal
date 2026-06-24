# v0.1 Architecture Plan

v0.1 reorganizes the project from a small ingest prototype into clearer layers:
provider adapters, storage, data quality, reusable ingest scripts, and database-backed
research readers.

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
      retry.py
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
    validation.py
    checks/
      duplicate.py
      missing.py
      ohlcv.py
      calendar_alignment.py

  research/
    daily_prices.py

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
- Data quality execution lives in `quality/validation.py`.
- User-facing reusable scripts live under `get_data/historical`.
- Database-backed Python research reads live under `research`.
- EODHD retry/progress policy lives in `sources/eodhd/retry.py`; CLI only renders progress events.

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

`fdp validate daily-price` executes those checks for requested split price tables and writes:

- `system.data_quality_check_run`
- `system.data_quality_issue`

Missing checks are scoped to instruments already loaded in the target price table, so a partial backfill does not produce millions of expected-but-not-yet-loaded symbols.

## EODHD Retry And Progress

The EODHD client has one shared retry path:

- max retries: 3
- retry wait: 30 seconds
- retryable failures: temporary network failures, timeout/JSON interruption, HTTP 408/429/5xx
- CLI events: `request`, `retrying`, `success`, `failed`

The CLI prints endpoint names and errors, but never prints API tokens.

## Bulk Daily Ingest

`fdp ingest daily` wraps EODHD's Bulk API for EOD, Splits and Dividends in price-only
mode. The current implementation uses:

```text
/eod-bulk-last-day/{exchange}?fmt=json
```

This is the daily update path:

```text
EODHD bulk EOD
-> active stock/ETF instrument match
-> OHLCV validation
-> stock_daily_price / etf_daily_price upsert
-> task/API audit logs
```

It is intentionally separate from `fdp ingest history`:

- `ingest history` backfills selected symbols through one API call per provider symbol.
- `ingest daily` updates one exchange/day through one bulk API request.

The endpoint also supports `type=splits` and `type=dividends`, but v0.1 does not ingest
those through this command because corporate-action storage is not designed yet.

## Research Read Layer

`fdp.research.DailyPriceReader` is the Python-facing read layer for notebooks,
scripts, and future backtests. It reads from MySQL only; it does not call EODHD.

Date priority is explicit:

```text
method-level date_from/date_to
-> reader default date_from/date_to
-> ValueError
```

Partial date overrides are rejected. If a method call provides only `date_from` or
only `date_to`, the reader raises `ValueError` instead of mixing method and reader
defaults silently.

The reader currently supports:

- `stock` -> `stock_daily_price`
- `etf` -> `etf_daily_price`
- `index` -> `index_daily_price`

It resolves identity through current `instrument.symbol`, current
`instrument.provider_symbol`, and `instrument_identifier_history` for ticker/provider-symbol
history. CLI command `fdp research daily-prices` is only a thin wrapper around this reader.
