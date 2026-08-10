"""Versioned PyArrow schema for normalized one-minute bars."""

from __future__ import annotations

import pyarrow as pa

INTRADAY_SCHEMA_VERSION = 1
PRICE_TYPE = pa.decimal128(20, 8)

INTRADAY_BAR_SCHEMA = pa.schema(
    [
        pa.field("instrument_id", pa.int64(), nullable=False),
        pa.field("provider_symbol", pa.string(), nullable=False),
        pa.field("timestamp_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("trade_date", pa.date32(), nullable=False),
        pa.field("session", pa.string(), nullable=False),
        pa.field("open", PRICE_TYPE, nullable=False),
        pa.field("high", PRICE_TYPE, nullable=False),
        pa.field("low", PRICE_TYPE, nullable=False),
        pa.field("close", PRICE_TYPE, nullable=False),
        pa.field("volume", pa.int64(), nullable=False),
        pa.field("transactions", pa.int64(), nullable=True),
        pa.field("source", pa.string(), nullable=False),
        pa.field("interval", pa.string(), nullable=False),
    ]
)
