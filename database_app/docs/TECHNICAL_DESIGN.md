# EODHD Code Generator App Technical Design

This document describes the implementation under `database_app/`. The app is a lightweight EODHD API playground and code generator for small research queries. It is intentionally separate from `database_system_cli/`.

## Design Goals

- Keep the app independent from the database ingestion system.
- Use endpoint registry data rather than per-endpoint hardcoded pages.
- Add a stock workflow that loads a universe, lets users select or paste-match symbols, and then maps the selection into endpoint params.
- Add a standalone multi-asset Instrument Universe workflow without coupling catalog rows to price requests.
- Generate copyable EODHD direct URLs, Python `requests`, curl, and JavaScript `fetch` snippets.
- Execute whitelisted EODHD endpoints for interactive preview.
- Read the real API token from the local app token store first; `EODHD_API_KEY` is only a fallback for scripted runs.
- Avoid silent fallback to demo keys.
- Avoid database writes, schema changes, Alembic migrations, and shared import path coupling.
- Keep API tokens server-side; config status must not expose the token value.

## Non-Goals

- No large batch downloader.
- No database persistence.
- No authentication layer.
- No `.xlsx` export in the current implementation.
- No complete multi-asset price/analytics implementation; multi-asset support is limited to the Instrument Universe catalog.
- No import from `database_system_cli`; future sharing should be done through an explicit shared package.

## Runtime Architecture

```text
Browser UI
  |
  | GET /, /static/*
  | GET /api/endpoints
  | GET /api/instrument-catalog/menu
  | POST /api/instrument-catalog/exchanges
  | POST /api/generate
  | POST /api/execute
  | GET /api/exports/{execution_id}.csv
  v
ThreadingHTTPServer
  |
  +-- endpoints.py      -> endpoint registry, param specs, docs/plan evidence
  +-- request_model.py  -> validate payload and normalize endpoint params
  +-- cost.py           -> estimate API-call cost and require bulk confirmation
  +-- codegen.py        -> generate token-safe URLs and code snippets
  +-- client.py         -> execute real EODHD requests with server-resolved token
  +-- execution_export.py -> retain one successful full result and serialize safe CSV
  +-- instrument_catalog.py -> catalog mapping, DB facets, EODHD exchange cache
  +-- token_store.py    -> local app config/environment fallback token status/save/delete
  +-- universe.py       -> exchange and screener universe loading
  +-- server.py         -> route handling and loopback/JSON side-effect guards
  +-- static/instrument_catalog.js -> pure catalog draft/menu/mapping logic
  +-- static/app.js     -> workflows, dynamic form renderer, code tabs, preview, export trigger
```

The frontend never receives the real API token. Generated snippets use placeholders:

- `YOUR_EODHD_API_KEY` for direct URLs.
- `os.environ["EODHD_API_KEY"]` for Python.
- `${EODHD_API_KEY}` for curl.
- `process.env.EODHD_API_KEY` for JavaScript examples.

## Dependency Choice

The app currently uses the Python standard library server instead of FastAPI/Jinja2. The reason is practical: the current environment already runs this app without runtime dependencies, while the product risk is endpoint registry correctness, validation, code generation, preview parsing, and token safety. A FastAPI + Jinja2 migration remains a P1/P2 refactor after the app contract stabilizes.

## Directory Layout

```text
database_app/
  pyproject.toml
  README.md
  PROGRESS.md
  PROJECT.md
  PROJECT.html
  docs/
    OFFICIAL_ENDPOINTS.md
    TECHNICAL_DESIGN.md
  site/
    index.html
    styles.css
    PLAN.md
    assets/
      app-preview.svg
    downloads/
      .gitignore
  src/eodhd_codegen_app/
    __main__.py
    client.py
    codegen.py
    cost.py
    endpoints.py
    execution_export.py
    instrument_catalog.py
    request_model.py
    server.py
    token_store.py
    universe.py
    static/
      index.html
      styles.css
      instrument_catalog.js
      timezone.js
      app.js
  tests/
    test_client.py
    test_codegen.py
    test_cost.py
    test_endpoint_registry.py
    test_execution_export.py
    test_instrument_catalog.py
    test_instrument_catalog_tools.js
    test_request_model.py
    test_server_security.py
    test_token_store.py
    test_universe.py
    test_static_app.py
    test_timezone_tools.js
  scripts/
    run_local.command
    package_macos_app.sh
```

## Endpoint Registry

`endpoints.py` defines:

