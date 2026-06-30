from __future__ import annotations

from dataclasses import dataclass
from typing import Any


BASE_URL = "https://eodhd.com/api"
MAX_RESEARCH_SYMBOLS = 2000
MAX_EXPENSIVE_SYMBOLS = 2000
LIVE_OHLCV_SYMBOLS_PER_REQUEST = 20


@dataclass(frozen=True)
class ChoiceSpec:
    value: str
    label: str

    def as_dict(self) -> dict[str, str]:
        return {"value": self.value, "label": self.label}


@dataclass(frozen=True)
class ParamSpec:
    """Describe one endpoint parameter rendered by the UI and validated by Python.

    Input: official endpoint parameter semantics and app-level guardrails.
    Output: immutable metadata used by the frontend and request validator.
    Flow: docs evidence -> parameter spec -> form rendering -> validation/codegen.
    """

    name: str
    label: str
    kind: str
    required: bool = False
    default: str | int | bool = ""
    choices: tuple[ChoiceSpec, ...] = ()
    placeholder: str = ""
    help_text: str = ""
    max_length: int | None = None
    min_value: int | None = None
    max_value: int | None = None
    max_items: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "default": self.default,
            "choices": [choice.as_dict() for choice in self.choices],
            "placeholder": self.placeholder,
            "help_text": self.help_text,
            "max_length": self.max_length,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "max_items": self.max_items,
        }


@dataclass(frozen=True)
class EndpointSpec:
    """Document one implemented or inventoried EODHD endpoint.

    Input: endpoint id, docs evidence, subscription evidence, and UI params.
    Output: endpoint registry row used by validation, URL building, UI, and docs.
    Flow: official docs -> registry -> request model -> code generation/execution.
    """

    endpoint_id: str
    label: str
    category: str
    path_pattern: str
    description: str
    official_doc_url: str
    plan_evidence: str
    call_cost_note: str
    formats: tuple[str, ...] = ("json",)
    default_format: str = "json"
    params: tuple[ParamSpec, ...] = ()
    implemented: bool = True
    implementation_note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.endpoint_id,
            "label": self.label,
            "category": self.category,
            "path_pattern": self.path_pattern,
            "description": self.description,
            "official_doc_url": self.official_doc_url,
            "plan_evidence": self.plan_evidence,
            "call_cost_note": self.call_cost_note,
            "formats": list(self.formats),
            "default_format": self.default_format,
            "params": [param.as_dict() for param in self.params],
            "implemented": self.implemented,
            "implementation_note": self.implementation_note,
        }


def choices(*values: str) -> tuple[ChoiceSpec, ...]:
    return tuple(ChoiceSpec(value=value, label=value) for value in values)


def labeled_choices(items: tuple[tuple[str, str], ...]) -> tuple[ChoiceSpec, ...]:
    return tuple(ChoiceSpec(value=value, label=label) for value, label in items)


COMMON_EQUITY_SYMBOLS = ParamSpec(
    name="symbols",
    label="Symbol / provider_symbol",
    kind="symbol_list",
    required=True,
    default="AAPL.US",
    placeholder="AAPL.US, MSFT.US",
    help_text="Use EODHD provider symbols. US suffix is added automatically when missing.",
    max_items=MAX_RESEARCH_SYMBOLS,
)

INTRADAY_EQUITY_SYMBOLS = ParamSpec(
    name="symbols",
    label="Symbol / provider_symbol",
    kind="symbol_list",
    required=True,
    default="AAPL.US",
    placeholder="AAPL.US, MSFT.US",
    help_text="Use EODHD provider symbols. Intraday is capped because each request costs 5 calls.",
    max_items=MAX_EXPENSIVE_SYMBOLS,
)

COMMON_DATE_FROM = ParamSpec(
    name="date_from",
    label="From",
    kind="date",
    required=True,
    default="2024-01-01",
)

COMMON_DATE_TO = ParamSpec(
    name="date_to",
    label="To",
    kind="date",
    required=True,
    default="2024-01-31",
)

COMMON_OPTIONAL_DATE_FROM = ParamSpec(
    name="date_from",
    label="From",
    kind="date",
    default="2024-01-01",
)

COMMON_OPTIONAL_DATE_TO = ParamSpec(
    name="date_to",
    label="To",
    kind="date",
    default="2024-01-31",
)

EXCHANGE_PARAM = ParamSpec(
    name="exchange",
    label="Exchange",
    kind="exchange",
    required=True,
    default="US",
    placeholder="US",
)

