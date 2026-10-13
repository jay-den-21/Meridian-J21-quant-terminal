# Ingest Job Contracts

This spec defines how `database_system_cli` exposes the same ingestion behavior to Typer CLI, the interactive terminal menu, and direct Python callers. The sibling `database_system_cli_cn` product does not register Tushare inside `fdp`; its separate contract is recorded below.

## Chinese Tushare Product Boundary

- `database_system_cli_cn/src/fdp_cn` owns its `j21` entry point, Chinese-first
  Menu, endpoint catalog, direct Job, and compatibility dispatcher.
- The CN CLI and Menu must call the same `fdp_cn.tushare.service.IngestService`;
  the Menu must not shell out to the CLI.
- All 93 variants remain visible. Eight reviewed endpoints use the direct page
  transaction path; other runnable historical variants use an explicitly
  labelled isolated compatibility worker. Disabled realtime/unsupported
  variants remain visible but cannot execute.
- `ingest init` and `ingest all` default to dry-run. Live work requires both
  `--execute` and `--yes`; default `all` excludes separately purchased,
  realtime, retired, and known-denied interfaces.
- Direct checkpoints/API summaries use `system_cn`; business rows use
  `a_share`. The sibling `database_system_cli` neither imports this package nor
  owns Tushare commands.
- A relative monthly weight plan persists its resolved first and last complete
  natural month in the immutable checkpoint. Resume must not re-anchor the
  plan from the current date or from the last active index-month unit.
- Compatibility-worker failure records one endpoint failure and continues the
  batch. Direct authentication or storage failure remains a global stop.

## Scenario: Maintain The CN 10,000-Point Execution Inventory

### 1. Scope / Trigger

Apply this contract whenever a CN endpoint, permission classification,
pagination limit, alias, CLI selector, Menu selector, or batch-scope rule is
added or changed. It prevents provider page sizes from being mistaken for
account permissions and prevents CLI/Menu inventory drift.

### 2. Signatures

```text
poetry run j21 ingest list [--category CATEGORY]
poetry run j21 ingest tushare --endpoint KEY [--from DATE --to DATE]
poetry run j21 ingest all --from DATE --to DATE
poetry run j21 menu
```

```python
is_standard_points_eligible(spec: EndpointSpec) -> bool
standard_points_endpoint_specs() -> tuple[EndpointSpec, ...]
IngestService.plan_endpoint(...) -> IngestPlan
IngestService.plan_category(...) -> IngestPlan
IngestService.plan_all(...) -> IngestPlan
```

`AccessSpec.points_tier` is the reviewed account tier. `page_limit` is a
provider pagination value and has no permission meaning.

### 3. Contracts

- The closed catalog has 93 variants backed by 92 physical `Get_*.py` files.
- The reviewed partition is 71 executable standard-point variants, 17
  separately entitled variants, three external realtime variants, and two
  retired/unsupported standard-point variants.
- Default `all` selects exactly the 71 executable standard-point variants with
  `points_tier <= 10000`; it excludes separate, realtime and unsupported
  entries regardless of their page limit.
- CLI and Menu call the same `IngestService`; neither owns a copied endpoint
  list or permission predicate.
- Batch candidate codes are forwarded only to `code_list` or
  `code_date_range` endpoints.
  Without codes, `cyq_chips` uses `legacy_compat` so the preserved getter can
  resolve its stock universe; with codes, it uses the reviewed direct Job.
- An endpoint-local capability, parameter, compatibility-process or timeout
  failure produces `partial_failed` and later endpoints continue.
  Authentication and storage-integrity failures stop the batch.
- All 93 entries remain visible with access, `points_tier`, backend,
  enabled/disabled state and page limit. Unique preserved getter leaf names
  are accepted as aliases.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| `page_limit` is 15,000 but `points_tier` is 10,000 | Keep the endpoint in default `all` |
| Endpoint needs news, minute, US-daily or another separate entitlement | Keep visible; exclude from ordinary category and `all` |
| Standard-point endpoint is retired/unsupported | Keep visible; reject execution; exclude from the 71 |
| Batch has codes and endpoint does not accept codes | Pass an empty code tuple to that endpoint |
| Batch omits codes for direct `cyq_chips` | Route that item through `legacy_compat`; do not reject the 71-item plan |
| Compatibility child exits nonzero or times out | Record one failure and continue |
| Direct authentication or storage integrity fails | Stop later endpoints and return `failed` |

### 5. Good / Base / Bad Cases

