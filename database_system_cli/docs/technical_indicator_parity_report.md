# EODHD Technical Indicator Parity Report

## Scope

This report records the bounded provider comparison run completed on 2026-07-11. It is a
formula-parity diagnostic, not a source for stored indicators and not an ingestion workflow.

```bash
poetry run j21 research technical-validate \
  --symbols AAPL.US,META.US,SPY.US \
  --from 2024-01-01 --to 2024-03-31 \
  --max-api-units 200 --output json
```

## Result

| Provider symbol | SMA 20 | EMA 20 | RSI 14 |
| --- | --- | --- | --- |
| `AAPL.US` | Pass | Pass | Pass |
| `META.US` | Pass | Pass | Pass |
| `SPY.US` | Pass | Pass | Pass |

- Overall status: `pass` (`9/9` comparisons).
- Weighted EODHD units consumed: `45` (`3 symbols x 3 requests x 5 units`).
- Absolute-error tolerance: `0.0002`.
- Maximum observed absolute error across the comparison matrix: less than `0.00005`.
- The residual difference is consistent with the provider response being rounded to four decimal
  places; no local formula was changed from provider output.

## Interpretation

The result supports the local SMA20, EMA20, and Wilder RSI14 formulas for the tested symbols and
window. It does not prove parity for every security, date, or indicator. SMA50/200, Bollinger,
MACD, volume SMA, and volatility remain covered by deterministic local fixtures rather than by
additional paid API calls.

Official endpoint reference: [EODHD Technical Indicators API](https://eodhd.com/financial-apis/technical-indicators-api).
