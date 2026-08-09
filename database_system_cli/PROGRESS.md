# Progress

This file tracks implementation progress for `database_system_cli`. `PROJECT.md` remains the project specification.

## Current Status

The project has a runnable, testable, and committable Python + Poetry scaffold.

Completed:

- Tushare CLI/Menu/client/Job and the completed `qtdb_pro_rep -> a_share`
  operator were removed from this product; sibling `database_system_cli_cn`
  now solely owns Tushare ingestion, while this project only protects the
  externally managed `a_share` schema from downgrade deletion.
- Python package scaffold under `src/fdp`
- Poetry project metadata and dependency definitions
- CLI entrypoint through `poetry run j21 --help`; `fdp` remains as a temporary compatibility alias
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
- `j21 ingest instruments --market US --source eodhd` command path
- Instrument ingestion service that parses, rejects unsupported/malformed rows, upserts valid rows, and records task/API summaries
- Unit tests for EODHD client URL construction, instrument row rejection, ingestion task logging, and CLI command registration
- `instrument_identifier_history` schema and migration for ticker/provider symbol history
- EODHD `symbol-change-history` client/parser and instrument rename reconcile before upsert
- Unit tests for symbol-change parsing, history upsert, and rename reconcile
- EODHD historical EOD client method for symbol-limited daily price pulls
- Daily price parser and OHLCV validation for `date/open/high/low/close/adjusted_close/volume`
- `j21 ingest history --symbols ... --from ... --to ...` command path
- Historical daily price ingestion service that looks up active instruments, calls EODHD, rejects invalid rows, upserts valid rows, and records task/API summaries
- Unit tests for historical EOD URL construction, daily price parsing, history ingestion, and CLI command registration
- Local MySQL migration applied through `0006_split_daily_tables`
- Real historical ingest smoke test: `AAPL,MSFT,SPY` from `2023-01-01` to `2024-01-01`, 750 rows inserted, 0 rows rejected, 0 duplicate `instrument_id + trade_date` groups
- Real 3-year stock/ETF historical ingest smoke test: `AAPL,MSFT,SPY` from `2023-01-01` to `2025-12-31`, 2256 rows inserted, 0 rows rejected, 0 duplicate `instrument_id + trade_date` groups across the 3 stock/ETF symbols and 4 benchmark indices
- EODHD `/symbol-change-history` access verified after plan upgrade: run_id 6 fetched 1062 rename rows, updated 44 existing instruments, and wrote 176 identifier-history rows
- EODHD index daily price ingestion through `j21 ingest indices`; real 3-year smoke test for `GSPC.INDX,DJI.INDX,IXIC.INDX,NDX.INDX` from `2023-01-01` to `2025-12-31` inserted 3009 rows with 0 rejected rows and 0 duplicate `instrument_id + trade_date` groups
- EODHD market calendar ingestion through `j21 ingest calendar`; latest real 3-year US calendar smoke test from `2023-01-01` to `2025-12-31` inserted 1096 calendar rows with 752 trading days and 344 non-trading days
- Unit tests for EODHD exchange-details client methods, market calendar parser/upsert, index daily ingest, market calendar ingest, and CLI command registration
- `market_calendar` early-close flag removed from v0.1 scope as a pseudo requirement; calendar keeps only trading-day semantics
- EODHD ingest workflows split into focused v0.1 modules under `sources/eodhd/ingest/`, with old `sources/eodhd/ingestion.py` kept as a compatibility facade
- v0.1 storage now keeps `instrument` as the only writable identity master, adds read-only `stock_instrument`/`etf_instrument`/`index_instrument` views, and writes new price ingest into `stock_daily_price`/`etf_daily_price`/`index_daily_price`
- `get_data/historical` wrappers now route stock, ETF, index, and market-calendar pulls through explicit reusable functions
- Data quality query builders now cover duplicate groups, missing trading-day rows, OHLCV constraints, and price rows on non-trading calendar dates
- Operator-confirmed repair workflow added for missing daily-price issues: `repair plan-daily-price`, `repair list`, `repair confirm`, and `repair run` create/preview/confirm/execute backfill plans against existing `system.repair_plan`
- Repair execution backfills by immutable `instrument_id`, not by ticker guessing, and only marks the linked `data_quality_issue` resolved after the target daily-price row exists
- Repair workflow hardened after adversarial review: logical duplicate missing issues share one active plan, stale provider symbols are rejected before API calls, and confirmed plans are claimed as `executing` before external backfill starts
- Operator-confirmed quarantine workflow added for bad existing daily-price rows: `system.quarantine_plan`, `system.quarantined_daily_price_row`, and `j21 quarantine plan-daily-price/list/confirm/run`
- Quarantine execution archives source row payload/hash before deleting rows for `invalid_ohlcv` and `price_on_non_trading_day`, then resolves the linked `data_quality_issue` only after post-action verification
- Quarantine workflow hardened after adversarial review: confirm/run previews source rows, execution claims the plan, locks source rows, checks actual delete rowcount, and refuses to silently resolve stale non-trading issues while rows remain
- Operator-confirmed dedupe workflow added for `duplicate_key` daily-price groups: exact duplicate payloads are deduped through the quarantine archive/delete path, while conflicting duplicate payloads are rejected for manual review
- EODHD API calls now use a centralized retry/progress policy: up to 5 retries, default 61-second waits, retryable transient status/network failures, and CLI-visible `request`/`retrying`/`success`/`failed` messages without printing API tokens
- `j21 validate daily-price` command now executes duplicate, missing loaded trading-day row, OHLCV, and non-trading-day price checks, then writes `system.data_quality_check_run` and `system.data_quality_issue`
- Database-backed research read layer added through `fdp.research.DailyPriceReader`, with method-level dates overriding reader defaults and strict `ValueError` behavior for missing or partial date ranges
- `j21 research daily-prices` command added as a thin CLI wrapper around the Python research reader
- EODHD Bulk EOD endpoint wrapped through `EodhdClient.get_bulk_eod(...)`
- `j21 ingest daily` added as the bulk daily update path: one EODHD bulk request, active stock/ETF instrument matching, OHLCV validation, split-table upsert, and task/API audit logging
- `j21 ingest daily-range` added as a guarded multi-day Bulk EOD path: dry-run by default, `--execute --yes` gated writes, per-day transactions, optional bounded parallel workers, request-rate throttling, and pre-run API-call/storage budget checks
- Real active stock+ETF daily bulk backfill completed for `2018-08-01` to `2022-07-07`: 990 trading days, 49,201,725 rows fetched, 31,612,511 rows inserted, 17,589,214 unmatched active-universe rows rejected, 990 HTTP requests, 99,000 estimated API-call cost, and 0 failed days
- Post-backfill DB verification passed: `stock_daily_price` and `etf_daily_price` both cover all 990 trading days in `2018-08-01..2022-07-07`, with 0 duplicate `(instrument_id, trade_date)` groups and no missing trading-day sample
- Full MySQL backup created after the active bulk run and before delisted rerun: `/private/tmp/j21-daily-backfill-delisted/backups/j21_mysql_contains-delisted_pre-delisted-rerun_20260707_035632.sql.gz`; name is explicit because the live DB already contained inactive/delisted rows
- EODHD delisted/inactive universe workflow added through `j21 ingest delisted-instruments --market US`; idempotent rerun fetched 58,322 rows, accepted 53,645 stock/ETF/fund rows, rejected 4,677 unsupported/malformed rows, and left lifecycle duplicate keys at 0
- Real EODHD delisted-symbol-list payload does not include a delisting date field, so the workflow can reliably set `instrument.is_active = false` and write lifecycle events, but `instrument.delisted_date` remains `NULL` unless a later source supplies a date
- Inactive history smoke test passed: `j21 ingest history --symbols TWTR.US --from 2022-10-20 --to 2022-10-28 --include-inactive` fetched and inserted 6 `stock_daily_price` rows with `instrument.is_active = false`
- Legacy `us_share.daily_price` was removed after verification: it had 5,265 rows and only one row not already represented in split tables, the known bad holiday row `DJI.INDX` on `2024-12-25`
- Live DB Alembic version was reconciled from the older dirty-workflow revision `0022_quarantine` back onto the clean migration chain, then upgraded through `0009_bulk_unmatched`.
- EODHD runtime knobs added to `config/default.yaml` / `.env.example`: max retries, retry delay, request rate, daily API-call budget, daily-range parallel flag, and worker count
- Documentation workflow rule added to `AGENTS.md`: when human-facing Markdown docs are updated, matching HTML docs and the `PROGRESS.md` board must be kept in sync when applicable
- `PROJECT.md` / `PROJECT.html` audience rule documented: Markdown is the Codex/AI-facing specification source, while HTML is the shared readable board for user and Codex/AI
- User-operated ingest workflow rule added to root and subproject `AGENTS.md`: small smoke tests and read-only validation can be run by Codex/AI, while large API-consuming ingest defaults to user-operated CLI execution unless explicitly delegated
- `j21 ingest history` now supports `--instrument-status active|inactive|all`; legacy `--include-inactive` remains compatible as `all`, and conflicting new/old flags are rejected
- Bulk EOD unmatched staging added through Alembic `0009_bulk_unmatched`: unmatched rows are stored in `system.bulk_unmatched_daily_price_observation` with raw payload, OHLCV fields, classification status, and exact-match routing metadata
- `j21 ingest daily` now writes unmatched Bulk EOD rows into the system staging table instead of only counting them as rejected
- Bulk unmatched review/classification CLI added: `j21 research bulk-unmatched summary/list/classify`
- Bulk unmatched routing CLI added: `j21 ingest bulk-unmatched-route --dry-run` previews matched rows, while `--execute --yes` writes high-confidence stock/ETF/index rows to split daily price tables
- Focused verification for the bulk unmatched workflow passed: storage schema/upsert, CLI registration/conflict behavior, EODHD ingest, and classifier/route tests passed with 54 targeted tests; focused ruff checks passed
- `app_log` snapshot schema cleanup added through Alembic `0010_app_log_snapshots` and `0011_drop_us_share_snapshots`: API playground/search/screener/quote/live/websocket snapshots are copied out of `us_share`, verified by count, and legacy `us_share` snapshot tables are dropped so `us_share` stays focused on canonical market data and instrument master data
- Real post-split 3-year ingest smoke test: `AAPL,MSFT,SPY` from `2023-01-01` to `2025-12-31` wrote 2256 rows into split stock/ETF tables with 0 rejected rows
- Real post-split 3-year index ingest smoke test: `GSPC.INDX,DJI.INDX,IXIC.INDX,NDX.INDX` from `2023-01-01` to `2025-12-31` wrote 3009 rows into `index_daily_price` with 0 rejected rows
- Post-split DB verification found 0 duplicate `instrument_id + trade_date` groups in stock, ETF, and index price tables
- Resolved one vendor data-quality issue manually after EODHD fixed the source data: deleted stale `DJI.INDX` `2024-12-25` row from `index_daily_price`; all four benchmark indices now have 752 rows for `2023-01-01` to `2025-12-31`, and verified non-trading index price rows are 0
- Real validate smoke test: `j21 validate daily-price --from 2023-01-01 --to 2025-12-31 --asset-types stock,etf,index` completed with 0 issues and wrote check runs for stock, ETF, and index price tables
- Repository layout migrated so the database CLI system now lives under `financial-data-platform/database_system_cli/`; project docs, source, tests, Alembic migrations, and config moved together, while the repository root is reserved for the future app
- `docs/architecture.md` added to record the Data Core / Terminal boundary, MySQL daily-data decision, Parquet recommendation for high-volume intraday bars, and large-run guardrails for 15-year daily / 1-year 5m loads
- Shared `fdp.get_data` Job layer added for instrument, historical stock/ETF/index, calendar, Bulk EOD, daily-range, and Bulk unmatched workflows; CLI, terminal menu, and direct Python callers now share parameter resolution, preflight, runtime, progress, and structured result contracts
- `j21 menu` added as a bilingual Chinese/English arrow-key terminal workflow with basic/advanced prompts, target-table/API/storage preflight, equivalent CLI preview, default-cancel confirmation, and `tqdm` progress
- Typer ingest commands now invoke the shared Jobs and support `--output text|json`; JSON stdout is a single versioned result object while operational progress is routed to stderr
- Historical stock/ETF Job execution now resolves canonical/provider symbols through the instrument master, commits each symbol independently under one aggregate task run, preserves completed work on cancellation/failure, and stops on fatal auth/entitlement, DB, or repeated global transient failures
- Terminal menu and shared Job verification covers non-TTY rejection, default-cancel behavior, JSON output, parameter precedence, API-budget preflight, isolated symbol failure, fatal stop, and parent-run finalization
- Shared Job/menu quality gate passes 136 tests plus Ruff/compileall; a real-DB `daily-range --dry-run` for `2024-01-02` resolved 1 trading day, 45,848 estimated rows, 0.03 GB, and 100 estimated API-call cost without calling EODHD or writing data
- Scoped maintainer/agent context is now defined at the docs, shared Job, terminal menu, EODHD provider, storage, Alembic, quality, repair, quarantine, and research boundaries; parent `AGENTS.md` files provide deterministic routing, and `docs/architecture.md/.html` trace the current executable flows with Mermaid diagrams and exact code paths
- Canonical asset model now keeps `stock/etf/fund/index/forex/crypto`; EODHD Fund/Mutual Fund is no longer collapsed into ETF, and `fund_instrument`/`fund_daily_price` are managed at Alembic head `0014_fund_compact_swap`.
- Real ETF/Fund split completed from a verified 2.6 GiB compressed backup (SHA-256 `b32c4cc054e5a36aa73bdbaeee0867c7bba04c2fddff8f39c7f86c3e1801b1aa`): ETF `7,100,821` + Fund `56,464,163` = source `63,564,984`, with 0 duplicate natural keys, 0 cross-type rows, and matching sampled checksum; `OPTIMIZE TABLE` was not run.
- Historical Bulk identity matching now uses source-date identifier history before current provider symbols, treats missing historical `Type` as unavailable only for a unique identity, stages lower old/current aliases as `shadowed`, and preserves ambiguous/invalid/unresolved raw rows.
- Approved four-worker `instrument-status=all` Bulk backfill completed for `2010-09-30..2014-08-15`: 979/979 work units, 0 failed days, 0 retries, 33,729,043 source rows, 33,289,082 canonical matched rows processed, 236,312 unmatched rows, 173,525 shadowed aliases, and 98,001 task units including User API preflight.
- Post-backfill verification passed: stock `12,031,361`, ETF `1,200,695`, and Fund `20,096,562` rows in `2010-09-30..2014-08-18`; all three cover both endpoints, retain unique `(instrument_id, trade_date)` indexes, and have 0 cross-table type contamination.
- Recent-first historical Bulk recovery completed for factor research over `2022-08-08..2026-07-06`: 980/980 trading days, run IDs `4046..5025`, 48,191,634 source rows, 46,958,823 matched rows, 98,000 weighted API units, 0 failed days, and 0 retries.
- Post-recovery DB verification passed for all 980 dates: Stock `17,063,497`, ETF `4,127,506`, Fund `25,587,451`, and Bulk staging `1,550,792` physical rows; every date has all three canonical asset classes plus staging, table/master mismatch counts are 0, and all canonical tables retain unique `(instrument_id, trade_date)` indexes.
- Historical Bulk recovery added a verified continuous prefix `2014-09-18..2018-08-08`: 980/980 dates, run IDs `5026..6007`, 44,389,798 source rows, 43,220,825 canonical upsert effects, and an exact 99,800 weighted units across 980 successes, 16 successful internal retries, and 2 pre-fix terminal transport failures.
- Post-recovery verification passed for the older prefix: Stock `14,226,096`, ETF `1,767,338`, Fund `27,260,645`, and staging `1,168,973` physical rows; every table covers all 980 dates, table/master mismatch counts are 0, and canonical natural-key unique indexes remain present.
- Historical Bulk recovery continued through `2018-08-09..2022-03-30`: 917/917 dates, run IDs `6009..6925`, 45,485,986 source rows, 44,146,515 canonical upsert effects, and 92,400 weighted units across 917 successful calls plus 7 retries. All four destinations cover every date and Stock/ETF/Fund table-master mismatch counts are 0.
- The final `2022-03-31..2022-08-05` continuation completed 88/88 dates with run IDs `6927..7014`, 4,506,354 source rows, 4,329,704 canonical upsert effects, 176,650 staged observations, 8,800 weighted units, 0 retries, and 0 failed dates.
- Historical Bulk unmatched recovery is complete for all 2,986/2,986 affected trading dates in `2014-08-19..2026-07-06`. Post-staging run evidence and durable staging rows cover every date; canonical natural-key indexes remain present and all verified Stock/ETF/Fund table-master mismatch counts are 0.
- The `2014-08-18` observation spike was verified as retained audit history: 39,585 rows are already `resolved`; only 558 are non-resolved (345 unknown, 1 ambiguous, 210 shadowed, 2 invalid), matching adjacent-day levels.
- Historical calendar audit found EODHD omitted three official closures. Nasdaq/SEC-backed US overrides now mark `2012-01-02` and Sandy `2012-10-29/30` non-trading; 49 canonical rows were archived into quarantine, deleted, and all 49 linked issues resolved. `2012-07-03` early-close data was retained.
- Local adjusted/raw indicators now calculate SMA20/50/200, EMA20, Bollinger20/2, RSI14, MACD12/26/9, Volume SMA20, and annualized 20-day volatility without materializing indicator tables.
- `j21 research technical-validate` provides a 200-unit hard-capped EODHD parity diagnostic. AAPL/META/SPY SMA20/EMA20/RSI14 used 45 units; all 9 comparisons passed with maximum absolute error about `0.00005`.
- New sibling `research_terminal/` is operational: GET-only FastAPI/SQLAlchemy backend, React/TypeScript/ECharts Overview/Security/Funds/Data Health views, stock/ETF candles, Fund NAV line, safe CSV, PNG, and no ingest/repair HTTP route.
- Terminal verification passes 22 backend tests, frontend Vitest/build, npm audit with 0 vulnerabilities, and 8 Playwright desktop/mobile tests with real AAPL/VFINX data, nonblank canvas pixels, and no global horizontal overflow.
- Final database CLI suite passes 235 tests plus Ruff and compileall; Alembic code and live DB both report the single `0015_id_mapping_ingest` head.
- Final cross-table audit found 871 rows for 22 instruments that were written as stock before later
  metadata corrected them to ETF. New `j21 migrate daily-price-asset-types` plan/execute workflow
  copies, verifies, and transactionally deletes drift rows; a 100-row smoke plus 771-row completion
  moved all rows with no target conflicts, and the final global mismatch plan is 0.
- Daily quality validation now reports future table/master drift as `asset_type_mismatch` and points
  to the reconcile workflow instead of quarantining valid prices.
- EODHD Security ID Mapping is operational through one shared Job, Typer CLI, and bilingual terminal menu. Live run `7022` completed all 110 remote pages: 109,338 rows fetched, 98,810 exactly matched, 176,599 new undated aliases inserted, 30,350 aliases unchanged, 10,625 rows staged for reconciliation, 0 request failures, and `next_offset=NULL`. Targeted repair run `7023` resolved all six blank-field parser false positives; normalized identifier duplicates and conflicting intervals are both 0.
- Guided Bulk reconciliation is operational through `j21 reconcile bulk-unmatched summary/list/classify/route/status`. Classify uses 5,000-row checkpointed keyset batches; route uses complete 1,000-group batches, confidence-aware overwrite protection, identity audit, existing quality tables, atomic checkpoints, and 0 EODHD API calls. The v0.4 research/ingest routes remain warning-compatible and are scheduled for removal in v0.5.
- Alembic `0016_guided_bulk_reconcile` is the single code/live head. It adds `checkpoint_json`, `last_classified_run_id`, `instrument_identity_resolution_audit`, and the exact `(market, classification_status, trade_date, observation_id)` index with online DDL and shape validation. Live `EXPLAIN ANALYZE` used that index to fetch 5,000 rows in about 21.5 ms.
- Bounded real-DB reconciliation smoke stayed within authorization: 905 observations classified in 100-row batches, one complete FIRRF.US group dry-run/routed, repeated route produced 0 new groups, canonical/audit/staging counts remained 1/1/1, duplicate groups were 0, related API logs were 0, and daily-price quality runs found 0 issues.
- Guided Menu now hands successful Bulk daily/range results to a colored summary, skippable 10-second review, default-No classify/route confirmations, Rich Live measured progress, route dry-run, automatic daily-price validation, final retained-issue samples, and same-`run_id` resume. Latest daily defaults to active; explicit historical daily and daily-range default to active+inactive.
- Harsh review hardened three non-obvious failure modes: migration rejects a same-name/wrong-shape classifier index; route enforces `selected = routed + shadowed + failed` plus canonical/routed closure; invalid price payloads use `invalid_ohlcv`/`api_rejected_row` rather than identity-conflict issues. Final gate passes 274 tests, Ruff, compileall, docs-staleness, CLI help, and live Alembic current.
- `docs/system_tables.md/.html` now records every managed `system` table's purpose, writer, reader, retention policy, and deletion boundary; it is included in deterministic Markdown/HTML staleness validation.
- Stock-only EODHD Corporate Actions ingestion is operational through one shared Job, `j21 ingest corporate-actions`, and the bilingual Menu. The request universe is fixed to `instrument.asset_type='stock'`; no ETF/Fund selector exists, while non-stock ticker owners are read only as collision guards.
- Alembic `0017_corporate_actions` adopts the existing canonical table without dropping legacy rows. The backup-gated `j21 migrate corporate-action-identities` cleanup moved 182 dated stock rows, merged 205 rows, removed 334,467 ETF/Fund-owned action rows, and now plans 0 additional moves/merges/deletes; 8 overlapping stock-owner rows remain explicitly audited.
- Corporate Action runs `7030..7038` consumed exactly the authorized 99,800 API units. Final inactive-stock run `7038` completed 23,846 instruments using 47,694 units, fetched 352,772 rows, accepted 352,718, and retained 54 rejected rows as 30 identity ambiguities, 22 proven non-stock owners, and 2 invalid split ratios.
- Final Corporate Action verification passed: 867,857 canonical stock rows (833,703 dividends and 34,154 splits), 0 non-stock rows, 0 natural-key duplicate groups, 0 invalid typed rows, and 0 logged run-7038 symbols outside the selected inactive-stock universe. The protected pre-cleanup backup is `/private/tmp/j21-corporate-action-stock-only-precleanup-20260718-012824.sql.gz` with SHA-256 `3799743d0355c1a9f4be9c1e7e4df73c78f30023cec3aa875e66c1b1148257ff`.
- The five-layer CLI architecture is now the maintainer map: Source Intake -> Task Orchestration -> Security Alignment -> Quality/Publish -> Published Data/Research. Human docs use raw/pending/published/held/quarantined while legacy internal `canonical` names remain unchanged.
- Durable Daily Bulk tasks are implemented with immutable task/date fingerprints, automatic exact-scope resume, verified overlap reuse, `--new-run`, live/stale lease protection, periodic heartbeat, per-date checkpoints, source-row closure, thin-response retry/held review, and zero-provider exact-complete results. Daily and daily-range remain dry-run by default and require `--execute --yes`.
- Daily now automatically runs local classify/route/validate unless `--manual` is selected. The bilingual Menu exposes Continue/New and Auto/Manual with one final confirmation; `j21 task list/status/adopt-daily-legacy` provides operator inspection and strict old-run adoption.
- `.agents/skills/j21-daily-ingest` and the stdio `j21-mcp` adapter reuse the same Job/TaskLedger. MCP has four read tools and two execute tools; writes require both `J21_MCP_ENABLE_WRITES=1` and `confirm_execute=true`. Full verification passes 359 tests, Ruff, compileall, Poetry metadata check, Alembic single head `0018_daily_task_ledger`, CLI help, and MCP initialize/list-tools smoke.

