# database_app AGENTS.md

This file defines AI work constraints for `financial-data-platform/database_app`.

Before changing this subproject, read:

- root `AGENTS.md`
- `database_app/PROJECT.md`
- `database_app/PROGRESS.md`
- `database_app/docs/OFFICIAL_ENDPOINTS.md`
- `database_app/docs/TECHNICAL_DESIGN.md`

## Boundaries

- `database_app` is a sibling of `database_system_cli`, not a child module.
- Do not modify `database_system_cli` while working on app features unless the user explicitly requests a cross-subproject change.
- Do not modify MySQL schema, Alembic migrations, or ingestion flows from this app.
- The pool browser may read existing `database_system_cli/.env` database config and query `us_share.instrument` read-only.
- Missing DB config, DB connection failure, or schema failure must show an explicit unavailable state. Do not silently fall back to EODHD API.
- `database_app/site/` is the CodeGen product/download page and packaging target only. Personal homepage and Terminal roots are local-only and must not be required by the public app or its tests.
- Cross-product navigation may link to sibling roots, but must not copy their views, scripts, styles, or assets into `database_app`.

## Token And API Rules

- Never commit real `.env`, EODHD API keys, saved tokens, passwords, or private keys.
- The browser must not receive the saved token value.
- Generated snippets must use placeholders such as `YOUR_EODHD_API_KEY`, `${EODHD_API_KEY}`, or environment-variable examples unless the user explicitly requests otherwise.
- `/api/execute` must not return real upstream URLs containing tokens.
- Upstream errors returned to the browser must be redacted.
- Do not add a demo-token fallback.

## Endpoint Rules

- Endpoint whitelist entries must have official EODHD documentation and plan evidence in `docs/OFFICIAL_ENDPOINTS.md`.
- If 29.99 Extended access is unclear, keep the endpoint inventory-only until verified.
- Do not label filtered pools as official index membership.
- Do not add sector, industry, index-constituent, or vendor taxonomy pools without an official or licensed membership source.

## UI, Codegen, Export

- Keep the app usable as a local single-user research tool.
- Preserve the confirmed-request model: draft wizard changes must not affect Execute API until confirmed.
- CSV export must avoid spreadsheet formula injection.
- Bulk requests must expose cost warnings and require explicit confirmation where implemented.
- Local Execute remains for small interactive previews; large research lists should use generated code.

## Documentation

- `PROJECT.md` is the app specification source.
- `PROJECT.html` must be synchronized whenever `PROJECT.md` changes.
- `PROGRESS.md` tracks milestone progress only, not every small edit.
- Release notes live under `database_app/docs/`.

## Validation

For meaningful app changes, run the relevant subset of:

```bash
cd database_app
PYTHONPATH=src ../database_system_cli/.venv/bin/python -m pytest
../database_system_cli/.venv/bin/ruff check --no-cache src tests
node --check src/eodhd_codegen_app/static/app.js
```

For release work, also run server smoke tests and secret/staging hygiene checks.
