# Official Endpoint Notes

This document records the official public documentation basis for the endpoint whitelist in `database_app`.

## Subscription Context

The user-reported plan is `EOD+Intraday - All World Extended` at 29.99. The EODHD pricing page lists this plan and the official API docs for the implemented endpoints below list the same plan or the broader EOD/EOD+Intraday plan family.

Official pricing:

- https://eodhd.com/pricing

Official API documentation hub and endpoint list:

- https://eodhd.com/financial-apis/

Official Postman collection entry in the EODHD docs:

- https://eodhd.com/financial-apis/

The public docs hub is the endpoint catalog used for this app. A public OpenAPI file was not found in the official docs during this pass; EODHD points developers to the full docs pages, code examples, SDK pages, and Postman collection.

API usage limit reference:

- https://eodhd.com/financial-apis/api-limits

Important cost notes from the API limits docs:

- Paid plans default to 100,000 API calls per user per day.
- Bulk API for an entire exchange costs 100 API calls.
- Bulk API with `symbols` costs 100 plus one call per ticker.
- Several analytics/metadata endpoints consume 5 calls per request.

## Implemented Whitelist

All implemented endpoints are listed in `src/eodhd_codegen_app/endpoints.py` and exposed through `/api/endpoints`.

| Endpoint id | Official docs | Implemented path | Plan evidence | Cost note |
| --- | --- | --- | --- | --- |
| `historical_eod` | https://eodhd.com/financial-apis/api-for-historical-data-and-volumes | `/api/eod/{provider_symbol}` | Docs list `EOD+Intraday - All World Extended` among supported plans. | 1 API call per symbol request. |
| `intraday` | https://eodhd.com/financial-apis/intraday-historical-data-api | `/api/intraday/{provider_symbol}` | Docs list `EOD+Intraday - All World Extended`. | 5 API calls per request. |
| `live_ohlcv` | https://eodhd.com/financial-apis/live-ohlcv-stocks-api | `/api/real-time/{provider_symbol}` | Docs list `EOD+Intraday - All World Extended`. | 1 API call per ticker. |
| `bulk_last_day_eod` | https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends | `/api/eod-bulk-last-day/{exchange}` | Docs list `EOD+Intraday - All World Extended`. | 100 calls for full exchange; 100 + one per ticker with `symbols`. |
| `dividends` | https://eodhd.com/financial-apis/api-splits-dividends | `/api/div/{provider_symbol}` | Corporate actions docs list `EOD+Intraday - All World Extended`. | 1 API call per symbol request. |
| `splits` | https://eodhd.com/financial-apis/api-splits-dividends | `/api/splits/{provider_symbol}` | Corporate actions docs list `EOD+Intraday - All World Extended`. | 1 API call per symbol request. |
| `technical` | https://eodhd.com/financial-apis/technical-indicators-api | `/api/technical/{provider_symbol}` | Docs list `EOD+Intraday - All World Extended`. | 5 API calls per request. |
| `screener` | https://eodhd.com/financial-apis/stock-market-screener-api | `/api/screener` | Docs list `EOD+Intraday - All World Extended`. | 5 API calls per request. |
| `exchange_symbol_list` | https://eodhd.com/financial-apis/covered-tickers-eodhd | `/api/exchange-symbol-list/{exchange}` | Official supported-tickers docs define this endpoint and parameters; pricing feature list for `EOD+Intraday - All World Extended` includes Exchange Symbols List. | 1 API call; browser preview caps rows. |
| `instrument_search` | https://eodhd.com/financial-apis/search-api-for-stocks-etfs-mutual-funds | `/api/search/{query_string}` | Docs list `EOD+Intraday - All World Extended`. | 1 API call per request. |
| `exchanges_list` | https://eodhd.com/financial-apis/exchanges-api-list-of-tickers-and-trading-hours | `/api/exchanges-list/` | Docs list `EOD+Intraday - All World Extended`. | 1 API call. |
| `exchange_details` | https://eodhd.com/financial-apis/exchanges-api-trading-hours-and-stock-market-holidays | `/api/v2/exchange-details/{exchange}` | Docs list `EOD+Intraday - All World Extended`. | 5 API calls per request. |
| `symbol_change_history` | https://eodhd.com/financial-apis/us-stock-symbol-rename-history-api | `/api/symbol-change-history` | Docs list `EOD+Intraday - All World Extended`. | 5 API calls per request. |
| `id_mapping` | https://eodhd.com/financial-apis/id-mapping-api-cusip-isin-figi-lei-cik-%E2%86%94-symbol | `/api/id-mapping` | Docs list `EOD+Intraday - All World Extended`. | 1 API call per request. |

