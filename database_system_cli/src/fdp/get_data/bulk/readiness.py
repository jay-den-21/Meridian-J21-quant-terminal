"""Resolve the latest provider-ready US trading date for one asset mix."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.engine import Connection

from fdp.storage.tables import market_calendar

NEW_YORK = ZoneInfo("America/New_York")
STOCK_ETF_READY_TIME = time(16, 30)
FUND_READY_TIME = time(6, 30)


def latest_provider_ready_trade_date(
    connection: Connection,
    *,
    asset_types: Sequence[str],
    now: datetime | None = None,
) -> date:
    """Read recent calendar rows and return the newest date past its EODHD cutoff."""
    timestamp = _new_york_now(now)
    candidates = connection.execute(
        select(market_calendar.c.calendar_date)
        .where(
            market_calendar.c.calendar_date <= timestamp.date(),
            market_calendar.c.is_trading_day.is_(True),
        )
        .order_by(market_calendar.c.calendar_date.desc())
        .limit(20)
    ).scalars()
    return latest_ready_from_dates(
        candidates,
        asset_types=asset_types,
        now=timestamp,
    )


def latest_ready_from_dates(
    trade_dates: Iterable[date],
    *,
    asset_types: Sequence[str],
    now: datetime,
) -> date:
    """Pure readiness rule used by DB callers and boundary tests."""
    timestamp = _new_york_now(now)
    includes_fund = "fund" in {value.strip().lower() for value in asset_types}
    for trade_date in sorted(set(trade_dates), reverse=True):
        if includes_fund:
            ready_at = datetime.combine(
                trade_date + timedelta(days=1),
                FUND_READY_TIME,
                tzinfo=NEW_YORK,
            )
        else:
            ready_at = datetime.combine(
                trade_date,
                STOCK_ETF_READY_TIME,
                tzinfo=NEW_YORK,
            )
        if timestamp >= ready_at:
            return trade_date
    raise ValueError(
        "market_calendar has no trading date that has reached the provider readiness cutoff"
    )


def _new_york_now(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(NEW_YORK)
