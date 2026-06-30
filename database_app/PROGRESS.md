# database_app Progress

This file tracks implementation progress for the EODHD API Code Generator App. It is separate from `database_system_cli/PROGRESS.md`.

## Current Status

Completed:

- Created standalone `database_app/` sibling project, separate from `database_system_cli/`.
- Kept `database_system_cli` unmodified; no schema, Alembic, MySQL, or CLI changes.
- Added standard-library Python HTTP server entrypoint.
- Added registry-driven endpoint metadata and parameter specs.
- Added dynamic frontend form rendering from `/api/endpoints`.
- Added implemented endpoint whitelist for:
  - Historical EOD price
  - Intraday historical bars
  - Live delayed OHLCV
  - Bulk last-day EOD
  - Historical dividends
  - Historical splits
  - Technical indicators
  - Stock market screener
  - Exchange symbol list
  - Instrument search
  - Supported exchanges list
  - Exchange trading hours/holidays
  - US symbol change history
  - ID mapping
- Added inventory-only documentation for:
  - Fundamentals
  - Calendar/news
  - Historical market capitalization
- Added generated direct URL, Python requests code, curl command, and JavaScript fetch code.
- Added server-side EODHD execution through `EODHD_API_KEY`.
- Added no-key execution error path without demo-token fallback.
- Added token-safe frontend output: no real API key is rendered in generated code or API responses.
- Added JSON/CSV data preview table.
- Added nested JSON preview coercion for dict/data-list responses.
- Added browser CSV export for returned rows with spreadsheet formula injection mitigation.
- Added official endpoint documentation in `docs/OFFICIAL_ENDPOINTS.md`.
- Added technical design documentation in `docs/TECHNICAL_DESIGN.md`.
- Added project specification docs in `PROJECT.md` and synced `PROJECT.html`.
- Added pytest coverage for registry, request validation, code generation, execution parsing, nested preview parsing, and token redaction.
- Completed server smoke test for `/api/endpoints` and `/api/generate`.
- Completed in-app browser smoke test for default Historical form, Screener dynamic form, and missing `EODHD_API_KEY` execute error.
- Completed evaluator review with no P0 findings.
- Fixed evaluator P1 findings:
  - Screener curl snippets now URL-encode JSON filter quotes while preserving `${EODHD_API_KEY}` shell expansion.
  - JSON `{"data":[]}` responses now return empty rows instead of a wrapper row.
  - JSON error payloads are treated as execution errors and redacted.
  - Failed `Execute API` calls now clear stale preview rows and disable CSV export.
- Fixed evaluator P2 documentation/UI issues:
  - Added `Copy active` snippet button.
  - Clarified exchange-symbol-list evidence as endpoint docs plus pricing feature-list support.
- Added v0.2 stock workflow:
  - Universe menu for exchange symbol lists and EODHD Filtered Pools.
  - Universe load route with token-required execution. Superseded in v0.6 by the read-only DB pool browser; candidate loading no longer requires EODHD token.
  - Checkbox selection table, local filter, selected count, paste-to-match, and apply-selected flow.
  - `Normal API` and `Bulk last-day EOD` call modes.
  - Backend API-call cost estimates and forced bulk confirmation.
- Added token config flow:
  - `/api/config` status route.
  - `/api/config/token` save/delete routes.
  - Local app config token storage with `0600` permissions.
  - Optional Keychain path remains in `token_store.py`, but default UI save avoids macOS `security` blocking.
  - No token readback to browser.
  - Saved Login / Config token now takes priority over `EODHD_API_KEY`; environment token is only a fallback for scripted runs.
  - Direct launch scripts unset `EODHD_API_KEY`, so the normal desktop-style startup uses only the saved Login / Config token.
- Added lightweight desktop review wrappers:
  - `scripts/run_local.command`
  - `scripts/package_macos_app.sh`
- Added local side-effect request guard:
  - loopback-only Host/Origin for POST/DELETE.
  - JSON-only POST bodies.
