# database_app v1.0 Release Notes

Release tag: `database-app-v1.0.0`

## Summary

`database_app` v1.0 is the first productized local release of the EODHD API Code Generator App. It is a standalone sibling project next to `database_system_cli`, focused on small equity research workflows, token-safe code generation, API preview, CSV export, and read-only stock universe browsing.

## Highlights

- Wind-style local API code generator and playground.
- Bilingual function toolbar for:
  - Historical Price
  - Bulk Last-Day EOD
  - Latest Snapshot
  - Intraday Bars
  - Instrument Lookup
- Registry-driven endpoint metadata and parameter validation.
- Generated direct URL, Python `requests`, curl, and JavaScript `fetch` snippets.
- Real EODHD execution through saved local token first, with `EODHD_API_KEY` as scripted fallback.
- Token-safe frontend output: saved tokens are never returned to the browser.
- JSON/CSV preview table and browser CSV export.
- Read-only MySQL pool browser over existing `us_share.instrument`.
- CSV/TXT/pasted ticker import with DB-backed exact symbol/provider-symbol matching.
- Bulk cost estimation and explicit confirmation guard.
- Local side-effect request guard for loopback-only JSON POST/DELETE routes.

## Supported Endpoint Surface

The executable whitelist is documented in `docs/OFFICIAL_ENDPOINTS.md` and implemented through the endpoint registry. v1.0 supports Historical EOD, Intraday, Live OHLCV, Bulk EOD, Dividends, Splits, Technical Indicators, Screener, Exchange Symbol List, Instrument Search, Exchanges List, Exchange Details, Symbol Change History, and ID Mapping.

Inventory-only groups remain documented but not executable when 29.99 Extended plan evidence is unclear or the product appears separate: fundamentals, calendar/news, historical market cap, and official index constituents.

## Governance

This release adopts Trellis as the task-level workflow while preserving the existing Markdown governance model:

- `AGENTS.md`, `PROJECT.md`, `PROGRESS.md`, and `docs/` remain long-term project truth.
- Trellis records large-task PRD/design/implementation history.
- Trellis tasks that change product facts must sync project Markdown and paired HTML docs.

## Validation

Release validation should include:

```bash
cd database_app
PYTHONPATH=src ../database_system_cli/.venv/bin/python -m pytest
../database_system_cli/.venv/bin/ruff check --no-cache src tests
node --check src/eodhd_codegen_app/static/app.js
```

The release task also runs local server smoke checks, no-token execution checks, secret scan, and staged-file hygiene checks before tagging.

Latest validation for this release:

```text
PYTHONPATH=src ../database_system_cli/.venv/bin/python -m pytest
79 passed

../database_system_cli/.venv/bin/ruff check --no-cache src tests
All checks passed

node --check src/eodhd_codegen_app/static/app.js
passed

Local smoke on http://127.0.0.1:8123/
GET / -> 200
GET /api/endpoints -> registry returned
POST /api/generate -> token-safe snippets returned
POST /api/execute without token -> {"error": "EODHD_API_KEY is not set"}
```

## Known Limits

- Local single-user tool, not hosted multi-user software.
- No database writes.
- No Excel `.xlsx` export.
- No full multi-asset implementation.
- No official index constituent universe in the 29.99 Extended whitelist.
- Sector/industry pools stay disabled until a licensed taxonomy or membership source exists.
