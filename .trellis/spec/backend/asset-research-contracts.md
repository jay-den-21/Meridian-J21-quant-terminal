# Asset And Research Contracts

## 1. Scope / Trigger

Apply this spec when changing canonical `instrument.asset_type`, a split daily-price table,
local indicators, EODHD Technical parity, or CLI/HTML documentation coverage. An instrument type
can be corrected after prices were written, so metadata correctness alone does not prove physical
table correctness.

## 2. Signatures

```text
j21 migrate daily-price-asset-types --phase plan
j21 migrate daily-price-asset-types --phase execute --chunk-size N --execute --yes
j21 research technical-validate --symbols ... --from ... --to ... --max-api-units <=200
j21 validate docs-staleness --root <repo-or-cli-root>

plan_daily_price_asset_type_reconcile(connection) -> AssetTypeReconcilePlan
reconcile_daily_price_asset_types(engine, chunk_size, max_chunks) -> AssetTypeReconcileResult
calculate_daily_indicators(rows, adjusted=True) -> enriched rows
```

## 3. Contracts

- Canonical types are `stock/etf/fund/index/forex/crypto`; each maps to exactly one daily table.
- Reconcile reads the current instrument type, copies the complete non-PK price row, verifies
  symbol/OHLCV/currency/source payload, then deletes the source in the same transaction.
- Existing same-key target payloads may be reused only when comparison fields are identical.
- Indicator output is ephemeral. Adjusted mode scales OHLC with `adjusted_close / close` and keeps
  the source rows unchanged.
- EODHD Technical requests reserve 5 weighted units per attempt before HTTP and never exceed 200.
- JSON CLI mode writes progress to stderr and one JSON document to stdout.
- Docs staleness compares current Typer leaves with `docs/cli_commands.md` and byte-compares
  renderer output for managed Markdown/HTML pairs.

## 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| execute without `--execute --yes` | Typer parameter error; no DB write |
| target key exists with different payload | rollback chunk; do not overwrite or delete source |
| instrument type changes during chunk | rollback chunk |
| partial run reaches `max_chunks` | return `partial`; rerun resumes from remaining rows |
| adjusted row has raw close zero | `ValueError` |
| Technical matrix exceeds budget | reject before API request |
| CLI leaf missing from tutorial or HTML differs | docs-staleness exits nonzero |

## 5. Good / Base / Bad Cases

- Good: `stock -> etf` rows have no target rows; copy, verify, delete, final plan is zero.
- Base: no mismatch rows; plan and execute are idempotent no-ops.
- Bad: target has a different close for the same instrument/date; fail the transaction and retain
  both facts for operator review.

## 6. Tests Required

- Compile all quality queries against MySQL dialect and assert table/master join semantics.
- Test plan totals, payload conflict detection, CLI confirmation gate, and final plan zero on live
  smoke data when operator-authorized.
- Test indicator warm-ups, adjusted/raw, flat RSI, MACD seed, invalid inputs, and provider parity.
- Test JSON progress channel separation and exact docs-staleness command coverage.

## 7. Wrong vs Correct

### Wrong

```text
UPDATE instrument SET asset_type='etf';
# Assume old stock_daily_price rows moved automatically.
```

### Correct

```text
update instrument metadata
-> j21 migrate daily-price-asset-types --phase plan
-> review source/target groups
-> execute copy + payload verify + source delete
-> plan again and require total_rows=0
```