- Added explicit browser confirmation before confirmed bulk execution.
- Updated `.app` packaging so bundle resources include the app source/docs instead of hard-coding the checkout path.
- Fixed clipboard paste handling:
  - Up to 2000-symbol US research lists can be pasted directly without preloading a universe.
  - `BRK.B` normalizes to `BRK-B.US` for normal calls and `BRK-B` for bulk.
  - US listing venue suffixes from exchange lists normalize to EODHD provider suffixes; for example `AA.NYSE` -> `AA.US` and `AABB.PINK` -> `AABB.US`.
  - Frontend manual paste now applies the same normalization, so selected rows do not display `AA.NYSE`/`AABB.PINK` as provider symbols.
  - Historical EOD normal mode now supports up to 2000 symbols.
  - Selected manual-paste symbols are shown in a dedicated selected table.
- Added code generation modes:
  - one URL per line in Direct URL.
  - Python/JavaScript URL-template loops.
  - Python/JavaScript explicit symbol-array loops.
  - local Config-token proxy example through `/api/execute`.
- Fixed strict evaluator P1 findings after v0.3 review:
  - Config-token proxy examples now use the current localhost port instead of hard-coded `127.0.0.1:8000`.
  - Bulk loop snippets iterate dates and submit the symbol list once per date instead of repeating the same bulk request per symbol.
  - Default token status/save resolves the local app config file before optional Keychain lookup and Keychain reads have a timeout.
  - Exchange universe loading supports up to 2000 rows; Filtered Pool loading stays capped at the official app limit of 100.
  - Live OHLCV accepts up to 2000 symbols for code generation and chunks generated URLs into 20-symbol requests.
  - Local `Execute API` is hard-capped at 50 generated HTTP requests; larger research lists are codegen-only in the preview UI.
- Fixed second-round evaluator P2 notes:
  - Docs now consistently say Execute uses the stored local app token first and `EODHD_API_KEY` only as fallback.
  - Default local token deletion no longer touches Keychain; optional Keychain deletion has a timeout.
- Reworked frontend IA:
  - home screen domain blocks.
  - Stocks detail workspace with left source/selection column and right request/code column.
  - loaded-universe filter explanation.
  - dropdown multi-select and Command/Ctrl-click row selection.
- Added v0.4 Wind-style desktop UI:
  - Ribbon shortcuts for WSD, WSS, WST, WSET, TDays, Tools, and reserved EDB/Trade buttons.
  - Task tab and MDI-like child windows.
  - `+` creates a new active task tab and resets the workspace to a blank request.
  - More compact, retro desktop table/form styling.
  - Program language selector that switches generated code tabs.
  - Initial empty task state now stays `Ready` instead of auto-showing `symbols is required`.
- Added T+n date helper:
  - Anchor date plus from/to offsets.
  - Business-day mode skips weekends; calendar-day mode uses raw calendar days.
  - Writes into endpoint date fields and leaves backend range validation intact.
- Added v0.5 single-workspace request wizard:
  - Removed the large Stocks two-column workspace and task tabs from the P0 screen.
  - Added bilingual function toolbar for Historical Price, Bulk Last-Day EOD, Latest Snapshot, Intraday Bars, and Instrument Lookup.
  - Moved endpoint-specific configuration into a 3-step floating wizard: Stocks, Parameters, Review.
  - Added confirmed-request-only state: draft wizard edits do not update main codegen or Execute API until Confirm.
  - Added CSV/TXT and pasted-text ticker import parsed locally in the browser.
  - Added candidate-table checkbox, double-click, and Command/Ctrl-click selection behavior.
  - Renamed screener-style choices to EODHD Filtered Pools and labeled them as filtered pools, not official index membership.
  - Kept previous Execute results visible after a new Confirm and marks them as previous/stale.
- Added v0.6 read-only MySQL pool browser:
  - Stocks wizard candidate loading now reads the existing `us_share.instrument` table instead of calling EODHD API.
  - DB config precedence is process env first, then read-only `database_system_cli/.env`.
  - `/api/universe/load` no longer requires a stored EODHD token or `EODHD_API_KEY`.
  - Pool Resources categories include Preset Pools, Exchange, Asset Type, Index Assets, and disabled Sectors.
  - Default pool is active US common stocks on NYSE/NASDAQ/AMEX/ARCA/NYSE ARCA/BATS.
  - Index Assets are labeled as index instruments, not index constituent membership.
  - Sectors stay disabled until a sector/industry taxonomy source exists.
  - Advanced Filter supports DB-only filters: active-only, exclude OTC/PINK, preset pool, asset type, exchange, and text search.
  - Candidate/selected UI now uses left/right asset lists with checkbox, double-click, and Command/Ctrl-click selection.
  - Missing DB config or DB connection failure shows explicit unavailable state and does not silently fallback to EODHD API.
  - DB table/query failures return explicit unavailable payloads instead of raw server errors.
  - Pool Browser guards against stale async load responses and hidden stale exchange state.