SUPPORTED_ENDPOINTS: dict[str, EndpointSpec] = {
    "historical_eod": EndpointSpec(
        endpoint_id="historical_eod",
        label="Historical EOD price",
        category="Market Data",
        path_pattern="/eod/{provider_symbol}",
        description="Historical daily, weekly, or monthly OHLCV for one or a few symbols.",
        official_doc_url="https://eodhd.com/financial-apis/api-for-historical-data-and-volumes",
        plan_evidence=(
            "Official docs list this endpoint in All-In-One, EOD Historical Data: "
            "All World, EOD+Intraday: All World Extended, and limited Free plan."
        ),
        call_cost_note="1 API call per symbol request, any history length.",
        formats=("json", "csv"),
        params=(
            COMMON_EQUITY_SYMBOLS,
            COMMON_DATE_FROM,
            COMMON_DATE_TO,
            ParamSpec("period", "Period", "select", default="d", choices=choices("d", "w", "m")),
            ParamSpec("order", "Order", "select", default="a", choices=choices("a", "d")),
            ParamSpec(
                "adjustment",
                "Adjustment",
                "select",
                default="eodhd_default",
                choices=labeled_choices((("eodhd_default", "Raw OHLC + adjusted_close"),)),
            ),
        ),
    ),
    "intraday": EndpointSpec(
        endpoint_id="intraday",
        label="Intraday historical bars",
        category="Market Data",
        path_pattern="/intraday/{provider_symbol}",
        description="Delayed/finalized intraday OHLCV bars for short-horizon research.",
        official_doc_url="https://eodhd.com/financial-apis/intraday-historical-data-api",
        plan_evidence="Official docs list Intraday in EOD+Intraday - All World Extended and All-In-One.",
        call_cost_note="5 API calls per request; app caps each request to a few symbols.",
        formats=("json", "csv"),
        params=(
            INTRADAY_EQUITY_SYMBOLS,
            ParamSpec(
                "interval",
                "Interval",
                "select",
                default="5m",
                choices=choices("1m", "5m", "1h"),
                help_text="Official maximum ranges: 1m 120 days, 5m 600 days, 1h 7200 days.",
            ),
            ParamSpec(
                "from_timestamp",
                "From UTC timestamp",
                "number",
                default="",
                placeholder="1627896900",
                min_value=0,
            ),
            ParamSpec(
                "to_timestamp",
                "To UTC timestamp",
                "number",
                default="",
                placeholder="1630575300",
                min_value=0,
            ),
            ParamSpec(
                "split_datetime",
                "Split date/time fields",
                "checkbox",
                default=False,
                help_text="Maps to split-dt=1 in official docs.",
            ),
        ),
    ),
    "live_ohlcv": EndpointSpec(
        endpoint_id="live_ohlcv",
        label="Live delayed OHLCV",
        category="Market Data",
        path_pattern="/real-time/{provider_symbol}",
        description="Latest delayed OHLCV snapshot for one or a small watchlist.",
        official_doc_url="https://eodhd.com/financial-apis/live-ohlcv-stocks-api",
        plan_evidence=(
            "Official docs list Live OHLCV in All-In-One, EOD Historical Data: "
            "All World, EOD+Intraday: All World Extended and Free plans."
        ),
        call_cost_note=(
            "1 API call per ticker; generated URLs group symbols into batches of 20 because "
            "EODHD recommends 15-20 tickers per request."
        ),
        formats=("json", "csv"),
        params=(
            ParamSpec(
                name="symbols",
                label="Symbols",
                kind="symbol_list",
                required=True,
                default="AAPL.US, MSFT.US",
                max_items=MAX_RESEARCH_SYMBOLS,
                help_text=(
                    "Code generation accepts up to 2000 symbols; generated requests are grouped "
                    "into 20-ticker batches using the official s= parameter."
                ),
            ),
        ),
    ),
    "bulk_last_day_eod": EndpointSpec(
        endpoint_id="bulk_last_day_eod",
        label="Bulk last-day EOD",
        category="Market Data",
        path_pattern="/eod-bulk-last-day/{exchange}",
        description="One-day EOD rows for an exchange, optionally narrowed to a small symbol list.",
        official_doc_url="https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends",
        plan_evidence=(
            "Official docs list this endpoint in All-In-One, EOD Historical Data: "
            "All World, and EOD+Intraday: All World Extended."
        ),
        call_cost_note=(
            "100 API calls for an entire exchange, plus one extra API call per ticker "
            "when the symbols option is used."
        ),
        formats=("json", "csv"),
        params=(
            EXCHANGE_PARAM,
            ParamSpec(
                name="symbols",
                label="Symbols",
                kind="bulk_symbol_list",
                default="AAPL, MSFT",
                max_items=MAX_RESEARCH_SYMBOLS,
                help_text="Required unless full exchange is explicitly enabled.",
            ),
            ParamSpec("trade_date", "Bulk date", "date", default=""),
            ParamSpec("date_from", "Bulk from", "date", default=""),
            ParamSpec("date_to", "Bulk to", "date", default=""),
            ParamSpec(
                "allow_full_exchange",
                "Allow full exchange request",
                "checkbox",
                default=False,
                help_text="Full exchange requests cost 100 API calls and may be large.",
            ),
        ),
    ),
    "dividends": EndpointSpec(
        endpoint_id="dividends",
        label="Historical dividends",
        category="Corporate Actions",
        path_pattern="/div/{provider_symbol}",
        description="Dividend history for one or a few symbols.",
        official_doc_url="https://eodhd.com/financial-apis/api-splits-dividends",
        plan_evidence=(
            "Official docs list Corporate Actions in All-In-One, EOD Historical Data: "
            "All World, EOD+Intraday: All World Extended, and Free plan limited history."
        ),
        call_cost_note="1 API call per symbol request.",
        formats=("json", "csv"),
        params=(COMMON_EQUITY_SYMBOLS, COMMON_OPTIONAL_DATE_FROM, COMMON_OPTIONAL_DATE_TO),
    ),
    "splits": EndpointSpec(
        endpoint_id="splits",
        label="Historical splits",
        category="Corporate Actions",
        path_pattern="/splits/{provider_symbol}",
        description="Split history for one or a few symbols.",
        official_doc_url="https://eodhd.com/financial-apis/api-splits-dividends",
        plan_evidence=(
            "Official docs list Corporate Actions in All-In-One, EOD Historical Data: "
            "All World, EOD+Intraday: All World Extended, and Free plan limited history."
        ),
        call_cost_note="1 API call per symbol request.",
        formats=("json", "csv"),
        params=(COMMON_EQUITY_SYMBOLS, COMMON_OPTIONAL_DATE_FROM, COMMON_OPTIONAL_DATE_TO),
    ),
    "technical": EndpointSpec(
        endpoint_id="technical",
        label="Technical indicators",
        category="Analytics",
        path_pattern="/technical/{provider_symbol}",
        description="EODHD technical indicator series such as SMA, EMA, WMA, RSI, volatility, and MACD.",
        official_doc_url="https://eodhd.com/financial-apis/technical-indicators-api",
        plan_evidence="Official docs list Technical API in All-In-One and EOD+Intraday - All World Extended.",
        call_cost_note="5 API calls per request.",
        formats=("json", "csv"),
        params=(
            ParamSpec(
                name="symbols",
                label="Symbol / provider_symbol",
                kind="symbol_list",
                required=True,
                default="AAPL.US",
                max_items=MAX_EXPENSIVE_SYMBOLS,
            ),
            COMMON_DATE_FROM,
            COMMON_DATE_TO,
            ParamSpec("order", "Order", "select", default="d", choices=choices("a", "d")),
            ParamSpec(
                "function",
                "Function",
                "select",
                default="sma",
                choices=choices(
                    "splitadjusted",
                    "avgvol",
                    "avgvolccy",
                    "sma",
                    "ema",
                    "wma",
                    "volatility",
                    "stoch",
                    "rsi",
                    "stddev",
                    "stochrsi",
                    "slope",
                    "dmi",
                    "adx",
                    "macd",
                    "atr",
                    "cci",
                    "sar",
                    "bbands",
                ),
            ),
            ParamSpec("indicator_period", "Indicator period", "number", default=50, min_value=1, max_value=1000),
            ParamSpec("filter", "Filter", "text", default="", placeholder="last_ema", max_length=80),
            ParamSpec("splitadjusted_only", "Split-adjusted only", "checkbox", default=False),
        ),
    ),
    "screener": EndpointSpec(
        endpoint_id="screener",
        label="Stock market screener",
        category="Discovery",
        path_pattern="/screener",
        description="Filter equity universe by market cap, exchange, sector, industry, signals, and other fields.",
        official_doc_url="https://eodhd.com/financial-apis/stock-market-screener-api",
        plan_evidence="Official docs list Screener API in All-In-One and EOD+Intraday - All World Extended.",
        call_cost_note="5 API calls per request.",
        formats=("json",),
        params=(
            ParamSpec("sort", "Sort", "text", default="market_capitalization.desc", max_length=120),
            ParamSpec(
                "filters",
                "Filters JSON",
                "textarea",
                default='[["exchange","=","us"],["market_capitalization",">",1000000000]]',
                max_length=2000,
                help_text="Official filters array, for example [[\"code\",\"=\",\"AAPL\"]].",
            ),
            ParamSpec("signal", "Signal", "text", default="", placeholder="wallstreet_lo", max_length=80),
            ParamSpec("limit", "Limit", "number", default=10, min_value=1, max_value=100),
            ParamSpec("offset", "Offset", "number", default=0, min_value=0, max_value=10000),
        ),
    ),
    "exchange_symbol_list": EndpointSpec(
        endpoint_id="exchange_symbol_list",
        label="Exchange symbol list",
        category="Exchange & Instruments",
        path_pattern="/exchange-symbol-list/{exchange}",
        description="Currently active tickers by exchange and optional asset type.",
        official_doc_url="https://eodhd.com/financial-apis/covered-tickers-eodhd",
        plan_evidence=(
            "Official covered-tickers docs define this endpoint and parameters; pricing feature list "
            "for EOD+Intraday - All World Extended includes Exchange Symbols List."
        ),
        call_cost_note="1 API call; use preview limits for browser usability.",
        formats=("json",),
        params=(
            EXCHANGE_PARAM,
            ParamSpec(
                "type_filter",
                "Type",
                "select",
                default="all",
                choices=choices("all", "common_stock", "preferred_stock", "stock", "etf", "fund"),
            ),
            ParamSpec("delisted", "Include delisted", "checkbox", default=False),
        ),
    ),
    "instrument_search": EndpointSpec(
        endpoint_id="instrument_search",
        label="Instrument search",
        category="Exchange & Instruments",
        path_pattern="/search/{query_string}",
        description="Search active stocks, ETFs, funds, bonds, indices, and crypto assets.",
        official_doc_url="https://eodhd.com/financial-apis/search-api-for-stocks-etfs-mutual-funds",
        plan_evidence=(
            "Official docs list Search API in All-In-One, EOD Historical Data: "
            "All World, EOD+Intraday: All World Extended, Fundamentals Data Feed, and Free plans."
        ),
        call_cost_note="1 API call per request.",
        formats=("json",),
        params=(
            ParamSpec("search_query", "Search query", "text", required=True, default="AAPL", max_length=80),
            EXCHANGE_PARAM,
            ParamSpec(
                "type_filter",
                "Type",
                "select",
                default="all",
                choices=choices("all", "stock", "etf", "fund", "bond", "index", "crypto"),
            ),
            ParamSpec("limit", "Limit", "number", default=15, min_value=1, max_value=100),
        ),
    ),
    "exchanges_list": EndpointSpec(
        endpoint_id="exchanges_list",
        label="Supported exchanges",
        category="Exchange & Instruments",
        path_pattern="/exchanges-list/",
        description="Full list of exchanges and virtual asset venues supported by EODHD.",
        official_doc_url="https://eodhd.com/financial-apis/exchanges-api-list-of-tickers-and-trading-hours",
        plan_evidence=(
            "Official docs list Exchanges API in All-In-One, EOD Historical Data: "
            "All World, EOD+Intraday: All World Extended, Fundamentals Data Feed, and Free plans."
        ),
        call_cost_note="1 API call.",
        formats=("json",),
    ),
    "exchange_details": EndpointSpec(
        endpoint_id="exchange_details",
        label="Exchange trading hours/holidays",
        category="Exchange & Instruments",
        path_pattern="/v2/exchange-details/{exchange}",
        description="Trading hours, extended sessions, and holiday calendar for a requested exchange.",
        official_doc_url="https://eodhd.com/financial-apis/exchanges-api-trading-hours-and-stock-market-holidays",
        plan_evidence=(
            "Official docs list Stock Market Trading Hours and Holidays API in All-In-One "
            "and EOD+Intraday - All World Extended."
        ),
        call_cost_note="5 API calls per request.",
        formats=("json",),
        params=(EXCHANGE_PARAM,),
    ),
    "symbol_change_history": EndpointSpec(
        endpoint_id="symbol_change_history",
        label="US symbol change history",
        category="Exchange & Instruments",
        path_pattern="/symbol-change-history",
        description="US ticker rename history for portfolio reconciliation and point-in-time research.",
        official_doc_url="https://eodhd.com/financial-apis/us-stock-symbol-rename-history-api",
        plan_evidence="Official docs list this API in All-In-One and EOD+Intraday - All World Extended.",
        call_cost_note="5 API calls per request.",
        formats=("json", "csv"),
        params=(
            ParamSpec("date_from", "From", "date", default="2024-01-01"),
            ParamSpec("date_to", "To", "date", default=""),
        ),
    ),
    "id_mapping": EndpointSpec(
        endpoint_id="id_mapping",
        label="ID mapping",
        category="Exchange & Instruments",
        path_pattern="/id-mapping",
        description="Resolve CUSIP, ISIN, FIGI, LEI, CIK, exchange, or EODHD symbol identifiers.",
        official_doc_url="https://eodhd.com/financial-apis/id-mapping-api-cusip-isin-figi-lei-cik-%E2%86%94-symbol",
        plan_evidence=(
            "Official docs list ID Mapping API in All-In-One, EOD Historical Data - All World, "
            "EOD+Intraday - All World Extended, Fundamentals Data Feed, and Free plans."
        ),
        call_cost_note="1 API call per request.",
        formats=("json",),
        params=(
            ParamSpec(
                "filter_name",
                "Filter field",
                "select",
                default="symbol",
                choices=choices("symbol", "isin", "cusip", "figi", "lei", "cik", "ex"),
            ),
            ParamSpec("filter_value", "Filter value", "text", required=True, default="AAPL.US", max_length=80),
            ParamSpec("limit", "Limit", "number", default=100, min_value=1, max_value=500),
            ParamSpec("offset", "Offset", "number", default=0, min_value=0, max_value=100000),
        ),
    ),
}