In progress:

- the separate 1-minute EODHD Parquet storage contract and fixture-only validation; Massive and PIT remain excluded from this task

## Next Step

- implement the separate 1-minute Parquet contract with fixture-only EODHD validation and zero real intraday API calls
- add an explicit operator-controlled skip/manual-review path for future rename-history API outages
- decide the next delisted-date source: EODHD Fundamentals/Corporate Actions, Nasdaq/FINRA lists, or manual enrichment, because the EODHD delisted symbol list does not expose delist dates
- plan point-in-time universe membership so active-only backtests can be clearly separated from survivorship-bias-aware research
- extend delisted historical backfill in small, budgeted batches after date-source and universe policy are settled
- run the full retained Bulk staging backlog through `j21 menu -> Reference / reconcile -> Bulk unmatched -> New` under user control, then verify checkpoint closure, quality runs, canonical duplicate keys, audit aggregation, and remaining status samples; do not auto-route identity conflicts
- design the separate from-zero database bootstrap wizard after the full reconcile run; it remains outside the Guided Bulk workflow
- remove the v0.4 `research bulk-unmatched` and `ingest bulk-unmatched-route` compatibility aliases in v0.5 after dependent notes/automation migrate
- create a dedicated MySQL SELECT-only account for `research_terminal`; the application SQL guard remains defense-in-depth, not the only permission boundary
- decide whether to persist exact/periodic table statistics for Terminal Overview instead of using labeled InnoDB estimates
- reconcile the remaining `10,619` ID Mapping observations, starting with `10,522 missing_instrument` rows; do not create or merge instruments from CIK/LEI/CUSIP/ISIN/FIGI alone
- review the 8 retained overlapping stock-owner Corporate Action rows and the 30 new event-date identity ambiguities before any manual reassignment; do not guess ownership
- plan stock-only incremental dividend/split updates and targeted retry policy for isolated legacy-symbol 404s; ETF/Fund Corporate Actions remain out of scope
