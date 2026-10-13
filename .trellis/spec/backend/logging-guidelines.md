# Logging Guidelines

> Runtime logging contracts for data ingestion and repair jobs.

---

## Scenario: Tushare endpoint runtime visibility

### 1. Scope / Trigger

Apply this contract whenever `basis.tools` fetches, cleans, writes, retries,
paginates, creates indexes, or removes duplicate rows. It prevents an active
provider call or SQL cleanup from looking like a hung process.

### 2. Signatures

```python
ts2db_father_template.run() -> object
ts2db_father_template.ts2db_get_data_agent() -> int
ts2db_father_template._log_call_result(fetched, cleaned, written) -> None
deal_duplicate_in_hq_lost(params, table, business_key_sql) -> int | None
```

An optional, test-only or operator-controlled duplicate scope may be supplied
as `params.deal_duplicate_scope_filters: dict[str, str]`. Production behavior
is unchanged when that attribute is absent.

### 3. Contracts

- Log database initialization with SQLAlchemy's masked engine representation;
  never interpolate the raw DSN.
- Log Tushare client initialization and package versions; never log the token.
- At the start of every `run()`, log the target table and Chinese table name.
- After every provider call, log the monotonically increasing call number,
  active date/code/source scope, and fetched/cleaned/written row counts.
- When the first positive response is smaller than the requested page size,
  record the observed server page size and continue pagination with that size.
- Log the final fetched/cleaned/written totals before index and cleanup work.
- Existing indexes must produce an explicit `无需重建` message.
- Duplicate cleanup logs inspection start, expected rows, batch progress, and
  actual-versus-expected completion. It keeps the greatest `id` per declared
  business key.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Provider exception before retry limit | Warning with attempt/limit and wait |
| Provider exception at retry limit | Error, re-raise, non-zero caller exit |
| First positive page `< requested limit` | Adapt page size and keep fetching |
| Empty page | End pagination normally |
| Cleanup query fails in strict mode | Raise `RuntimeError`; do not hide it |
| Deleted rows differ from expected | Warning; strict mode raises |
| Scope filter has an invalid identifier/value | Reject before SQL execution |

### 5. Good/Base/Bad Cases

- Good: `cyq_chips` returns `6000, 6000, ..., 2344`; every page is logged,
  pagination exits, and duplicate cleanup reports exact progress.
- Base: a one-page endpoint logs one call, one total summary, and its indexes.
- Bad: log only a connection error while sleeping/retrying indefinitely, or
  run one large `DELETE ... NOT IN (...)` with no progress.

### 6. Tests Required

- Unit: configured retry bound is exact and final failure propagates.
- Unit: smaller first page changes the effective page limit and pagination
  continues until a smaller/empty terminal page.
- Unit: all batch-template labels render the correct date/code/source scope.
- Unit: duplicate deletion selects explicit old IDs and never emits `NOT IN`.
- Live smoke: one bounded code/date scope exits, has zero business-key
  duplicates, and leaves no active database statement.

### 7. Wrong vs Correct

#### Wrong

```python
while True:
    try:
        return provider()
    except Exception:
        pass
```

#### Correct

```python
for attempt in range(1, retry_limit + 1):
    try:
        return provider()
    except Exception:
        if attempt == retry_limit:
            raise
        logging.warning("bounded retry with visible attempt and wait")
```

---

## Log levels

- `INFO`: lifecycle, per-call scope/counts, pagination adaptation, indexes,
  cleanup progress.
- `SUCCESS`: endpoint start and verified cleanup completion.
- `WARNING`: retryable provider failures, empty/ambiguous responses, detected
  duplicate rows, and non-strict count mismatches.
- `ERROR`: terminal provider failure, database write/cleanup failure, or any
  exception that will propagate to the caller.

## Secrets

Never log tokens, passwords, cookies, authorization headers, full environment
variables, or unmasked connection strings. Log only masked engine identity,
endpoint/table/code/date scope, counters, and exception class/message after
the normal secret-safe logging boundary.