INVENTORY_ONLY_ENDPOINTS: dict[str, EndpointSpec] = {
    "fundamentals": EndpointSpec(
        endpoint_id="fundamentals",
        label="Fundamental data",
        category="Not in 29.99 Extended",
        path_pattern="/fundamentals/{provider_symbol}",
        description="Large company, ETF, mutual fund, and index fundamentals object.",
        official_doc_url="https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds",
        plan_evidence="Pricing lists Fundamentals Data Feed as a separate 59.99 plan, not the 29.99 Extended plan.",
        call_cost_note="10 API calls per request per API limits docs.",
        implemented=False,
        implementation_note="Inventory only for this app until subscription is expanded.",
    ),
    "calendar_news": EndpointSpec(
        endpoint_id="calendar_news",
        label="Calendar and news APIs",
        category="Marketplace/add-on",
        path_pattern="/calendar/* and /news",
        description="Upcoming earnings, IPO, splits, dividends, economic events, and news feeds.",
        official_doc_url="https://eodhd.com/pricing",
        plan_evidence="Pricing lists Corporate Events Calendar & News API as a separate 19.99 marketplace product.",
        call_cost_note="Depends on marketplace product; not enabled by default plan evidence.",
        implemented=False,
        implementation_note="Inventory only; not whitelisted for 29.99 Extended.",
    ),
    "historical_market_cap": EndpointSpec(
        endpoint_id="historical_market_cap",
        label="Historical market capitalization",
        category="Not confirmed for 29.99 Extended",
        path_pattern="/historical-market-cap/{provider_symbol}",
        description="Historical market cap series.",
        official_doc_url="https://eodhd.com/financial-apis/historical-market-capitalization-api",
        plan_evidence="Official API docs list it in Fundamental & Economic Data; current pricing separates fundamentals from Extended.",
        call_cost_note="Not implemented until plan access is confirmed.",
        implemented=False,
        implementation_note="Inventory only; avoid whitelisting without clear 29.99 Extended evidence.",
    ),
}


def get_endpoint(endpoint_id: str) -> EndpointSpec:
    try:
        return SUPPORTED_ENDPOINTS[endpoint_id]
    except KeyError as exc:
        raise KeyError(f"unsupported endpoint: {endpoint_id}") from exc


def endpoint_payload() -> list[dict[str, Any]]:
    """Return implemented endpoint metadata for the frontend."""
    return [spec.as_dict() for spec in SUPPORTED_ENDPOINTS.values()]


def inventory_payload() -> list[dict[str, Any]]:
    """Return inventory-only endpoint metadata for docs/status views."""
    return [spec.as_dict() for spec in INVENTORY_ONLY_ENDPOINTS.values()]
