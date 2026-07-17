# CLI Commands

This file is the quick command reference for `database_system_cli`.

## Two Equivalent Ingest Entry Points

For a human-operated, bilingual arrow-key workflow:

```bash
poetry run j21 menu
```

For scripts, AI tools, reproducible notes, and automation:

```bash
poetry run j21 ingest --help
```

Both routes call the same `fdp.get_data` Jobs. The menu does not start a shell
subprocess. Before execution it shows the resolved parameters, their sources,
target tables, API/storage estimate, Job module, and an equivalent CLI command.
Confirmation defaults to **No**.

All migrated ingest commands support `--output text|json`. JSON mode emits one
versioned `JobResult` on stdout and sends progress events to stderr:

```bash
poetry run j21 ingest daily --market US --date 2026-07-07 --output json
```

## Instrument Master

Refresh active instruments and identifier history:

```bash
poetry run j21 ingest instruments --market US
```

The command uses EODHD symbol-change history before the current exchange list.
It writes canonical instruments and identifier history; it does not guess rename
relationships.

## Security ID Mapping

Plan a full US crosswalk sync without calling EODHD or writing the database:

```bash
poetry run j21 ingest id-mappings --exchange US --dry-run
```

Run a small targeted smoke or repair request:

```bash
poetry run j21 ingest id-mappings \
  --symbols AAPL.US,MSFT.US \
  --max-api-calls 2
```

Run or resume the paginated US exchange feed:

```bash
poetry run j21 ingest id-mappings \
  --exchange US \
  --page-limit 1000 \
  --start-offset 0 \
  --max-api-calls 200
```

Exactly one of `--exchange` and `--symbols` is required. Exchange mode is the
normal full-sync path; symbol mode is for small smoke tests and repairs.
`--start-offset` is exchange-only. Every mapping request and retry consumes one
unit from `--max-api-calls`; a separate audited User API preflight verifies the
real account allowance. If the hard budget stops pagination, the result reports
`metrics.next_offset` for the next command.

Status and pagination are separate signals. A completed exchange feed may
return `partial_failed` when some rows require reconciliation; in that case
`metrics.next_offset` is null. A non-null `next_offset` means the remote pages
are incomplete and gives the exact resume position.

Validated CUSIP, ISIN, FIGI, LEI, and CIK values enrich the already resolved
`instrument_id` in `us_share.instrument_identifier_history`. Resolution uses an
exact current provider symbol, then one unique historical provider-symbol owner;
it never guesses by company name or merges instruments from an external ID.
Unresolved, ambiguous, or malformed rows remain in
`system.identifier_mapping_unmatched_observation`.