- Good: `all` plans 71 unique keys; a supplied stock code reaches
  `cyq_chips` but not `trade_cal`, and CLI/Menu show the same ordered plan.
- Base: a one-endpoint getter alias resolves to its stable catalog key and
  remains dry-run until both execution guards are supplied.
- Bad: infer account points from `page_limit`, keep a second hard-coded Menu
  list, or forward one global code list to every endpoint.

### 6. Tests Required

- Assert the exact 93/92 inventory and the mutually exclusive 71/17/3/2
  partition.
- AST-check every legacy module, class and target-table declaration without
  importing side-effectful getters.
- Plan each of the 71 variants individually and assert `plan_all()` has the
  same ordered keys.
- Exercise CLI JSON and Menu dry-run paths and compare their all/category
  plans with `IngestService`.
- Assert codes, parameters, endpoint-local failure continuation, timeout/nonzero
  compatibility exits, and global authentication/storage stops independently.
- Run the complete CN suite plus `compileall` and `poetry check --lock`.

### 7. Wrong vs Correct

#### Wrong

```python
eligible = spec.page_limit <= 10_000
for spec in catalog:
    run(spec, codes=global_codes)
```

#### Correct

```python
eligible = is_standard_points_eligible(spec)
endpoint_codes = (
    plan.codes
    if spec.scope_kind in {"code_list", "code_date_range"}
    else ()
)
run(spec, codes=endpoint_codes)
```

## Scenario: Add Or Change The CN Index PIT Workflow

### 1. Scope / Trigger

Apply this contract to changes under `fdp_cn.tushare.index_pit`, its CLI/Menu
adapters, the six reviewed index endpoints, or the `a_share`/`system_cn` tables
used by the workflow. It prevents a resume from replaying paid API work, keeps
SW2014 and SW2021 interval semantics separate, and prevents monthly weights
from being represented as daily membership.

### 2. Signatures

```text
poetry run j21 ingest index-pit \
  --phase basic|classify|sw-daily|sw-members|sw-pit|style|general|all \
  [--from YYYY-MM-DD --to YYYY-MM-DD | --months N] [--codes CSV] \
  [--max-retries N] [--max-api-calls N] --execute --yes

poetry run j21 ingest index-pit \
  --resume-run-id ID [--max-retries N] [--max-api-calls N] --execute --yes
```

```python
IndexPitRequest(
    phase: IndexPitPhase | None,
    date_from: date | None,
    date_to: date | None,
    months: int | None,
    codes: tuple[str, ...],
    resume_run_id: int | None,
    max_retries: int | None,
    max_api_calls: int | None,
    execute: bool,
    override_source: str,
)

IndexPitJob.preflight(request, *, runtime=None) -> JobPreflight
IndexPitJob.run(request, *, runtime=None, reporter=None, preflight=None) -> JobResult
```

Persistence signatures:

```text
business: a_share.hq_idx_basic, hq_idx_sw_classify, hq_idx_sw_daily,
          hq_idx_sw_member, hq_idx_sw_member_all,
          idx_sw_member_pit, idx_style_member_pit, idx_member_pit
control:  system_cn.ingestion_task_run, api_call_log,
          index_weight_stage, index_pit_run_lease
```

### 3. Contracts

- CLI and Menu construct the same `IndexPitRequest` and call the same
  `IndexPitJob`; default behavior is dry-run and writes require both guards.
- `phase` and `resume_run_id` are mutually exclusive. Resume restores phase,
  dates/months, codes, units and cursor from the immutable checkpoint; callers
  may only change retry and API-budget controls.
- A checkpoint contains `version`, `kind`, `phase`, immutable `parameters` and
  `units`, `plan_hash`, `cursor`, page signatures, counters, failures,
  `status`, and `complete`. Its plan hash must equal the run's `config_hash`.
- Relative `--months N` plans persist `resolved_weight_date_from` and
  `resolved_weight_date_to`; a later resume never re-anchors the range.
- `style` selects exact `hq_idx_basic.category='风格指数'` and writes only
  `idx_style_member_pit`. `general` requires explicit non-style codes and
  writes only `idx_member_pit`.
- Weight units are one index and one complete natural month. The provider's
  exact snapshot date and weight are stored; weights are never forward-filled
  into daily rows.
- SW2014 uses closed `index_member` intervals through 2021-12-10. SW2021 uses
  closed `index_member_all` intervals from 2021-12-13. Both include L1/L2/L3
  and `is_new=N/Y`; only SSE open dates are materialized.
