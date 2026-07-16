"""Execution layer for database-backed data quality validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Iterable

from sqlalchemy import Table, update
from sqlalchemy.engine import Connection

from fdp.quality.checks.asset_type import asset_type_mismatch_rows
from fdp.quality.checks.calendar_alignment import price_rows_on_non_trading_days
from fdp.quality.checks.duplicate import duplicate_daily_price_groups
from fdp.quality.checks.missing import loaded_daily_price_instruments, missing_daily_price_dates
from fdp.quality.checks.ohlcv import invalid_ohlcv_rows
from fdp.storage.tables import (
    DAILY_PRICE_TABLES,
    SYSTEM_SCHEMA,
    US_SHARE_SCHEMA,
    data_quality_check_run,
    data_quality_issue,
)

if TYPE_CHECKING:
    from fdp.bulk_unmatched import BulkUnmatchedRouteFailure

PRICE_TABLES = {
    asset_type: DAILY_PRICE_TABLES[asset_type]
    for asset_type in ("stock", "etf", "fund", "index")
}


@dataclass(frozen=True)
class DailyPriceTableValidationSummary:
    """Validation result for one asset-specific daily price table."""

    check_run_id: int
    asset_type: str
    target_table: str
    status: str
    issues_found: int


@dataclass(frozen=True)
class DailyPriceValidationResult:
    """Validation result for all requested daily price tables."""

    date_from: date
    date_to: date
    table_summaries: list[DailyPriceTableValidationSummary]

    @property
    def issues_found(self) -> int:
        return sum(summary.issues_found for summary in self.table_summaries)


def create_bulk_route_quality_check(
    connection: Connection,
    *,
    market: str,
    date_from: date,
    date_to: date,
) -> int:
    """Create one reusable quality run for conflicts retained by a route workflow."""
    result = connection.execute(
        data_quality_check_run.insert().values(
            market=market,
            target_schema=SYSTEM_SCHEMA,
            target_table="bulk_unmatched_daily_price_observation",
            check_scope=(
                "bulk_route_identity:"
                f"{date_from.isoformat()}..{date_to.isoformat()}"
            ),
            status="running",
            started_at=_now_utc(),
        )
    )
    return int(result.inserted_primary_key[0])


def record_bulk_route_quality_issues(
    connection: Connection,
    *,
    check_run_id: int,
    market: str,
    failures: Iterable["BulkUnmatchedRouteFailure"],
) -> int:
    """Persist route conflicts without changing or repairing their source rows."""
    issue_rows = [
        {
            "check_run_id": check_run_id,
            "market": market,
            "target_schema": US_SHARE_SCHEMA,
            "target_table": f"{failure.asset_type}_daily_price",
            "issue_type": failure.issue_type,
            "severity": "error",
            "instrument_id": failure.instrument_id,
            "symbol": failure.symbol,
            "trade_date": failure.trade_date,
            "details": json.dumps(
                {
                    "observation_id": failure.observation_id,
                    "provider_symbol": failure.provider_symbol,
                    "reason": failure.reason,
                },
                sort_keys=True,
            ),
            "status": "open",
        }
        for failure in failures
    ]
    if issue_rows:
        connection.execute(data_quality_issue.insert().values(issue_rows))
    return len(issue_rows)


def finish_bulk_route_quality_check(
    connection: Connection,
    *,
    check_run_id: int,
    status: str,
    issues_found: int,
    error_message: str | None,
) -> None:
    """Finish or pause the route-conflict quality run with committed counts."""
    _finish_check_run(
        connection,
        check_run_id=check_run_id,
        status=status,
        issues_found=issues_found,
        error_message=error_message,
    )


def validate_daily_prices(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    asset_types: list[str] | None = None,
    market: str = "US",
) -> DailyPriceValidationResult:
    """Run daily price quality checks and persist check runs/issues.

    Input: database connection, inclusive date range, and optional asset types.
    Output: per-table validation summaries with issue counts.
    Flow: price tables -> quality queries -> data_quality_issue rows -> check summaries.
    """
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")

    selected_asset_types = asset_types or list(PRICE_TABLES)
    table_summaries = [
        _validate_price_table(
            connection,
            date_from=date_from,
            date_to=date_to,
            market=market,
            asset_type=asset_type,
            price_table=_price_table_for(asset_type),
        )
        for asset_type in selected_asset_types
    ]
    return DailyPriceValidationResult(
        date_from=date_from,
        date_to=date_to,
        table_summaries=table_summaries,
    )


def _validate_price_table(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str,
    asset_type: str,
    price_table: Table,
) -> DailyPriceTableValidationSummary:
    check_run_id = _create_check_run(
        connection,
        market=market,
        target_table=price_table.name,
        check_scope=f"{price_table.name}:{date_from.isoformat()}..{date_to.isoformat()}",
    )
    issue_rows = _collect_issue_rows(
        connection,
        check_run_id=check_run_id,
        market=market,
        asset_type=asset_type,
        price_table=price_table,
        date_from=date_from,
        date_to=date_to,
    )
    if issue_rows:
        connection.execute(data_quality_issue.insert().values(issue_rows))

    _finish_check_run(
        connection,
        check_run_id=check_run_id,
        status="success",
        issues_found=len(issue_rows),
        error_message=None,
    )
    return DailyPriceTableValidationSummary(
        check_run_id=check_run_id,
        asset_type=asset_type,
        target_table=price_table.name,
        status="success",
        issues_found=len(issue_rows),
    )


def _collect_issue_rows(
    connection: Connection,
    *,
    check_run_id: int,
    market: str,
    asset_type: str,
    price_table: Table,
    date_from: date,
    date_to: date,
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []

    mismatch_rows = connection.execute(
        asset_type_mismatch_rows(
            expected_asset_type=asset_type,
            date_from=date_from,
            date_to=date_to,
            price_table=price_table,
        )
    ).mappings()
    for row in mismatch_rows:
        details = _price_row_details(row)
        details.update(
            {
                "expected_asset_type": asset_type,
                "actual_asset_type": row["actual_asset_type"],
                "resolution": "j21 migrate daily-price-asset-types --phase plan",
            }
        )
        issues.append(
            _issue_row(
                check_run_id=check_run_id,
                market=market,
                target_table=price_table.name,
                issue_type="asset_type_mismatch",
                severity="error",
                instrument_id=row["instrument_id"],
                symbol=row["symbol"],
                trade_date=row["trade_date"],
                details=details,
            )
        )

    duplicate_rows = connection.execute(
        duplicate_daily_price_groups(
            date_from=date_from,
            date_to=date_to,
            price_table=price_table,
        )
    ).mappings()
    for row in duplicate_rows:
        issues.append(
            _issue_row(
                check_run_id=check_run_id,
                market=market,
                target_table=price_table.name,
                issue_type="duplicate_key",
                severity="error",
                instrument_id=row["instrument_id"],
                symbol=None,
                trade_date=row["trade_date"],
                details={"row_count": row["row_count"]},
            )
        )

    loaded_instrument_rows = connection.execute(
        loaded_daily_price_instruments(
            date_from=date_from,
            date_to=date_to,
            price_table=price_table,
        )
    ).mappings()
    for instrument_row in loaded_instrument_rows:
        missing_rows = connection.execute(
            missing_daily_price_dates(
                instrument_id=instrument_row["instrument_id"],
                date_from=date_from,
                date_to=date_to,
                price_table=price_table,
            )
        ).mappings()
        for row in missing_rows:
            issues.append(
                _issue_row(
                    check_run_id=check_run_id,
                    market=market,
                    target_table=price_table.name,
                    issue_type="missing_trade_date",
                    severity="warning",
                    instrument_id=instrument_row["instrument_id"],
                    symbol=instrument_row["symbol"],
                    trade_date=row["calendar_date"],
                    details={"reason": "loaded instrument is missing a trading-day price row"},
                )
            )

    invalid_rows = connection.execute(
        invalid_ohlcv_rows(
            date_from=date_from,
            date_to=date_to,
            price_table=price_table,
        )
    ).mappings()
    for row in invalid_rows:
        issues.append(
            _issue_row(
                check_run_id=check_run_id,
                market=market,
                target_table=price_table.name,
                issue_type="invalid_ohlcv",
                severity="error",
                instrument_id=row["instrument_id"],
                symbol=row["symbol"],
                trade_date=row["trade_date"],
                details=_price_row_details(row),
            )
        )

    non_trading_rows = connection.execute(
        price_rows_on_non_trading_days(
            date_from=date_from,
            date_to=date_to,
            price_table=price_table,
        )
    ).mappings()
    for row in non_trading_rows:
        issues.append(
            _issue_row(
                check_run_id=check_run_id,
                market=market,
                target_table=price_table.name,
                issue_type="price_on_non_trading_day",
                severity="error",
                instrument_id=row["instrument_id"],
                symbol=row["symbol"],
                trade_date=row["trade_date"],
                details=_price_row_details(row),
            )
        )

    return issues


def _create_check_run(
    connection: Connection,
    *,
    market: str,
    target_table: str,
    check_scope: str,
) -> int:
    result = connection.execute(
        data_quality_check_run.insert().values(
            market=market,
            target_schema=US_SHARE_SCHEMA,
            target_table=target_table,
            check_scope=check_scope,
            status="running",
            started_at=_now_utc(),
        )
    )
    return int(result.inserted_primary_key[0])


def _finish_check_run(
    connection: Connection,
    *,
    check_run_id: int,
    status: str,
    issues_found: int,
    error_message: str | None,
) -> None:
    connection.execute(
        update(data_quality_check_run)
        .where(data_quality_check_run.c.check_run_id == check_run_id)
        .values(
            status=status,
            finished_at=_now_utc(),
            issues_found=issues_found,
            error_message=error_message,
        )
    )


def _issue_row(
    *,
    check_run_id: int,
    market: str,
    target_table: str,
    issue_type: str,
    severity: str,
    instrument_id: int | None,
    symbol: str | None,
    trade_date: date | None,
    details: dict[str, object],
) -> dict[str, object]:
    return {
        "check_run_id": check_run_id,
        "market": market,
        "target_schema": US_SHARE_SCHEMA,
        "target_table": target_table,
        "issue_type": issue_type,
        "severity": severity,
        "instrument_id": instrument_id,
        "symbol": symbol,
        "trade_date": trade_date,
        "details": json.dumps(details, default=_json_default, sort_keys=True),
        "status": "open",
    }


def _price_row_details(row: dict[str, Any]) -> dict[str, object]:
    return {
        "provider_symbol": row.get("provider_symbol"),
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "close": row.get("close"),
        "adjusted_close": row.get("adjusted_close"),
        "volume": row.get("volume"),
    }


def _price_table_for(asset_type: str) -> Table:
    try:
        return PRICE_TABLES[asset_type]
    except KeyError as exc:
        supported = ", ".join(PRICE_TABLES)
        raise ValueError(f"unsupported asset type {asset_type!r}; expected one of {supported}") from exc


def _json_default(value: object) -> str | int | float:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _now_utc() -> datetime:
    return datetime.now(UTC)
