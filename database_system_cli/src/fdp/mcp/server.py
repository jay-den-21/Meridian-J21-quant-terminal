"""Stdio MCP server exposing the shared Daily Job and durable task ledger."""

from __future__ import annotations

from datetime import date, datetime
import os
from typing import Any, Mapping, Sequence

from mcp.server.fastmcp import FastMCP

from fdp.get_data.bulk import BulkDailyJob, DailyRangeJob
from fdp.get_data.runtime import JobRuntime
from fdp.get_data.task_ledger import TaskLedger

MCP_WRITE_ENV = "J21_MCP_ENABLE_WRITES"

mcp = FastMCP(
    "Meridian J21 Daily Data",
    instructions=(
        "Use preflight and task tools first. Provider calls and database writes are "
        "disabled unless the operator explicitly enables MCP writes and confirms each call."
    ),
)


def _date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc


def _assets(values: Sequence[str] | None) -> list[str]:
    normalized = sorted(
        {str(value).strip().lower() for value in (values or ["stock", "etf", "fund"])}
    )
    unsupported = set(normalized) - {"stock", "etf", "fund"}
    if unsupported:
        raise ValueError(f"unsupported Bulk Daily asset types: {sorted(unsupported)}")
    return normalized


def _assert_write_allowed(*, confirm_execute: bool) -> None:
    if os.getenv(MCP_WRITE_ENV) != "1":
        raise PermissionError(
            f"MCP writes are disabled; set {MCP_WRITE_ENV}=1 in the server environment"
        )
    if confirm_execute is not True:
        raise PermissionError("confirm_execute=true is required for a provider/write call")


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@mcp.tool()
def daily_range_preflight(
    date_from: str,
    date_to: str,
    asset_types: list[str] | None = None,
    instrument_status: str = "all",
    exchange: str = "US",
    market: str = "US",
    max_api_calls: int | None = None,
) -> dict[str, Any]:
    """Estimate a Daily Bulk range without provider calls or database writes."""
    runtime = JobRuntime.from_env()
    result = DailyRangeJob().run(
        execute=False,
        date_from=_date(date_from, field_name="date_from"),
        date_to=_date(date_to, field_name="date_to"),
        asset_types=_assets(asset_types),
        instrument_status=instrument_status,
        exchange=exchange,
        market=market,
        max_api_calls=max_api_calls,
        runtime=runtime,
        override_source="mcp",
    )
    return _json_safe(result.to_dict())


@mcp.tool()
def daily_preflight(
    trade_date: str | None = None,
    asset_types: list[str] | None = None,
    instrument_status: str = "active",
    exchange: str = "US",
    market: str = "US",
) -> dict[str, Any]:
    """Estimate one explicit/latest Daily Bulk request without writes."""
    runtime = JobRuntime.from_env()
    result = BulkDailyJob().run(
        execute=False,
        trade_date=(
            _date(trade_date, field_name="trade_date") if trade_date is not None else None
        ),
        asset_types=_assets(asset_types),
        instrument_status=instrument_status,
        exchange=exchange,
        market=market,
        runtime=runtime,
        override_source="mcp",
    )
    return _json_safe(result.to_dict())


@mcp.tool()
def daily_execute(
    confirm_execute: bool,
    trade_date: str | None = None,
    asset_types: list[str] | None = None,
    instrument_status: str = "active",
    exchange: str = "US",
    market: str = "US",
    manual: bool = False,
    new_run: bool = False,
    max_api_calls: int | None = None,
) -> dict[str, Any]:
    """Execute/resume one explicit/latest Daily Bulk task after dual confirmation."""
    _assert_write_allowed(confirm_execute=confirm_execute)
    result = BulkDailyJob().run(
        execute=True,
        manual=manual,
        new_run=new_run,
        trade_date=(
            _date(trade_date, field_name="trade_date") if trade_date is not None else None
        ),
        asset_types=_assets(asset_types),
        instrument_status=instrument_status,
        exchange=exchange,
        market=market,
        max_api_calls=max_api_calls,
        runtime=JobRuntime.from_env(),
        override_source="mcp",
    )
    return _json_safe(result.to_dict())


@mcp.tool()
def daily_range_execute(
    date_from: str,
    date_to: str,
    confirm_execute: bool,
    asset_types: list[str] | None = None,
    instrument_status: str = "all",
    exchange: str = "US",
    market: str = "US",
    manual: bool = False,
    new_run: bool = False,
    max_api_calls: int | None = None,
) -> dict[str, Any]:
    """Execute/resume Daily Bulk only after two independent write confirmations."""
    _assert_write_allowed(confirm_execute=confirm_execute)
    result = DailyRangeJob().run(
        execute=True,
        manual=manual,
        new_run=new_run,
        date_from=_date(date_from, field_name="date_from"),
        date_to=_date(date_to, field_name="date_to"),
        asset_types=_assets(asset_types),
        instrument_status=instrument_status,
        exchange=exchange,
        market=market,
        max_api_calls=max_api_calls,
        runtime=JobRuntime.from_env(),
        override_source="mcp",
    )
    return _json_safe(result.to_dict())


@mcp.tool()
def task_list(status: str | None = None, limit: int = 50) -> list[dict[str, object]]:
    """List durable task checkpoints; this never calls a provider."""
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    runtime = JobRuntime.from_env()
    with runtime.engine.connect() as connection:
        return _json_safe(TaskLedger().list_tasks(connection, status=status, limit=limit))


@mcp.tool()
def task_status(run_id: int) -> dict[str, object]:
    """Read one durable task and work-unit summary; this never writes."""
    runtime = JobRuntime.from_env()
    with runtime.engine.connect() as connection:
        return _json_safe(TaskLedger().task_status(connection, run_id=run_id))


def main() -> None:
    """Start the protocol-clean stdio server."""
    mcp.run(transport="stdio")