- Every committed provider page atomically persists business rows, API audit
  and the advanced checkpoint. Weight results stage per run/index/month and
  publish only after exact scope and key validation. SW PIT uses a run-owned
  staging table and atomic publish.
- One `max_api_calls` budget is shared across `phase=all`. Every provider
  attempt, including retries and terminal empty responses, consumes it.
- `no_data` and exhausted unit-local transport retries are auditable failures
  that advance to the next unit. Authentication, rate/budget, schema/storage,
  checkpoint mismatch and global contract errors stop later work.
- Only one writer may target `a_share` at a time. Full SW PIT stays below the
  5 GB target by keeping only its date-first composite primary key unless a
  measured query workload justifies another index.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Both/neither `phase` and `resume_run_id` | Reject before runtime/API creation |
| Only one date boundary, reversed range, or partial current month | Reject preflight |
| Weight request supplies both `months` and dates | Reject preflight |
| `general` has no codes or contains a style code | Reject before API calls |
| Resume changes immutable scope or plan hash | Reject resume; do not issue a request |
| Page repeats an earlier signature, including an A/B/A cycle | Stop as provider-contract failure |
| Response contains another code/date/month or duplicate staged key | Roll back the page/unit and stop |
| Empty monthly response | Record terminal `no_data`, clear page history, advance unit, return `partial_failed` overall |
| Unit-local transport retries exhausted | Record failure and continue the next unit |
| Authentication, rate/budget, schema, or storage failure | Stop later units and preserve committed checkpoints |
| Commit outcome is uncertain | Re-read the durable run/checkpoint and accept only an exactly matching committed candidate |
| SW PIT staging fingerprint/owner differs | Refuse resume or publish |
| A second live `a_share` writer is detected | Refuse execution through the run lease |

### 5. Good / Base / Bad Cases

- Good: a six-month style run records both successful CSI/CNI months and
  terminal `no_data`, then a five-year run extends only the successful,
  effective-date-overlapping codes without replaying the first six months.
- Good: an interrupted `index_weight` run resumes at the first uncommitted
  `(index_code, month, offset)` and keeps the originally resolved month range.
- Base: `000300.SH` is category `规模指数`, so an explicit `general` request
  publishes one exact monthly snapshot to `idx_member_pit`.
- Bad: treat `index_weight` as daily membership or forward-fill it; monthly
  snapshots and interval-derived daily SW membership are different products.
- Bad: query SW2014 through `index_member_all`; removed SW2014 codes are absent
  there and must come from `index_member`.

### 6. Tests Required

- CLI/Menu dry-run and double-confirmation, exact date range and recent-month
  input, shared Job dispatch, text/JSON result shape, and secret-free logs.
- Checkpoint plan-hash/scope validation, relative-month fixed range, cursor and
  page-signature replay rejection, post-commit reconciliation and run-lease
  cleanup reconciliation.
- Exact style/general routing, active-date filtering, complete-month planning,
  terminal `no_data` continuation, unit-local transport continuation, fatal
  authentication/storage stop and shared `all` API budget.
- SW2014/SW2021 cutover, inclusive `out_date`, weekend gap, all three levels,
  Y/N completeness, staging ownership/fingerprint and primary-only final
  schema.
- Page limits and offsets for all reviewed endpoints; response scope, field,
  duplicate-key and nullable historical `sw_daily` validation.
- Full CN unit suite, `compileall`, Poetry validation, then authorized serial
  live checks of run counters, API audit, zero staging residue, duplicate keys,
  month continuity and snapshot weight sums.

### 7. Wrong vs Correct

#### Wrong

```python
# Recompute “last 60 months” when resuming and advance memory before commit.
units = plan_recent_months(60, today())
checkpoint["cursor"] = next_cursor
write_rows(rows)
```

#### Correct

```python
checkpoint = load_and_validate_checkpoint(run_id)
candidate = advance_copy(checkpoint, committed_page)
with engine.begin() as connection:
    publish_page(connection, committed_page)
    record_api_audit(connection, committed_page)
    save_checkpoint(connection, candidate)
checkpoint = candidate
```

The immutable checkpoint retains the originally resolved complete-month range,
and only the transactionally committed candidate becomes the in-memory cursor.

## Scenario: Add Or Change An Ingest Workflow

### 1. Scope / Trigger

Apply this contract whenever a change adds or modifies:

- a `j21 ingest` command;
- a `j21 menu` ingestion wizard;
- a reusable Python ingestion entrypoint;
- preflight, progress, retry/stop, or result behavior.

