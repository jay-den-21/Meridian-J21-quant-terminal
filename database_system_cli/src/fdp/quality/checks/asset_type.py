"""Physical daily-table alignment checks against canonical instrument type."""

from datetime import date

from sqlalchemy import Select, Table, select

from fdp.storage.tables import instrument, stock_daily_price


def asset_type_mismatch_rows(
    *,
    expected_asset_type: str,
    date_from: date,
    date_to: date,
    price_table: Table = stock_daily_price,
) -> Select:
    """Return price rows whose current instrument type disagrees with the table contract."""
    return (
        select(
            price_table,
            instrument.c.asset_type.label("actual_asset_type"),
        )
        .select_from(
            price_table.join(
                instrument,
                instrument.c.instrument_id == price_table.c.instrument_id,
            )
        )
        .where(
            price_table.c.trade_date.between(date_from, date_to),
            instrument.c.asset_type != expected_asset_type,
        )
    )
