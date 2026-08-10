"""New York trading-date and extended-session classification."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from fdp.intraday.models import MarketSession

NEW_YORK = ZoneInfo("America/New_York")
PRE_OPEN = time(4, 0)
CORE_OPEN = time(9, 30)
CORE_CLOSE = time(16, 0)
AFTER_CLOSE = time(20, 0)


def classify_us_equity_session(timestamp_utc: datetime) -> MarketSession:
    """Classify one aware UTC timestamp using local New York wall-clock bounds."""
    if timestamp_utc.tzinfo is None:
        raise ValueError("timestamp_utc must be timezone-aware")
    local_time = timestamp_utc.astimezone(NEW_YORK).time().replace(tzinfo=None)
    if PRE_OPEN <= local_time < CORE_OPEN:
        return "pre"
    if CORE_OPEN <= local_time < CORE_CLOSE:
        return "core"
    if CORE_CLOSE <= local_time < AFTER_CLOSE:
        return "after"
    raise ValueError("timestamp is outside the supported US equity 04:00-20:00 session")
