"""Common helpers for EODHD ingest workflows."""

from datetime import UTC, date, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.ingest.models import DEFAULT_INDEX_NAMES
from fdp.storage.tables import api_call_log, ingestion_task_run, instrument


def create_task_run(
    connection: Connection,
    *,
    market: str,
    job_name: str = "eodhd_exchange_symbols",
    target_table: str = "instrument",
    date_from: date | None = None,
    date_to: date | None = None,
) -> int:
    """Insert a running `system.ingestion_task_run` row and return `run_id`.

    Input: target job/table/date metadata.
    Output: new task run id.
    Flow: task metadata -> insert running task -> primary key.
    """
    result = connection.execute(
        ingestion_task_run.insert().values(
            job_name=job_name,
            market=market,
            source="EODHD",
            target_schema="us_share",
            target_table=target_table,
            status="running",
            date_from=date_from,
            date_to=date_to,
            started_at=now_utc(),
        )
    )
    return int(result.inserted_primary_key[0])


def record_api_call(
    connection: Connection,
    *,
    run_id: int,
    response,
    provider_symbol: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> None:
    """Record one EODHD API call summary in `system.api_call_log`.

    Input: active task run id and normalized EODHD response.
    Output: inserted API-call audit row.
    Flow: EODHD response -> audit fields -> api_call_log insert.
    """
    connection.execute(
        api_call_log.insert().values(
            run_id=run_id,
            source="EODHD",
            endpoint=response.endpoint,
            provider_symbol=provider_symbol,
            date_from=date_from,
            date_to=date_to,
            status_code=response.status_code,
            success=response.success,
            retry_count=response.retry_count,
            rows_returned=response.rows_returned,
            error_message=response.error_message,
            called_at=now_utc(),
            duration_ms=response.duration_ms,
        )
    )


def finish_task_run(
    connection: Connection,
    *,
    run_id: int,
    status: str,
    rows_fetched: int,
    rows_inserted: int,
    rows_updated: int,
    rows_rejected: int,
    api_calls: int,
    error_message: str | None,
) -> None:
    """Mark an ingest task run as finished.

    Input: run id, final status, row counts, API count, and optional error.
    Output: updated `system.ingestion_task_run` row.
    Flow: final counters -> update task_run status/timestamps.
    """
    connection.execute(
        update(ingestion_task_run)
        .where(ingestion_task_run.c.run_id == run_id)
        .values(
            status=status,
            finished_at=now_utc(),
            rows_fetched=rows_fetched,
            rows_inserted=rows_inserted,
            rows_updated=rows_updated,
            rows_rejected=rows_rejected,
            api_calls=api_calls,
            error_message=error_message,
        )
    )


def instrument_task_status(
    *,
    rows_fetched: int,
    rows_accepted: int,
    rows_rejected: int,
) -> tuple[str, str | None]:
    """Derive instrument ingest task status and message from parse counts."""
    if rows_rejected == 0:
        return "success", None
    if rows_accepted == 0 and rows_fetched > 0:
        return "failed", "all fetched EODHD instrument rows were rejected"
    return "partial_failed", f"{rows_rejected} EODHD instrument row(s) were rejected"


def historical_price_status(
    *,
    requested: int,
    loaded: int,
    missing_symbols: list[str],
    api_failures: list[str],
    rejected_rows: int,
) -> tuple[str, str | None]:
    """Derive historical price task status and message from load outcomes."""
    problems: list[str] = []
    if missing_symbols:
        problems.append(f"missing instrument(s): {', '.join(missing_symbols)}")
    if api_failures:
        problems.append(f"failed provider_symbol(s): {', '.join(api_failures)}")
    if rejected_rows:
        problems.append(f"{rejected_rows} invalid EODHD price row(s) rejected")

    if not problems:
        return "success", None
    if loaded == 0 and requested > 0:
        return "failed", "; ".join(problems)
    return "partial_failed", "; ".join(problems)


def normalize_symbols(symbols: list[str]) -> list[str]:
    """Normalize a caller-provided symbol list while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol or normalized_symbol in seen:
            continue
        normalized.append(normalized_symbol)
        seen.add(normalized_symbol)
    return normalized


def normalize_provider_symbols(provider_symbols: list[str]) -> list[str]:
    """Normalize provider symbols such as `GSPC.INDX` while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for provider_symbol in provider_symbols:
        normalized_provider_symbol = provider_symbol.strip().upper()
        if not normalized_provider_symbol or normalized_provider_symbol in seen:
            continue
        normalized.append(normalized_provider_symbol)
        seen.add(normalized_provider_symbol)
    return normalized


def index_instrument_rows(
    provider_symbols: list[str],
    *,
    market: str,
    currency: str,
) -> list[dict[str, object]]:
    """Build `instrument` rows for EODHD index provider symbols."""
    rows: list[dict[str, object]] = []
    for provider_symbol in provider_symbols:
        symbol, exchange = split_provider_symbol(provider_symbol)
        rows.append(
            {
                "market": market,
                "symbol": symbol,
                "provider": "EODHD",
                "provider_symbol": provider_symbol,
                "name": DEFAULT_INDEX_NAMES.get(provider_symbol, symbol),
                "exchange": exchange,
                "asset_type": "index",
                "currency": currency,
                "is_active": True,
                "listed_date": None,
                "delisted_date": None,
            }
        )
    return rows


def load_active_instruments(
    connection: Connection,
    *,
    symbols: list[str],
    market: str,
    asset_types: list[str] | None = None,
    include_inactive: bool = False,
) -> list[dict[str, object]]:
    """Fetch EODHD instruments for current symbols, optionally including inactive rows."""
    if not symbols:
        return []
    conditions = [
        instrument.c.market == market,
        instrument.c.provider == "EODHD",
        or_(
            instrument.c.symbol.in_(symbols),
            instrument.c.provider_symbol.in_(symbols),
        ),
    ]
    if not include_inactive:
        conditions.append(instrument.c.is_active.is_(True))
    if asset_types:
        conditions.append(instrument.c.asset_type.in_(asset_types))

    result = connection.execute(
        select(
            instrument.c.instrument_id,
            instrument.c.symbol,
            instrument.c.provider_symbol,
            instrument.c.asset_type,
            instrument.c.currency,
        ).where(*conditions)
    )
    rows = [dict(row) for row in result.mappings()]
    rows_by_provider_symbol = {str(row["provider_symbol"]).upper(): row for row in rows}
    rows_by_symbol = {str(row["symbol"]).upper(): row for row in rows}
    ordered_rows: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    for symbol in symbols:
        row = rows_by_provider_symbol.get(symbol) or rows_by_symbol.get(symbol)
        if row is None:
            continue
        instrument_id = int(row["instrument_id"])
        if instrument_id in seen_ids:
            continue
        ordered_rows.append(row)
        seen_ids.add(instrument_id)
    return ordered_rows


def load_active_instruments_by_provider_symbols(
    connection: Connection,
    *,
    provider_symbols: list[str],
    market: str,
) -> list[dict[str, object]]:
    """Fetch active EODHD instruments by current provider symbols."""
    if not provider_symbols:
        return []
    result = connection.execute(
        select(
            instrument.c.instrument_id,
            instrument.c.symbol,
            instrument.c.provider_symbol,
            instrument.c.asset_type,
            instrument.c.currency,
        ).where(
            instrument.c.market == market,
            instrument.c.provider == "EODHD",
            instrument.c.is_active.is_(True),
            instrument.c.provider_symbol.in_(provider_symbols),
        )
    )
    rows_by_provider_symbol = {
        row["provider_symbol"]: dict(row)
        for row in result.mappings()
    }
    return [
        rows_by_provider_symbol[provider_symbol]
        for provider_symbol in provider_symbols
        if provider_symbol in rows_by_provider_symbol
    ]


def load_active_instruments_by_ids(
    connection: Connection,
    *,
    instrument_ids: list[int],
    market: str,
    asset_types: list[str] | None = None,
) -> list[dict[str, object]]:
    """Fetch active EODHD instruments by immutable database ids."""
    if not instrument_ids:
        return []
    unique_ids = list(dict.fromkeys(instrument_ids))
    conditions = [
        instrument.c.instrument_id.in_(unique_ids),
        instrument.c.market == market,
        instrument.c.provider == "EODHD",
        instrument.c.is_active.is_(True),
    ]
    if asset_types:
        conditions.append(instrument.c.asset_type.in_(asset_types))

    result = connection.execute(
        select(
            instrument.c.instrument_id,
            instrument.c.symbol,
            instrument.c.provider_symbol,
            instrument.c.asset_type,
            instrument.c.currency,
        ).where(*conditions)
    )
    rows_by_id = {int(row["instrument_id"]): dict(row) for row in result.mappings()}
    return [rows_by_id[instrument_id] for instrument_id in unique_ids if instrument_id in rows_by_id]


def load_active_instruments_for_market(
    connection: Connection,
    *,
    market: str,
    asset_types: list[str] | None = None,
) -> list[dict[str, object]]:
    """Fetch active EODHD instruments for one market and optional asset types."""
    conditions = [
        instrument.c.market == market,
        instrument.c.provider == "EODHD",
        instrument.c.is_active.is_(True),
    ]
    if asset_types:
        conditions.append(instrument.c.asset_type.in_(asset_types))

    result = connection.execute(
        select(
            instrument.c.instrument_id,
            instrument.c.symbol,
            instrument.c.provider_symbol,
            instrument.c.asset_type,
            instrument.c.currency,
        ).where(*conditions)
    )
    return [dict(row) for row in result.mappings()]


def split_provider_symbol(provider_symbol: str) -> tuple[str, str]:
    """Split a provider symbol into ticker and provider exchange suffix."""
    parts = provider_symbol.rsplit(".", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"invalid EODHD provider_symbol: {provider_symbol!r}")
    return parts[0], parts[1]


def single_payload(response) -> dict[str, object]:
    """Return the single-object payload used by EODHD exchange-details responses."""
    if len(response.payload) != 1:
        raise ValueError("EODHD exchange-details response must contain exactly one payload row")
    return response.payload[0]


def holiday_count(exchange_details: dict[str, object]) -> int:
    """Count holiday entries in an exchange-details payload."""
    holidays = exchange_details.get("ExchangeHolidays")
    return len(holidays) if isinstance(holidays, dict) else 0


def now_utc() -> datetime:
    """Return the current UTC timestamp for audit columns."""
    return datetime.now(UTC)
