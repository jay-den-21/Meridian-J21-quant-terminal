# database_app

`database_app` is a lightweight EODHD API Code Generator and desktop-style API playground for small equity research queries. It is intentionally separate from `database_system_cli`; it does not import or modify the database CLI, Alembic migrations, MySQL schemas, or ingestion code.

The v0.5 UI keeps the Wind-style code-generator idea but simplifies the main screen: a compact bilingual function toolbar, a confirmed-request summary, generated code tabs, and an Execute API result table. Endpoint-specific setup now happens in a 3-step floating wizard, and only a confirmed wizard request updates code generation or Execute API.

## Run Locally

From the repo root:

```bash
cd database_app
PYTHONPATH=src python -m eodhd_codegen_app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Stop the server with `Ctrl+C` in the terminal that is running it.

Code generation works without an API key. `Execute API` uses the token saved through `Login / Config` first. `EODHD_API_KEY` is only a fallback for scripted runs. If neither exists, the app returns a clear error and does not fall back to a demo key.

For review as a local desktop-style app:

```bash
cd database_app
./scripts/run_local.command
```

To generate local macOS install artifacts:

```bash
cd database_app
./scripts/package_macos_app.sh
open "dist/EODHD Code Generator.app"
open "dist/EODHD-Code-Generator-1.0.0.dmg"
```

The script builds:

- `dist/EODHD Code Generator.app`
- `dist/EODHD-Code-Generator-1.0.0.dmg`
- `dist/EODHD-Code-Generator-1.0.0.pkg`
- `dist/SHA256SUMS.txt`

It also copies the DMG/PKG and checksums to `site/downloads/`, so the CodeGen product/download page works after packaging:

```bash
open site/index.html
```

The wrapper starts the same local server on `127.0.0.1` with a random port and opens it in the system browser. The generated `.app` copies the app source/docs and pure Python dependencies into its bundle, but it does not bundle the Python runtime. At launch it checks `PYTHON_BIN` first, then common Homebrew and python.org Python 3.11+ install paths, before falling back to `python3`.
Direct launch scripts unset `EODHD_API_KEY` before starting the server, so the desktop-style flow uses the token saved in `Login / Config`.

The generated DMG/PKG are local developer artifacts. Public Mac distribution should use Apple Developer ID signing and notarization before posting the files on a public website.

The Stocks wizard pool browser reads candidates from the existing MySQL `us_share.instrument` table. It uses process `FDP_DATABASE_URL` / `FDP_DB_*` first, then read-only `../database_system_cli/.env`. If DB config or connection is missing, the app still opens and can generate/execute confirmed API requests, but Pool Resources shows an explicit unavailable state instead of calling EODHD API.

## Tests

```bash
cd database_app
PYTHONPATH=src python -m pytest
ruff check src tests
```

If you want to reuse the existing CLI virtualenv:

```bash
cd database_app
PYTHONPATH=src ../database_system_cli/.venv/bin/python -m pytest
../database_system_cli/.venv/bin/ruff check src tests
```

## Supported Endpoint Whitelist

Supported endpoints are registry-driven in `src/eodhd_codegen_app/endpoints.py` and rendered dynamically by the frontend.

| Endpoint id | EODHD path | Formats | Notes |
| --- | --- | --- | --- |
| `historical_eod` | `/api/eod/{provider_symbol}` | JSON / CSV | Historical daily/weekly/monthly EOD OHLCV |
| `intraday` | `/api/intraday/{provider_symbol}` | JSON / CSV | 1m/5m/1h bars; U.S. Eastern helper converts to UTC UNIX seconds |
| `live_ohlcv` | `/api/real-time/{provider_symbol}` | JSON / CSV | Delayed latest OHLCV, small watchlist |
| `bulk_last_day_eod` | `/api/eod-bulk-last-day/{exchange}` | JSON / CSV | Requires symbols unless full exchange is explicitly allowed |
| `dividends` | `/api/div/{provider_symbol}` | JSON / CSV | Historical dividends |
| `splits` | `/api/splits/{provider_symbol}` | JSON / CSV | Historical splits |
| `technical` | `/api/technical/{provider_symbol}` | JSON / CSV | EODHD technical indicators |
| `screener` | `/api/screener` | JSON | Stock market screener |
| `exchange_symbol_list` | `/api/exchange-symbol-list/{exchange}` | JSON | Exchange symbol list |
| `instrument_search` | `/api/search/{query_string}` | JSON | Active instrument lookup |
| `exchanges_list` | `/api/exchanges-list/` | JSON | Supported exchanges |
| `exchange_details` | `/api/v2/exchange-details/{exchange}` | JSON | Trading hours and holidays |
| `symbol_change_history` | `/api/symbol-change-history` | JSON / CSV | US ticker rename history |
| `id_mapping` | `/api/id-mapping` | JSON | CUSIP/ISIN/FIGI/LEI/CIK/EODHD symbol mapping |

Inventory-only endpoints currently not whitelisted for the 29.99 Extended app surface:

- `fundamentals`: pricing shows Fundamentals Data Feed as a separate 59.99 plan.
- `calendar_news`: pricing shows Corporate Events Calendar & News API as a separate marketplace product.
- `historical_market_cap`: official page is under Fundamental & Economic Data; 29.99 Extended access was not clear enough to whitelist.

Official evidence is documented in `docs/OFFICIAL_ENDPOINTS.md`.

## Stock Workflow

The main screen shows five P0 function cards:

- `Historical Price / 历史行情`
- `Bulk Last-Day EOD / 批量日终行情`
- `Latest Snapshot / 最新快照`
- `Intraday Bars / 分钟线`
- `Instrument Lookup / 证券搜索`

Clicking a function opens a floating 3-step wizard:

- `Stocks / 选股`: browse DB-backed Pool Resources, parse `.csv` / `.txt` / pasted tickers locally, resolve them against the local `us_share.instrument` table, and select with checkbox, double-click, or Command/Ctrl-click.
- `Parameters / 参数`: fill dates, period, adjustment, interval, lookup fields, and endpoint-specific parameters. `Date helper: T+n` fills `from` / `to` / `trade_date` from an anchor date plus business-day or calendar-day offsets. Intraday adds a second-precision `America/New_York` helper that applies EST/EDT automatically and writes UTC-based UNIX timestamp seconds.
- `Review / 确认`: check selected ticker count, format, preview rows, warnings, and estimated API calls; Confirm updates generated code and the executable request.

Notes:

- Draft wizard edits do not change the main screen until Confirm.
- Execute API always uses the last confirmed request.
- Previous Execute results stay visible after a new Confirm and are marked as previous/stale until Execute runs again.
- Pool Resources do not spend EODHD API calls. Execute API and Instrument Lookup still use the stored Login / Config token.
- Default stock candidates are active US common stocks on NYSE/NASDAQ/AMEX/ARCA/NYSE ARCA/BATS.
- `Index Assets` are DB index instruments only, not index constituents. Sectors are disabled until a sector/industry taxonomy or membership source is added.
- The app does not label S&P/MSCI/broker/申万-style industry or index pools unless there is an official/authorized constituent source.
- Imported tickers must exact-match active DB `symbol` or `provider_symbol` values case-insensitively. Unknown strings are rejected instead of being normalized into fake provider symbols.
- Imported tickers are DB-exact. Class-share aliases are not guessed; use the active DB `symbol` or `provider_symbol` spelling, for example `BRK-B` / `BRK-B.US` if that is how the instrument is stored.
- Intraday helper date/time input is always U.S. Eastern Time (`America/New_York`), not the browser or computer timezone. Ambiguous and nonexistent DST transition times are rejected explicitly.
- Most per-symbol endpoints consume one API call per ticker. The UI strongly warns above 100 selected tickers and caps selection at 2000.
- High-call execution requires explicit confirmation, and the local `Execute API` button is hard-capped at 50 generated HTTP requests. Use generated code for larger research lists.
- Code tabs include one-URL-per-line output and list/array loop snippets. Bulk loop snippets iterate dates, not symbols, so they do not repeat the same bulk request per ticker.

## Wind-Style Python Client Plan

P1 is a WindPy-like client layer:

- `pip install eodhd-codegen-app` or a later split package such as `eodhd-client`.
- `from eodhd_client import w`.
- `w.start()` reads the stored local app token; if missing, it opens Login / Config or prompts once, then prints `EODHD is connected`.
- `w.isconnected()` reports token/probe status.
- `w.wsd(...)`, `w.wss(...)`, and `w.wset(...)` map to the app's EODHD endpoint whitelist without requiring users to export `EODHD_API_KEY` manually.

Bulk mode is intentionally restricted to `/api/eod-bulk-last-day/{exchange}`. The server returns an estimated API-call cost and requires explicit browser confirmation before executing bulk requests. Date-range bulk requests are capped at 31 calendar days.

## Security And Token Handling

- The app reads the real token from the local app token store first. `EODHD_API_KEY` is only a fallback for scripted runs.
- `Login / Config` stores a token in a user-local app config file with `0600` permissions by default. Keychain support remains available in the token-store module but is not the default save path because macOS `security` can block inside a local HTTP request.
- The browser never receives the stored token value; it only sees configured/source/delete status.
- Stored tokens can be deleted but not viewed.
- Local side-effect routes reject non-loopback `Host`/`Origin` headers and require JSON POST bodies.
- Generated direct URLs use `YOUR_EODHD_API_KEY`.
- Generated Python uses `os.environ["EODHD_API_KEY"]`.
- Generated curl uses `${EODHD_API_KEY}`.
- Generated JavaScript uses `process.env.EODHD_API_KEY`.
- The `Config token` code tab calls the local app `/api/execute` route on the current localhost port, so it can use the token saved through `Login / Config` without printing the token into generated code.
- `/api/execute` does not return the real URL or token to the browser.
- Upstream error text is redacted before returning to the browser.
- No `.env` or real API key should be committed.

## Export

CSV export is implemented in the browser from the last returned result rows. Browser payloads are capped at 5000 rows to keep the app responsive; the preview table itself uses the selected preview row limit.

Excel export is P1. P0 avoids `openpyxl`, `xlsxwriter`, Pandas, or a browser spreadsheet library because CSV covers the immediate research workflow without adding runtime dependencies.

## Documentation

- `PROJECT.md` is the project specification source file.
- `PROJECT.html` is the browser-friendly generated view of the project specification.
- `PROGRESS.md` tracks the app status.
- `docs/OFFICIAL_ENDPOINTS.md` records official EODHD endpoint and plan evidence.
- `docs/TECHNICAL_DESIGN.md` explains architecture, request flow, validation, testing, and future extraction.

## Known Limits

- This is a local single-user tool, not a hosted multi-user service.
- No database writes, persistence, authentication, or audit logs are implemented.
- Bulk full-exchange requests are allowed only after an explicit checkbox because they cost at least 100 API calls.
- The local Execute button is capped at 50 generated HTTP requests; larger lists should use generated Python/curl/JavaScript code outside the preview UI.
- Real API smoke tests require the user's real `EODHD_API_KEY` or saved local app token; automated tests use fakes only.