The purpose is to prevent CLI, menu, and Python callers from developing separate business logic.

### 2. Signatures

Every human-operable ingest workflow must expose a Job under `fdp.get_data`:

```python
class ExampleJob:
    job_key: str
    job_module: str

    def preflight(
        self,
        *,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
        **options: object,
    ) -> JobPreflight: ...

    def run(
        self,
        *,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        preflight: JobPreflight | None = None,
        override_source: str = "python",
        **options: object,
    ) -> JobResult: ...
```

User-facing entrypoints:

```text
poetry run j21 menu
poetry run j21 ingest <workflow> [options] [--output text|json]
```

Menu discovery is explicit through `fdp.get_data.registry.INGEST_JOB_DEFINITIONS`. Every registry key must have one `fdp.menu.app.JOB_HANDLERS` entry.

### 3. Contracts

Parameter precedence:

```text
CLI/menu explicit value > Python Job module default > ValueError
```

`JobPreflight` must be read-only and include:

```text
job, job_module, target_tables, work_units, estimated_api_calls,
parameters, parameter_sources, estimated_rows?, estimated_gb?,
missing_symbols, warnings
```

`JobResult` is a versioned contract and must include:

```text
schema_version, job, status, run_id, parameters, parameter_sources,
row/API/work-unit counters, failures, missing_symbols, error_message,
preflight
```

Allowed statuses are `dry_run`, `success`, `partial_failed`, `failed`, and `cancelled`.

Progress is UI-neutral:

```python
class ProgressReporter(Protocol):
    def on_event(self, event: ProgressEvent) -> None: ...
    def on_api_event(self, event: EodhdApiEvent) -> None: ...
```

- CLI renders stable line events.
- JSON mode sends progress to stderr and exactly one `JobResult` JSON object to stdout.
- Menu renders work-unit events with `tqdm` and always closes the bar in `finally`.
- API keys, database passwords, and complete authenticated URLs must never enter events or results.

Runtime wiring:

- `JobRuntime.from_env()` creates the SQLAlchemy engine and runtime config.
- EODHD client/API-key loading is lazy through `JobRuntime.client(...)`.
- Preflight and confirmation must happen before client construction for guarded writes.
- Tests inject engine/client dependencies through `JobRuntime`.

MySQL storage and migration contract:

- When an upsert refreshes a server-default timestamp that is absent from the
  INSERT values, assign `CURRENT_TIMESTAMP` directly. Do not reference the
  inserted-row alias for a column that the INSERT did not supply.
- MySQL DDL is non-transactional in this project. A migration with multiple DDL
  steps must inspect existing columns/tables/indexes and safely resume after a
  partial failure.
- Before replacing an index that MySQL also uses to support a foreign key,
  create a dedicated foreign-key index. Do not disable foreign-key checks to
  force the index drop.

Historical transaction contract:

```text
commit aggregate ingestion_task_run
-> resolve instruments
-> one transaction per provider symbol
-> finalize aggregate run with committed facts
```

Corporate-action stock-only contract:

- `CorporateActionsHistoryJob` fixes `asset_type='stock'`; CLI and Menu must not
  expose an ETF/Fund selector.
- The request universe is stock-only, but identity resolution may read dated
  stock/ETF/Fund owners so reused tickers can reject a proven non-stock event.
- A unique dated provider-symbol owner wins. When no dated prior owner exists, the
  unique current endpoint owner may retain pre-rename history because the current
  EODHD symbol endpoint can return older events for the same security.
- Overlapping dated owners are quality issues and must not be guessed.
- Cleaning legacy mixed-scope rows requires an external backup, moving/merging
  uniquely dated stock events first, then deleting only corporate-action rows whose
  final owner is non-stock. It must not delete ETF/Fund instruments or prices.

Bulk daily write-lock contract:

- Write asset tables in a fixed order and sort each table's rows by
  `(instrument_id, trade_date, provider_symbol)` before chunking.
- Sort unmatched staging rows by their unique key before chunking.
- A deterministic order reduces InnoDB deadlocks but does not make concurrent
  mixed insert/update upserts against the auto-increment daily tables safe.
- Historical reruns that update existing prices while adding newly resolved
  instruments use one database writer unless the Job has either a single-writer
  queue or transaction retry that reuses the already-fetched provider response.
- Never implement a blind whole-unit retry that silently spends another weighted
  Bulk API request.

EODHD transport retry contract:

