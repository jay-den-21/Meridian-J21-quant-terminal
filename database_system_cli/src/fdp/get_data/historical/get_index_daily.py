"""Reusable script entrypoint for historical benchmark index daily OHLCV."""

from datetime import date
from typing import Any

from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.get_data.historical.base import HistoricalDailyJob, ResolvedHistoricalOptions
from fdp.sources.eodhd.ingest import (
    DEFAULT_INDEX_PROVIDER_SYMBOLS,
    HistoricalDailyPriceLoadResult,
    load_index_daily_prices,
)
from fdp.sources.eodhd.ingest.common import (
    create_task_run,
    index_instrument_rows,
    load_active_instruments_by_provider_symbols,
    split_provider_symbol,
)
from fdp.storage.upsert import build_instrument_upsert

DEFAULT_PROVIDER_SYMBOLS = tuple(DEFAULT_INDEX_PROVIDER_SYMBOLS)
DEFAULT_DATE_FROM: date | None = None
DEFAULT_DATE_TO: date | None = None
DEFAULT_CURRENCY = "USD"


class IndexDailyJob(HistoricalDailyJob):
    """Human-maintainable benchmark index daily job."""

    job_key = "ingest.indices"
    job_name = "eodhd_index_daily_price"

    def __init__(
        self,
        *,
        currency: str = DEFAULT_CURRENCY,
        currency_source: str = "job_default",
    ) -> None:
        super().__init__(
            asset_types=("index",),
            default_symbols=DEFAULT_PROVIDER_SYMBOLS,
            default_date_from=DEFAULT_DATE_FROM,
            default_date_to=DEFAULT_DATE_TO,
            default_instrument_status="active",
            job_module="fdp.get_data.historical.get_index_daily",
        )
        self.currency = currency.upper()
        self.currency_source = currency_source

    def _resolve_options(self, **kwargs: Any) -> ResolvedHistoricalOptions:
        options = super()._resolve_options(**kwargs)
        options.parameters["provider_symbols"] = options.parameters.pop("symbols")
        options.parameter_sources["provider_symbols"] = options.parameter_sources.pop("symbols")
        options.parameters["currency"] = self.currency
        options.parameter_sources["currency"] = self.currency_source
        return options

    def _preflight_instruments(
        self,
        connection: Any,
        options: ResolvedHistoricalOptions,
    ) -> list[dict[str, object]]:
        return [
            {
                "symbol": split_provider_symbol(provider_symbol)[0],
                "provider_symbol": provider_symbol,
            }
            for provider_symbol in options.symbols
        ]

    def _prepare_run(
        self,
        connection: Any,
        options: ResolvedHistoricalOptions,
    ) -> tuple[int, list[dict[str, object]]]:
        run_id = create_task_run(
            connection,
            market=options.market,
            job_name=self.job_name,
            target_table="index_daily_price",
            date_from=options.date_from,
            date_to=options.date_to,
        )
        connection.execute(
            build_instrument_upsert(
                index_instrument_rows(
                    options.symbols,
                    market=options.market,
                    currency=self.currency,
                )
            )
        )
        instruments = load_active_instruments_by_provider_symbols(
            connection,
            provider_symbols=options.symbols,
            market=options.market,
        )
        return run_id, instruments


def get_index_daily(
    connection: Connection,
    client: EodhdClient,
    *,
    provider_symbols: list[str] | None = None,
    date_from: date,
    date_to: date,
    market: str = "US",
    currency: str = "USD",
) -> HistoricalDailyPriceLoadResult:
    """Load benchmark index daily bars.

    Input: database connection, EODHD client, index provider symbols, and date range.
    Output: index daily price load summary.
    Flow: provider symbols -> index instruments -> EODHD historical EOD -> daily price upsert.
    """
    return load_index_daily_prices(
        connection,
        client,
        provider_symbols=provider_symbols or list(DEFAULT_INDEX_PROVIDER_SYMBOLS),
        date_from=date_from,
        date_to=date_to,
        market=market,
        currency=currency,
    )
