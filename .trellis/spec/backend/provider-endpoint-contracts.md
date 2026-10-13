# Provider Endpoint Contracts

> Official provider documentation is the first source for endpoint behavior.

## Scenario: Add Or Correct A Tushare Endpoint

### 1. Scope / Trigger

Apply this contract before changing a Tushare endpoint's request arguments,
pagination, rate handling, date scope, field mapping, or update schedule.

### 2. Signatures

```python
def ts2db_init(self) -> None: ...
def ts2db_get_data(self) -> pandas.DataFrame: ...
```

The endpoint owns its documented `one_time_rows_limit`; the shared pagination
layer only provides a runtime fallback when the service returns a different
positive cap.

### 3. Contracts

- Open the official endpoint page before implementation and record its URL in
  the endpoint or focused test.
- Verify required request parameters, maximum rows per call, supported date
  filters, update time, points/permission notes, and output fields.
- Set the endpoint's page limit directly from the current official document.
- Use `offset += documented_limit` until a page is smaller than that limit.
- Capture that configured limit after `ts2db_init()` and restore it whenever a
  new code/date pagination scope starts at offset zero.
- A runtime cap inferred from a short response is scope-local. It must not
  reduce the first request made for the next code, date, or list status.
- Treat runtime observation as corroboration, not a substitute for the
  provider contract.

For `cyq_chips`, official `doc_id=294` requires `limit=6000`; a wide date range
must request offsets `0, 6000, 12000, ...` until the final short page.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Local comment disagrees with official docs | Correct code/comment from the official page |
| Endpoint inherits a larger generic limit | Override it in `ts2db_init()` |
| Full page equals documented maximum | Continue at the next offset |
| Final page is smaller than maximum | Stop normally after writing it |
| Service returns a smaller positive cap | Shared adaptive pagination may lower the current scope only |
| First code has only three rows | Next code still starts with the documented maximum |

### 5. Good / Base / Bad Cases

- Good: `cyq_chips` starts with 6000 and fetches all pages.
- Base: a one-page result below 6000 is written once and terminates.
- Bad: request 50,000, receive 6000, and assume the response is complete.

### 6. Tests Required

- Assert the endpoint sets the documented limit during `ts2db_init()`.
- Assert provider kwargs contain the same `limit` and current `offset`.
- Assert a full page continues and a short page terminates.
- Assert a sparse scope cannot leak its inferred page size into the next
  pagination scope.
- For a live diagnosis, compare page sizes and offsets with the official
  contract without exposing credentials.

### 7. Wrong vs Correct

#### Wrong

```python
# Generic default; not the provider contract.
self.params.one_time_rows_limit = 50_000
```

#### Correct

```python
# https://tushare.pro/document/2?doc_id=294
self.params.one_time_rows_limit = 6_000
```