- `EndpointSpec`: endpoint id, label, category, path pattern, official docs URL, plan evidence, call cost, formats, params, implementation status.
- `ParamSpec`: UI/validation contract for one parameter.
- `SUPPORTED_ENDPOINTS`: executable whitelist.
- `INVENTORY_ONLY_ENDPOINTS`: documented but non-executable endpoint groups.

The browser calls `/api/endpoints`, builds the endpoint dropdown and parameter form from the registry, then posts a generic payload:

```json
{
  "endpoint": "historical_eod",
  "fmt": "json",
  "preview_limit": 50,
  "params": {
    "symbols": "AAPL.US",
    "date_from": "2024-01-01",
    "date_to": "2024-01-31"
  }
}
```

This keeps the UI maintainable as endpoints are added.

### Instrument Catalog Contract

Opening Instrument Universe calls `GET /api/instrument-catalog/menu`. That route reads only local DB facets/counts and the current in-process exchange cache; it never calls EODHD. Fixed catalog categories remain available when the DB is unavailable, and the response carries the explicit DB status/reason.

The browser has no free-text exchange input. Selectable stock/ETF/fund venues come from the local DB plus the process cache. Reserved virtual venues (`INDX`, `FOREX`, `CC`, `GBOND`, `MONEY`, `EUFUND`) are excluded from that ordinary exchange list and are applied only by their controlled asset mapping. Stocks default to `type=stock`; ETFs and exchange-listed funds require `type=etf` and `type=fund` respectively.

`POST /api/instrument-catalog/exchanges` is the only route that loads `/exchanges-list/`. It requires the server-side token, uses a lock-protected single-flight cache, and reports whether the response used the cache and how many API calls were made. DB and EODHD rows are deduplicated by uppercase exchange code, with DB-backed venues shown first in the browser.

`INDX` lists index instruments only. Index constituent membership stays disabled because it requires Fundamentals or another authorized constituents source.

### Intraday Time Input Contract

The Intraday wizard accepts helper date/time values through seconds and always interprets them in the IANA `America/New_York` zone. Browser/computer local timezone is ignored. `Intl.DateTimeFormat` resolves EST or EDT for the selected date, and the frontend writes the resulting UTC-based UNIX timestamp seconds into the existing `from_timestamp` and `to_timestamp` fields.

The conversion utility validates its own round trip. A spring DST-gap time that never occurred and a fall DST-overlap time that occurred twice are rejected explicitly instead of being silently normalized. Direct numeric UNIX timestamp editing remains available, and backend interval/range validation remains authoritative.

## Request Flow

### Generate Code

```text
POST /api/generate
  -> validate_payload(...)
  -> generate_snippets(...)
  -> return public request model + token-safe snippets
```

This path does not need `EODHD_API_KEY` because it only builds examples.

### Execute API

```text
POST /api/execute
  -> validate_payload(...)
  -> resolve token from the local app token store or EODHD_API_KEY fallback
  -> build real EODHD URL server-side
  -> urllib request
  -> parse JSON or CSV response
  -> reject responses above 64 MiB or 250,000 rows
  -> retain all rows in the latest-success export store
  -> return preview rows, full row count, and an opaque export id
```

If both the local app token and `EODHD_API_KEY` fallback are missing, the server returns an explicit error. There is no silent fallback to a demo token.

`GET /api/exports/{execution_id}.csv` serializes the retained rows from that exact successful execution. It does not call EODHD again. The process keeps only the latest successful snapshot; a failed execution does not replace it, and all ids expire on server restart.

### Token Config

The `Login / Config` dialog posts a token to `/api/config/token`. The server stores it in a user-local app config file with `0600` permissions by default. The token-store module still has an optional Keychain path, but it is not the default because macOS `security` can block when called from a local HTTP request. The browser never receives the token value; it only receives:

- configured/not configured
- source: `environment`, `local_file`, `keychain`, or `none`
- whether delete is available
- a short status message

Stored local tokens have priority over `EODHD_API_KEY`. Environment variable `EODHD_API_KEY` is only a fallback and cannot be deleted from the app. Stored local tokens can be deleted but not viewed.

### Local Request Guard

This is still a local single-user app, not an authenticated hosted service. To reduce accidental local CSRF/token-spend risk while the app is running, side-effect routes enforce:

- `Host` must be loopback: `127.0.0.1`, `localhost`, or `::1`.
- If an `Origin` header is present, it must also be loopback over `http`.
- POST bodies must use `Content-Type: application/json`.