- Fixed v0.6 CSV export issue:
  - Browser CSV export now builds CSV text before download and delays object URL revocation to avoid 0-byte/empty downloads.
  - Historical EOD CSV execution has explicit parser coverage.
  - CSV parser tolerates leading BOM/blank whitespace in upstream CSV bodies.
- Fixed v0.6 symbol identity and import validation issues:
  - Intraday and other one-symbol-per-request endpoints now annotate preview/export rows with `_provider_symbol`.
  - Ticker import now resolves pasted/file tokens against active `us_share.instrument` `symbol` or `provider_symbol` exact matches, case-insensitively.
  - Unknown tokens such as `FUCK` are rejected instead of being normalized into fake provider symbols.
- Added Wind study notes from the user-provided 2025 PDF and Kancloud link into `PROJECT.md`.
- Added P1 plan for a WindPy-like Python client: `from eodhd_client import w`, `w.start()`, `w.isconnected()`, and `w.wsd`/`w.wss`/`w.wset` mappings.
- Added tests for token store, universe normalization, and API cost estimation.
- Added tests for local side-effect request guards.
- Adopted Trellis as the repo-level large-task execution workflow while keeping `PROJECT.md` / `PROJECT.html` / `PROGRESS.md` / `docs/` as long-term project truth.
- Added `database_app/AGENTS.md` and `docs/RELEASE_NOTES_v1.0.md` for the v1.0 release boundary.

Validation latest run:

```text
../database_system_cli/.venv/bin/python -m pytest -q
79 passed

../database_system_cli/.venv/bin/ruff check --no-cache src tests
All checks passed

node --check database_app/src/eodhd_codegen_app/static/app.js
passed

v1.0 release smoke on http://127.0.0.1:8123/
GET / returned 200; GET /api/endpoints returned the registry; POST /api/generate for historical AAPL.US returned token-safe direct URL, Python, curl, JavaScript, and local proxy snippets; isolated no-token POST /api/execute returned {"error": "EODHD_API_KEY is not set"}.

In-app browser smoke on http://127.0.0.1:8010/
status Ready; no task tabs or old Stocks workspace; function toolbar shows five P0 cards; import AAPL,NVDA,MSFT,GOOGL,AMZN,META,TSLA,NFLX,AMD,BRK.B -> selected provider symbols including BRK-B.US; Review estimates 10 API calls; Confirm generates /eod URLs; opening Intraday then closing does not change the confirmed Historical request; double-clicking an imported candidate toggles selection.

Isolated no-token execute smoke on http://127.0.0.1:8011/
with HOME=/private/tmp/fdp_no_token and no EODHD_API_KEY, POST /api/execute returns 502 {"error": "EODHD_API_KEY is not set"}.
```

Not started:

- FastAPI + Jinja2 migration.
- Excel `.xlsx` export.
- Multi-asset support beyond reserved UI buttons.
- Server-side streaming export for very large exchange-wide responses.
- Shared package extraction with `database_system_cli`.
- Real EODHD execution smoke with a user-provided `EODHD_API_KEY`.
- Real official index constituents universe; current Index Assets are index instruments, not constituent memberships.
- Sector/industry taxonomy-backed pools.
- Holiday-aware exchange trading calendars for T+n helper; current UI helper skips weekends only.

## Next Step

After this productized local version is accepted:

- Run a small real API smoke test with the user's real `EODHD_API_KEY`.
- Run a local DB-backed pool browser smoke test against a populated `us_share.instrument`.
- Promote or reject any additional endpoint groups only after official plan evidence is clear.
- Add Excel export only if research users need formatted workbooks.
- Consider FastAPI + Jinja2 migration once dependency policy is settled.
- Extract a shared EODHD URL/client package once both `database_system_cli` and `database_app` stabilize around the same endpoint semantics.