The provider response has no effective-date fields. These mappings therefore
keep `valid_from` and `valid_to` null and are undated aliases, not current-only
or PIT identifier history. Multiple validated values for one instrument/type
are preserved because the provider does not identify which value is current.
The official endpoint, fields, filters, 1000-row maximum, pagination shape, and
one-call request cost are documented by
[EODHD ID Mapping API](https://eodhd.com/financial-apis/id-mapping-api-cusip-isin-figi-lei-cik-%E2%86%94-symbol).

## Dividends And Splits

Plan a bounded active-stock backfill without calling EODHD:

```bash
poetry run j21 ingest corporate-actions \
  --instrument-status active \
  --action-types dividend,split \
  --max-api-calls 200 \
  --dry-run
```

Run a small explicit smoke after reviewing the plan:

```bash
poetry run j21 ingest corporate-actions \
  --symbols AAPL.US,MSFT.US,META.US \
  --action-types dividend,split \
  --max-api-calls 7 \
  --execute --yes
```

Omitting `--symbols` selects the deterministic local stock scope. Asset type is
fixed to `stock`; Corporate Actions does not accept ETF or Fund instruments.
`--instrument-status active|inactive|all` is a local instrument-master filter.
Dates are optional because omitting `--from/--to` asks EODHD for the maximum
available history.

The hard `--max-api-calls` value includes the audited User API preflight and every
retry. Each `/div/{symbol}` or `/splits/{symbol}` attempt costs one unit. The Job
uses per-instrument transactions, batched checkpoints, idempotent upserts, and
stores rejected provider rows in `system.data_quality_issue`. An interrupted run
can continue with `--resume-run-id` only when the original scope and budget are
unchanged.

Historical rows are routed by event date when identifier history proves that a
ticker had another owner. That dated owner wins; otherwise the unique current
endpoint owner retains pre-rename history. A dated ETF/Fund owner is rejected, and
ambiguous ownership becomes a quality issue rather than a guessed stock event.

For a large run, add `--compact-progress`: the CLI reports every 100 completed
instruments and still prints every retry/failure, while all API calls remain in
`system.api_call_log`.

For a large backfill, use separate active and inactive stock cohorts under explicit
hard budgets. The historical endpoint and request cost are documented by
[EODHD Splits and Dividends API](https://eodhd.com/financial-apis/api-splits-dividends).

If a pre-stock-only run wrote ETF/Fund events, inspect and clean it only after an
out-of-repo backup:

```bash
poetry run j21 migrate corporate-action-identities --phase plan
poetry run j21 migrate corporate-action-identities \
  --phase execute \
  --backup-file /absolute/path/corporate_action.sql.gz \
  --execute --yes
```

The reconcile first moves or merges rows with a unique dated stock owner, records
identity conflicts in `system.data_quality_issue`, then removes all remaining
corporate-action rows joined to non-stock instruments. It never deletes ETF/Fund
instrument or daily-price data.

## Historical Stock, ETF, Fund, And Index EOD

Load a small explicit symbol set:

```bash
poetry run j21 ingest history \
  --symbols AAPL,MSFT,SPY \
  --asset-types stock,etf,fund,index \
  --from 2024-01-01 \
  --to 2024-01-31 \
  --instrument-status active
```

`--symbols` accepts canonical symbols such as `AAPL` and provider symbols such
as `AAPL.US`; lookup is performed through the instrument master. Use
`--instrument-status inactive` to fetch only inactive/delisted symbols, or
`all` for both. Empty symbols are rejected because full-universe history should
use Bulk EOD. `instrument_status` always controls the local instrument lookup;
it is not a status field returned by the historical or Bulk endpoint.

Each symbol is committed independently under one aggregate task run. An isolated
404/no-data symbol is recorded and the batch continues. Authentication,
entitlement, database, or repeated global transient failures stop later symbols.

## Index And Calendar

```bash
poetry run j21 ingest indices \
  --provider-symbols GSPC.INDX,DJI.INDX,IXIC.INDX,NDX.INDX \
  --from 2024-01-01 \
  --to 2024-12-31

poetry run j21 ingest calendar --market US --from 2024-01-01 --to 2024-12-31
```

## One-Day Bulk EOD

```bash
poetry run j21 ingest daily \
  --market US \
  --date 2026-07-07 \
  --asset-types stock,etf,fund \
  --instrument-status active
```

Matched rows enter the canonical split price tables. Unmatched provider rows are
retained in `system.bulk_unmatched_daily_price_observation` for later
classification and routing.

## Daily Range Bulk EOD

Estimate a date range before writing:

```bash
poetry run j21 ingest daily-range --from 2024-01-01 --to 2024-01-31 --dry-run
```

Execute after reviewing the estimate:

```bash
poetry run j21 ingest daily-range \
  --from 2024-01-01 \
  --to 2024-01-31 \
  --asset-types stock,etf,fund \
  --instrument-status all \
  --execute \
  --yes \
  --parallel \
  --workers 4
```

Large API-consuming `daily-range --execute --yes` runs default to user-operated CLI execution.
Codex/AI should prepare the command and then verify database state after the user runs it.

Relevant controls:

- `--parallel/--sequential`: enable or disable bounded per-day parallel ingestion.
- `--workers`: worker count when parallel mode is enabled.
- `--max-requests-per-minute`: request-rate throttle; must be at or below EODHD's 1000 requests/minute ceiling.
- `--instrument-status active|all`: daily update uses `active`; historical survivorship-aware matching uses `all`.
- `--max-api-calls`: weighted hard budget charged before every HTTP attempt, including retries.
- `--max-estimated-gb`: storage estimate guard.

Runtime defaults live in `config/default.yaml` and can be overridden with:

- `EODHD_MAX_RETRIES`
- `EODHD_RETRY_DELAY_SECONDS`
- `EODHD_MAX_REQUESTS_PER_MINUTE`
- `EODHD_DAILY_CALL_BUDGET`
- `EODHD_DAILY_RANGE_PARALLEL`
- `EODHD_DAILY_RANGE_MAX_WORKERS`

## Delisted Instruments

Load EODHD inactive/delisted stock+ETF+Fund universe:

```bash
poetry run j21 ingest delisted-instruments --market US
```

This writes inactive instruments to `us_share.instrument` and records delisting facts in
`us_share.instrument_lifecycle_event`. It is idempotent and does not backfill all
delisted historical prices by default. The current EODHD delisted symbol list does not
return a delisting date, so `instrument.delisted_date` can remain `NULL` until another
source supplies that date.

Run a small inactive-symbol historical price smoke test only when explicitly needed:

```bash
poetry run j21 ingest history \
  --market US \
  --symbols TWTR.US \
  --from 2022-10-20 \
  --to 2022-10-28 \
  --instrument-status inactive
```

Compatibility note: `--include-inactive` is still accepted and means
`--instrument-status all`. Use `inactive` when you only want delisted/inactive
symbols and want to avoid spending API calls on active instruments.

## Bulk Unmatched Workflow

`j21 ingest daily` and `j21 ingest daily-range` first write matched stock/ETF/Fund
rows into split daily price tables. Bulk EOD rows that cannot match the current
instrument universe are stored in `system.bulk_unmatched_daily_price_observation`
instead of being discarded.

The canonical command family is `j21 reconcile bulk-unmatched`. Every command in
this family reads only local MySQL data and has a fixed EODHD API cost of zero.

Inspect the backlog or a bounded sample:

```bash
poetry run j21 reconcile bulk-unmatched summary \
  --from 2024-01-01 --to 2024-01-31

poetry run j21 reconcile bulk-unmatched list \
  --from 2024-01-01 --to 2024-01-31 \
  --status unresolved --limit 50
```

Classify in committed batches. CLI defaults to `unresolved`; `--statuses` can add
`needs_instrument,unknown`. Reprocessing `ambiguous` or `non_price_asset` requires
the explicit `--advanced` gate.

```bash
poetry run j21 reconcile bulk-unmatched classify \
  --from 2024-01-01 --to 2024-01-31 \
  --statuses unresolved \
  --batch-size 5000
```

The result prints one `run_id`. A stopped or intentionally limited run resumes from
its last committed checkpoint:

```bash
poetry run j21 reconcile bulk-unmatched status --run-id <RUN_ID>

poetry run j21 reconcile bulk-unmatched classify \
  --from 2024-01-01 --to 2024-01-31 \
  --statuses unresolved \
  --run-id <RUN_ID>
```

Preview complete `(instrument_id, trade_date)` groups before writing. The default is
dry-run; execute requires both `--execute` and `--yes`.

```bash
poetry run j21 reconcile bulk-unmatched route \
  --from 2024-01-01 --to 2024-01-31 \
  --run-id <RUN_ID> \
  --dry-run

poetry run j21 reconcile bulk-unmatched route \
  --from 2024-01-01 --to 2024-01-31 \
  --run-id <RUN_ID> \
  --execute --yes \
  --batch-size 1000
```

Routing only writes rows that strictly matched an existing stock/ETF/Fund/index
`instrument_id`. Preferred, notes, bonds, warrants, and unknown rows remain in staging.

Historical Bulk identity order is source-date identifier history, current provider symbol,
optional EODHD Type compatibility, then exact instrument. Old/current aliases for one natural
key are not resolved by response order: the unique dated alias wins and the lower-priority row
remains staged as `shadowed`. Dated history is high-confidence. A unique current provider symbol
without a historical conflict is medium-confidence and can route with a persistent identity audit.
CUSIP/ISIN/FIGI mappings without dates can support review but cannot create high confidence.

The router keeps every ticker candidate for one natural key in the same batch. A different
provider symbol cannot replace an equal, lower, or unknown-confidence canonical row. Such conflicts
remain staged and create `identity_route_conflict` in the existing data-quality tables. Each batch
commits staging updates, canonical rows, identity audit, quality issues, and its checkpoint in one
transaction.

Compatibility commands remain available in v0.4 and write a migration warning to stderr:

```bash
poetry run j21 research bulk-unmatched summary --from 2024-01-01 --to 2024-01-31
poetry run j21 research bulk-unmatched list --from 2024-01-01 --to 2024-01-31 --status unresolved
poetry run j21 research bulk-unmatched classify --from 2024-01-01 --to 2024-01-31
poetry run j21 ingest bulk-unmatched-route --from 2024-01-01 --to 2024-01-31 --dry-run
```

They are scheduled for removal in v0.5. New automation should use the `reconcile` family now.

## Daily-Price Asset-Type Reconcile

Metadata can correct an instrument type after older prices were written. Plan first:

```bash
poetry run j21 migrate daily-price-asset-types --phase plan
```

After pausing ingest and reviewing every source/target group, execute in bounded transactions:

```bash
poetry run j21 migrate daily-price-asset-types --phase execute --chunk-size 1000 --execute --yes
```

Each chunk copies to the current canonical type table, verifies all OHLCV/source fields, and only
then deletes the old-table row. Existing conflicting target payloads stop and roll back the chunk.
Rerunning is safe because committed rows no longer appear in the mismatch plan.

## ETF/Fund Physical Split

The large-table migration is operator-controlled and resumable:

```bash
poetry run j21 migrate fund-daily-price --phase plan
poetry run j21 migrate fund-daily-price --phase copy --backup-file /absolute/backup.sql.gz --execute --yes
poetry run j21 migrate fund-daily-price --phase verify --run-id 1
poetry run j21 migrate fund-daily-price --phase finalize --run-id 1 --execute --yes
```

`copy` can resume by run ID. `finalize` refuses to run unless the current verification proves
row conservation, zero natural-key duplicates, zero cross-type rows, and sample checksum match.
Do not run `OPTIMIZE TABLE` as part of this workflow.

## Validate, Repair, And Quarantine

```bash
poetry run j21 validate daily-price --from 2024-01-01 --to 2024-01-31 --asset-types stock,etf,fund,index
poetry run j21 repair plan-daily-price --from 2024-01-01 --to 2024-01-31
poetry run j21 repair list --status pending_confirmation
poetry run j21 repair confirm --plan-id 123 --yes
poetry run j21 repair run --plan-id 123 --yes
poetry run j21 quarantine plan-daily-price --from 2024-01-01 --to 2024-01-31 --issue-types invalid_ohlcv,price_on_non_trading_day
poetry run j21 quarantine list --status pending_confirmation
poetry run j21 quarantine confirm --plan-id 123 --yes
poetry run j21 quarantine run --plan-id 123 --yes
poetry run j21 validate docs-staleness --root ..
```

Quarantine archives the full source payload and hash before deleting a canonical row. Planning,
confirmation, and execution are separate on purpose. `docs-staleness` checks that this tutorial
covers every current Typer leaf command and that managed Markdown/HTML pairs are synchronized.

## Research And Technical Parity

Read local prices:

```bash
poetry run j21 research daily-prices \
  --symbols AAPL.US \
  --asset-type stock \
  --from 2024-01-01 \
  --to 2024-03-31 \
  --adjusted
```

Run the fixed local-vs-EODHD SMA20/EMA20/RSI14 sample. It never permits more than 200 weighted
units and does not write the database:

```bash
poetry run j21 research technical-validate \
  --symbols AAPL.US,META.US,SPY.US \
  --from 2024-01-01 \
  --to 2024-03-31 \
  --max-api-units 200
```

## Research Terminal

```bash
cd ../research_terminal
poetry install
poetry run j21-terminal

cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The UI is read-only: it charts canonical data, exports CSV/PNG,
and displays inert CLI suggestions; it cannot execute ingest, repair, quarantine, or migration.