- Idempotent GET requests retry transient URL/timeouts, truncated HTTP bodies
  (`IncompleteRead`), remote closes without a response (`RemoteDisconnected`),
  and transient JSON decode failures under the configured retry limit.
- Reserve endpoint-weighted API units immediately before every HTTP attempt;
  retries consume the same units as the original attempt.
- Do not mark a work unit complete until the full response body parses and its
  database transaction commits.
- If the weighted budget is exhausted, preserve prior date commits and stop
  before issuing the next HTTP request.

Daily-range parallel stop contract:

- Cancel futures that have not started after a fatal stop condition.
- Continue collecting already-running/completed futures so `JobResult` counters match writes that actually committed.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Required option has no explicit value or Job default | Raise `ValueError` before API calls |
| Date end precedes start | Raise `ValueError` / Typer `BadParameter` |
| Daily-range API/storage estimate exceeds guard | Reject before API-key/client creation |
| `j21 menu` has no interactive TTY | Exit with guidance to use `j21 ingest` |
| Historical symbol is unknown | Add `missing_instrument` failure; do not write Bulk unmatched/DQ rows |
| Isolated provider 404/no-data | Record failed unit and continue |
| HTTP 401/402/403 | Stop later work units immediately |
| Repeated global transient failures | Stop after the configured consecutive threshold |
| DB/parser exception in a historical unit | Roll back that unit, stop, and finalize the parent run |
| Operator cancellation | Keep committed work and return cancelled/partial state |
| Parallel future fails after peers started | Cancel pending work, drain running peers, include their results |
| JSON mode | One parseable stdout object; operational events on stderr |

### 5. Good / Base / Bad Cases

- Good: `j21 ingest history --symbols AAPL,AAPL.US ...` resolves both values through the instrument master and writes each resolved instrument once.
- Base: a Job called directly from Python uses module-level dates when the caller omits dates.
- Bad: a required date is absent in both caller options and module defaults; execution fails before building an API client.
- Bad: a menu wizard runs `subprocess("j21 ingest ...")`; this creates two parsing/error surfaces and is forbidden.
- Bad: a CLI handler calls `load_bulk_daily_prices(...)` directly while the menu calls a Job; move orchestration into the Job.

### 6. Tests Required

For every added/changed Job, assert:

- explicit option and module-default precedence, including `parameter_sources`;
- preflight target tables and API/storage estimates;
- no client construction for rejected/dry-run preflight;
- success and provider failure result counters;
- fatal versus isolated failure stop behavior;
- transaction/finalization behavior when DB work raises;
- one parseable JSON stdout result;
- menu confirmation defaults to cancel and makes no Job call;
- registry keys and menu handlers remain equal;
- non-TTY menu rejection;
- progress reporter cleanup after exceptions.

Run at minimum:

```bash
poetry run pytest
poetry run ruff check --no-cache src tests scripts
poetry run python -m compileall -q src tests scripts
poetry run alembic heads
```

### 7. Wrong vs Correct

#### Wrong

```python
@ingest_app.command("daily-range")
def daily_range(...):
    # CLI owns parallel workers, API calls, transactions, and aggregation.
    load_bulk_daily_prices(...)

def menu_daily_range(...):
    # A second implementation with different defaults.
    load_bulk_daily_prices(...)
```

#### Correct

```python
job = DailyRangeJob()

# CLI
result = job.run(..., reporter=CliProgressReporter())

# Menu
preflight = job.preflight(...)
result = job.run(preflight=preflight, reporter=TqdmProgressReporter())
```

Both adapters only collect input and render output; the Job owns execution.

## Scenario: Add Or Change A Local Staging Reconcile Workflow

### 1. Scope / Trigger

Apply this contract when a workflow classifies staged provider rows, routes them to canonical
tables, exposes a resumable Menu flow, or adds a persisted checkpoint. Reconcile is local data
processing: it must not construct a provider client or consume API units.

### 2. Signatures

Canonical Bulk-unmatched surface:

```text
j21 reconcile bulk-unmatched summary --from DATE --to DATE
j21 reconcile bulk-unmatched list --from DATE --to DATE [--status STATE]
j21 reconcile bulk-unmatched classify --from DATE --to DATE [--statuses CSV] [--run-id ID]
j21 reconcile bulk-unmatched route --from DATE --to DATE [--run-id ID] --dry-run
j21 reconcile bulk-unmatched route --from DATE --to DATE --run-id ID --execute --yes
j21 reconcile bulk-unmatched status --run-id ID
```

Persistence signatures:

```text
system.ingestion_task_run.checkpoint_json JSON NULL
system.bulk_unmatched_daily_price_observation.last_classified_run_id BIGINT NULL
system.instrument_identity_resolution_audit
INDEX (market, classification_status, trade_date, observation_id)
```

### 3. Contracts

- One guided Menu workflow exposes one `ingestion_task_run.run_id` across classify, route, and
  validate.
- CLI classify defaults to `unresolved`; Menu defaults to
  `unresolved,needs_instrument,unknown`. Ambiguous/non-price states require an explicit advanced
  choice.
- Classify freezes one max observation ID per source status and uses
  `(trade_date, observation_id)` keyset pagination. A status change must not cause the same row to
  re-enter the same run; write `last_classified_run_id`.
- Classify defaults to 5,000 observations per batch. Route defaults to 1,000 complete
  `(instrument_id, trade_date)` groups per batch.
- Every staging/canonical/audit/quality mutation and its new checkpoint must commit on the same
  connection and transaction. Replace the in-memory checkpoint only after the transaction context
  exits successfully.
- Route must satisfy `observations_selected = routed + shadowed + route_failed` and
  `canonical writes = routed`; validation cannot report success otherwise.
- A dated unique alias is high confidence. A unique current provider symbol with no dated conflict
  is medium confidence. Undated ID mappings do not create high confidence.
- A different canonical provider symbol is overwritten only by high-over-explicit-medium evidence.
  Equal/lower/unknown confidence stays staged and becomes a quality issue.
- JSON stdout is one `JobResult`; progress/deprecation warnings use stderr. Interactive Rich output
  is presentation only and must fall back to plain text outside a TTY.
- Migration code must validate the exact classifier index column order. A same-name, wrong-shape
  index is an error, not an acceptable pre-existing object.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Unsupported source status | Reject before DB mutation |
| Resume scope changes date, market, statuses, or route assets | Reject the resume |
| Current batch or commit fails | Roll back batch; preserve prior checkpoint |
| Count says matched groups remain but selector returns none | Mark stalled/failed; do not claim success |
| Alias group would cross a batch boundary | Select group keys first, then load every alias in those groups |
| Existing symbol differs and confidence cannot upgrade it | Keep canonical row; mark route failure and quality issue |
| Price validation fails | Keep staging row; use `invalid_ohlcv` or `api_rejected_row`, not identity conflict |
| Route counts do not close | Mark validation `partial_failed` |
| Failure-status checkpoint cannot be persisted | Return the original failure plus checkpoint-update failure; do not mask it |
| Any reconcile API counter/log is nonzero | P0 contract failure |

### 5. Good / Base / Bad Cases

- Good: a unique dated old ticker beats the current ticker for that historical date; the old row
  routes and the current alias remains `shadowed`.
- Base: a unique current symbol with no history conflict routes as medium confidence and widens one
  aggregated identity-audit interval.
- Bad: update the Python checkpoint before transaction commit; a commit failure then skips
  uncommitted rows on resume.
- Bad: apply `LIMIT` to observations before grouping; aliases for one instrument/date can land in
  different transactions.
- Bad: check only that an index name exists; the optimizer contract depends on exact column order.

### 6. Tests Required

- status allowlist, frozen snapshot, multi-status no-rescan, keyset cursor, Ctrl+C, statement failure,
  and commit failure;
- complete alias groups, dated winner, shadowed aliases, confidence upgrade/rejection, price failure
  issue type, closure counts, idempotent rerun, and route stall;
- one run ID through Menu classify/route/validate, both default-No confirmations, latest-vs-history
  instrument-status defaults, Rich plain fallback, and reporter cleanup;
- legacy CLI warning compatibility, new help routes, JSON stdout parse, persisted status cursors, and
  zero API calls;
- migration exact index shape, online DDL text, guarded downgrade, one Alembic head, real
  `EXPLAIN ANALYZE`, and bounded live MySQL smoke.

### 7. Wrong vs Correct

#### Wrong

```python
checkpoint["last_observation_id"] = batch.last_id
with engine.begin() as connection:
    update_staging(connection, batch)
    save_checkpoint(connection, checkpoint)
```

The in-memory cursor advances even if commit fails.

#### Correct

```python
candidate = deepcopy(checkpoint)
candidate["last_observation_id"] = batch.last_id
with engine.begin() as connection:
    update_staging(connection, batch)
    save_checkpoint(connection, candidate)
checkpoint = candidate
```

Only a successfully committed candidate becomes the next in-memory checkpoint.
