"""Database-backed daily price reader for research code."""

from datetime import date
from typing import Any, Sequence

from sqlalchemy import Table, or_, select
from sqlalchemy.engine import Connection
from sqlalchemy.sql import Select

from fdp.storage.tables import (
    DAILY_PRICE_TABLES,
    instrument,
    instrument_identifier_history,
)

DateInput = date | str | None

_DAILY_PRICE_TABLES: dict[str, Table] = DAILY_PRICE_TABLES


class DailyPriceReader:
    """Read split daily price tables through one database-backed interface.

    Input: database connection plus optional default date range and market.
    Output: queryable reader whose methods return database rows as dictionaries.
    Flow: symbols/date range -> instrument identity resolution -> split price table query.
    """

    def __init__(
        self,
        connection: Connection,
        *,
        date_from: DateInput = None,
        date_to: DateInput = None,
        market: str = "US",
    ) -> None:
        self.connection = connection
        self.date_from = _coerce_optional_date(date_from, field_name="date_from")
        self.date_to = _coerce_optional_date(date_to, field_name="date_to")
        self.market = market.upper()

    def get_daily_prices(
        self,
        *,
        symbols: Sequence[str],
        asset_type: str = "stock",
        date_from: DateInput = None,
        date_to: DateInput = None,
        adjusted: bool = True,
    ) -> list[dict[str, Any]]:
        """Return daily OHLCV rows from the local database.

        Input: symbols, asset type, optional method-level date range, and price mode.
        Output: list of row dictionaries ordered by current symbol and trade date.
        Flow: resolve dates -> build SQLAlchemy query -> execute -> mappings to dicts.
        """
        statement = self.build_daily_prices_query(
            symbols=symbols,
            asset_type=asset_type,
            date_from=date_from,
            date_to=date_to,
            adjusted=adjusted,
        )
        rows = self.connection.execute(statement).mappings().all()
        return [dict(row) for row in rows]

    def build_daily_prices_query(
        self,
        *,
        symbols: Sequence[str],
        asset_type: str = "stock",
        date_from: DateInput = None,
        date_to: DateInput = None,
        adjusted: bool = True,
    ) -> Select[Any]:
        """Build the SQLAlchemy query used by `get_daily_prices`.

        Input: symbols, asset type, optional method-level date range, and price mode.
        Output: SQLAlchemy select statement targeting one split daily price table.
        Flow: validate inputs -> resolve dates -> match instrument identity -> select prices.
        """
        normalized_symbols = _normalize_symbols(symbols)
        normalized_asset_type = asset_type.strip().lower()
        price_table = _price_table_for_asset_type(normalized_asset_type)
        resolved_from, resolved_to = self.resolve_date_range(date_from=date_from, date_to=date_to)
        analysis_close = (
            price_table.c.adjusted_close if adjusted else price_table.c.close
        ).label("analysis_close")

        identifier_match = (
            select(1)
            .select_from(instrument_identifier_history)
            .where(
                instrument_identifier_history.c.instrument_id == instrument.c.instrument_id,
                instrument_identifier_history.c.id_type.in_(("ticker", "provider_symbol")),
                instrument_identifier_history.c.id_value.in_(normalized_symbols),
                or_(
                    instrument_identifier_history.c.valid_from.is_(None),
                    instrument_identifier_history.c.valid_from <= resolved_to,
                ),
                or_(
                    instrument_identifier_history.c.valid_to.is_(None),
                    instrument_identifier_history.c.valid_to >= resolved_from,
                ),
            )
            .exists()
        )

        return (
            select(
                instrument.c.instrument_id,
                instrument.c.symbol.label("symbol"),
                instrument.c.provider_symbol.label("provider_symbol"),
                instrument.c.name,
                instrument.c.exchange,
                instrument.c.asset_type,
                instrument.c.is_active,
                instrument.c.delisted_date,
                price_table.c.symbol.label("price_symbol"),
                price_table.c.provider_symbol.label("price_provider_symbol"),
                price_table.c.trade_date,
                price_table.c.open,
                price_table.c.high,
                price_table.c.low,
                price_table.c.close,
                price_table.c.adjusted_close,
                analysis_close,
                price_table.c.volume,
                price_table.c.currency,
                price_table.c.source,
                price_table.c.source_updated_at,
            )
            .select_from(
                price_table.join(
                    instrument,
                    price_table.c.instrument_id == instrument.c.instrument_id,
                )
            )
            .where(
                instrument.c.market == self.market,
                instrument.c.asset_type == normalized_asset_type,
                price_table.c.trade_date.between(resolved_from, resolved_to),
                or_(
                    instrument.c.symbol.in_(normalized_symbols),
                    instrument.c.provider_symbol.in_(normalized_symbols),
                    identifier_match,
                ),
            )
            .order_by(instrument.c.symbol, price_table.c.trade_date)
        )

    def resolve_date_range(
        self,
        *,
        date_from: DateInput = None,
        date_to: DateInput = None,
    ) -> tuple[date, date]:
        """Resolve method-level dates before reader defaults.

        Input: optional method-level `date_from` and `date_to`.
        Output: validated inclusive date range.
        Flow: method dates if both provided -> reader defaults -> ValueError on gaps.
        """
        if (date_from is None) != (date_to is None):
            raise ValueError("date_from and date_to must be provided together")

        resolved_from = (
            _coerce_optional_date(date_from, field_name="date_from")
            if date_from is not None
            else self.date_from
        )
        resolved_to = (
            _coerce_optional_date(date_to, field_name="date_to")
            if date_to is not None
            else self.date_to
        )

        if resolved_from is None or resolved_to is None:
            raise ValueError("date_from and date_to are required")
        if resolved_to < resolved_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        return resolved_from, resolved_to


def _price_table_for_asset_type(asset_type: str) -> Table:
    try:
        return _DAILY_PRICE_TABLES[asset_type]
    except KeyError as exc:
        supported = ", ".join(_DAILY_PRICE_TABLES)
        raise ValueError(f"asset_type must be one of: {supported}") from exc


def _normalize_symbols(symbols: Sequence[str]) -> list[str]:
    normalized = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    if not normalized:
        raise ValueError("symbols must contain at least one symbol")
    return normalized


def _coerce_optional_date(value: DateInput, *, field_name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc
