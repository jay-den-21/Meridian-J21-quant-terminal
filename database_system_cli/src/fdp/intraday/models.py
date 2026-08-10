"""Provider-neutral one-minute bar models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

MarketSession = Literal["pre", "core", "after"]


@dataclass(frozen=True)
class IntradayBar:
    """One validated raw 1-minute fact ready for deterministic Parquet storage."""

    instrument_id: int
    provider_symbol: str
    timestamp_utc: datetime
    trade_date: date
    session: MarketSession
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    transactions: int | None
    source: str = "eodhd"
    interval: str = "1m"

    @property
    def natural_key(self) -> tuple[str, int, datetime, str]:
        return (self.source, self.instrument_id, self.timestamp_utc, self.interval)