## App-Level Guardrails

These constraints are intentionally stricter than the EODHD protocol because the app is an interactive research tool, not a bulk downloader:

- Historical EOD: max 2000 symbols for code generation; max 3660 days.
- Intraday: max 2000 symbols for code generation; interval choices `1m`, `5m`, `1h`; timestamp ranges capped according to official depth notes.
- Live OHLCV: max 2000 symbols for code generation, grouped into 20-symbol requests because EODHD recommends 15-20 tickers per request.
- Bulk EOD: max 2000 symbols unless `Allow full exchange request` is checked.
- Technical indicators: max 2000 symbols for code generation.
- Screener: `filters` must be a JSON array; `limit` capped at 100.
- Local preview execution: capped at 50 generated HTTP requests; larger lists should use generated code outside the preview UI.
- Preview rows: capped at 500 in the table and 5000 returned rows for browser export.
- JSON-only endpoints reject CSV before URL generation.

## Inventory-Only Endpoints

These endpoint groups are tracked but not executable in the current app whitelist.

| Endpoint group | Official docs | Status | Reason |
| --- | --- | --- | --- |
| Fundamentals | https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds | inventory only | Pricing shows Fundamentals Data Feed as a separate 59.99 plan, not the 29.99 Extended plan. |
| Calendar and news | https://eodhd.com/pricing | inventory only | Pricing lists Corporate Events Calendar & News API as a separate marketplace product. |
| Historical market cap | https://eodhd.com/financial-apis/historical-market-capitalization-api | inventory only | Official page is under Fundamental & Economic Data; 29.99 Extended access was not clear enough to whitelist. |
| Official index constituents | https://eodhd.com/financial-apis/sp-and-dow-jones-indices-historical-constituents-data-api | inventory only | EODHD presents this as an indices historical constituents product under Fundamental & Economic Data/marketplace; the app does not label Filtered Pools as real index membership. |

If the user's subscription later adds these products, they can be promoted from `INVENTORY_ONLY_ENDPOINTS` to `SUPPORTED_ENDPOINTS` with tests and docs.

## Universe Sources In The App

The stock workflow uses two official EODHD-supported sources:

- `exchange_symbol_list`: load tickers by exchange and type.
- `screener`: load EODHD Filtered Pools such as US large cap or US mega cap.

Filtered Pools are not official S&P 500, Dow Jones, or Nasdaq 100 constituents. The UI and docs keep those distinct because the official index-constituents product is not whitelisted for the user's 29.99 Extended plan in this app.

## Wind API Research Notes

The app is inspired by Wind API tooling style, not Wind endpoint semantics.

Official public Wind pages confirm that Wind Financial Terminal covers equity, bond, fund, index, FX, commodity, financial derivatives, and macro workflows, provides an Excel add-in, and advertises a Client API for accessing Wind data with a few lines of code:

- https://www.wind.com.cn/portal/en/WFT/index.html
- https://www.wind.com.cn/portal/en/WDS/index.html

Design takeaways used here:

- Put asset and endpoint choices first.
- Render endpoint-specific parameters instead of one generic text box.
- Generate copyable code in multiple languages.
- Keep data preview and export near generated code.
- Reserve future asset buttons even when the current executable whitelist focuses on equity research.

The public Wind pages do not provide a stable text specification for the exact WAPI code generator UI, so the app uses Wind as a workflow reference only. EODHD endpoint behavior and subscription gating are based on official EODHD documentation above.