This blocks simple `text/plain` cross-site POSTs from arbitrary web pages. It is not a replacement for a full authentication layer.

### Mac Packaging

`scripts/package_macos_app.sh` builds local Mac distribution artifacts without changing `database_system_cli`:

- `dist/EODHD Code Generator.app`
- `dist/EODHD-Code-Generator-1.0.0.dmg`
- `dist/EODHD-Code-Generator-1.0.0.pkg`
- `dist/SHA256SUMS.txt`

The bundle copies `database_app` source/docs and pure Python dependencies into app resources. The launcher prepends those resource paths to `PYTHONPATH`, sets `PYTHONDONTWRITEBYTECODE=1` so Python does not mutate signed bundle resources, unsets `EODHD_API_KEY`, and starts the local server on `127.0.0.1` with a random port. It does not bundle the Python runtime; at launch it checks `PYTHON_BIN`, common Homebrew paths, common python.org framework paths, and finally `python3`, requiring Python 3.11+.

The script also copies DMG/PKG/checksum artifacts into `site/downloads/`, so `site/index.html` can serve as the CodeGen product/download page after packaging. The personal homepage and J21 Terminal are independent sibling roots and are not bundled into `database_app`. Public distribution requires a separate signing and notarization release process.

### Stock Workflow

The v0.5 UI is a single workspace. The main screen keeps only the function toolbar, confirmed request summary, generated code tabs, and Execute API result table. Endpoint-specific setup happens in a floating 3-step wizard:

```text
Function card -> Stocks / 选股 -> Parameters / 参数 -> Review / 确认 -> confirmed request -> generate/execute
```

Supported candidate sources:

- Read-only DB pool browser backed by `us_share.instrument`.
- Preset Pools, Exchange, Asset Type, and Index Assets categories.
- User imported `.csv` / `.txt` / pasted text parsed locally in the browser.

Candidate loading does not consume EODHD API calls. Official index constituents are not enabled because there is no current constituent membership source in the app. Index Assets are index instruments, not constituent membership lists, and Sectors stay disabled until a taxonomy source exists.

State model:

- `draftRequest`: wizard state only; does not update the main screen.
- `confirmedRequest`: the only payload used by generated code and Execute API.
- `executionResult`: last executed rows and metadata.
- `resultStale`: set after a new Confirm when previous Execute rows remain visible.

Selection behavior:

- checkbox toggles selection.
- double-click toggles selection.
- Command/Ctrl-click toggles selection.
- regular click only focuses a candidate row.
- valid imported tickers are automatically selected; duplicate and rejected tokens are summarized in the wizard.

Bulk execution uses `cost.py`. The frontend shows an explicit browser confirmation when cost confirmation is required, and the server rejects execution unless the request carries `confirm_cost=true`.
The local execution path is also hard-capped at 50 generated HTTP requests. Larger research lists remain valid for code generation, but the preview UI will not batch-execute them.

The code generator exposes multiple output styles:

- `Direct URL`: one URL per generated request.
- `Python` / `JavaScript`: URL-template loops.
- `Python loop` / `JS loop`: explicit `symbols = [...]` / `const symbols = [...]` loop requests.
- Bulk loop snippets iterate dates and pass the full symbol list once per date, avoiding repeated identical bulk calls.
- Live OHLCV snippets group symbols into 20-symbol requests using the official `s=` parameter.
- `Config token`: local proxy Python code that calls `/api/execute` on the current localhost port so the local app can use the stored Login / Config token without exposing it in generated code.

## Implemented Endpoint Groups

| Group | Endpoint ids |
| --- | --- |
| Market Data | `historical_eod`, `intraday`, `live_ohlcv`, `bulk_last_day_eod` |
| Corporate Actions | `dividends`, `splits` |
| Analytics | `technical` |
| Discovery | `screener` |
| Exchange & Instruments | `exchange_symbol_list`, `instrument_search`, `exchanges_list`, `exchange_details`, `symbol_change_history`, `id_mapping` |

Official documentation links and subscription notes are in `docs/OFFICIAL_ENDPOINTS.md`.

## Validation Rules

The request validator rejects unsupported input before URL generation or execution:

- Unknown endpoint or asset type.
- Unsupported symbols or exchange characters.
- Missing required endpoint params.
- Required params are not silently filled from UI defaults.
- Historical requests without symbols or dates.
- More than 2000 historical symbols.
- Wizard ticker import resolves against active DB `symbol` or `provider_symbol` exact matches, case-insensitively.
- Unknown strings and guessed aliases, such as `BRK.B` when only `BRK-B` is stored, are rejected.
- Historical ranges where `date_from > date_to`.
- Historical ranges longer than 3660 days.
- Intraday unsupported intervals and oversized timestamp ranges; frontend helper tests also cover EST/EDT conversion and DST gap/overlap rejection.
- Bulk requests without symbols unless full exchange is explicitly allowed.
- More than 2000 bulk symbols by default.
- More than 2000 symbols for intraday/technical/live code generation.
- Exchange universe load limits above 2000 rows.
- Screener preset universe load limits above 100 rows.
- CSV format on JSON-only endpoints.
- Search query longer than 80 characters.
- Screener filters that are not a JSON array.
- Preview limits outside 1 to 500.
- Catalog asset/venue/type mismatches, reserved virtual venues in ordinary exchange selection, or exchanges absent from the merged menu.
- Bulk/high-call execution without `confirm_cost=true`.
- Local preview execution above 50 generated HTTP requests.

These rules are app-level guardrails for small manual research usage. They are not EODHD protocol limits.

## Preview Parsing

`client.py` parses:

- CSV responses with `csv.DictReader`.
- JSON list responses into rows.
- JSON dict responses into one row.
- JSON dicts with a `data` list into the `data` rows, which fits APIs such as ID mapping.
- Nested dict/list cell values into JSON strings so the browser table and CSV export do not render `[object Object]`.

The browser receives only the user-selected preview rows (default 50, maximum 500). The server retains the complete parsed response up to 250,000 rows or 64 MiB and caps local execution at 50 generated HTTP requests. When execution fails, the frontend clears the failed preview state and does not replace the latest successful export snapshot.

## CSV Export

The browser downloads `GET /api/exports/{execution_id}.csv`; it does not construct a pseudo-full CSV from preview rows. The server writes UTF-8 BOM CSV, computes the field union over all retained rows, quotes values, and prefixes values beginning with `=`, `+`, `-`, or `@` to reduce spreadsheet formula injection risk. Generated URL/Python/curl/JavaScript snippets can be copied from the active tab through the `Copy active` button.

Excel `.xlsx` export is P1. CSV covers the current research workflow without adding runtime dependencies.

## Error Handling

The server distinguishes:

- `400` for invalid app request payloads.
- `502` for upstream EODHD execution failures or missing stored token / `EODHD_API_KEY` fallback.
- `404` for unknown routes.

Upstream error messages are redacted with the current API key before returning to the browser.

## Testing

Use the existing CLI venv if no standalone app venv exists:

```bash
cd /Users/boqingxin/tandon\ MSCS/My_Own/financial-data-platform/database_app
PYTHONPATH=src ../database_system_cli/.venv/bin/python -m pytest
../database_system_cli/.venv/bin/ruff check src tests
```

Current test coverage includes:

- Endpoint registry docs/plan metadata.
- Token store env/keychain behavior.
- Local side-effect request guards.
- Universe menu/load normalization.
- Instrument catalog mappings, DB/EODHD exchange deduplication, explicit-load cache behavior, and unavailable DB/token paths.
- Latest-success full export retention, opaque ids, full field union, response-size limits, and CSV formula-injection defense.
- API cost estimation.
- Request validation and endpoint boundary checks.
- Required params not silently filled from UI defaults.
- URL generation for market data, analytics, screener, and ID mapping endpoints.
- Token-safe direct URL/Python/curl/JavaScript snippets.
- CSV-mode Python/JavaScript snippet behavior.
- JSON and CSV execution parsing.
- Nested JSON preview parsing.
- Token redaction on upstream errors.

## Local Operation

Run the local server directly, then save the real API token in `Login / Config`:

```bash
cd /Users/boqingxin/tandon\ MSCS/My_Own/financial-data-platform/database_app
PYTHONPATH=src ../database_system_cli/.venv/bin/python -m eodhd_codegen_app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Stop the server with `Ctrl+C` in the terminal running it.

## Future Extraction Path

If this app and `database_system_cli` both continue to use EODHD URL and parameter logic, extract only stable shared pieces into a future package such as:

```text
shared/eodhd/
  endpoints.py
  url_builder.py
  validation.py
```

Do not create implicit cross-project imports from `database_app` into `database_system_cli`. Shared code should have its own tests and a clear ownership boundary.
