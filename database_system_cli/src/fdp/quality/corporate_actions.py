"""Quality-run persistence for rejected corporate-action provider rows."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Iterable

from sqlalchemy import update
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.corporate_actions import RejectedCorporateActionRow
from fdp.storage.tables import (
    US_SHARE_SCHEMA,
    data_quality_check_run,
    data_quality_issue,
)


def create_corporate_action_quality_check(
    connection: Connection,
    *,
    market: str,
    run_id: int,
) -> int:
    """Create the aggregate parser-quality run paired with one ingest run."""
    result = connection.execute(
        data_quality_check_run.insert().values(
            market=market,
            target_schema=US_SHARE_SCHEMA,
            target_table="corporate_action",
            check_scope=f"corporate_action_ingest_run:{run_id}",
            status="running",
            started_at=_now_utc(),
        )
    )
    return int(result.inserted_primary_key[0])


def record_corporate_action_quality_issues(
    connection: Connection,
    *,
    check_run_id: int,
    market: str,
    instrument_id: int,
    symbol: str,
    rows: Iterable[RejectedCorporateActionRow],
) -> int:
    """Persist rejected EODHD rows without modifying their raw evidence."""
    issues = []
    for rejected in rows:
        action_date = rejected.row.get("date")
        try:
            parsed_date = (
                None
                if action_date in (None, "")
                else datetime.strptime(str(action_date), "%Y-%m-%d").date()
            )
        except ValueError:
            parsed_date = None
        issues.append(
            {
                "check_run_id": check_run_id,
                "market": market,
                "target_schema": US_SHARE_SCHEMA,
                "target_table": "corporate_action",
                "issue_type": _issue_type(rejected),
                "severity": "error",
                "instrument_id": instrument_id,
                "symbol": symbol,
                "trade_date": parsed_date,
                "details": json.dumps(
                    {
                        "provider_symbol": rejected.provider_symbol,
                        "row_index": rejected.index,
                        "reason": rejected.reason,
                        "raw_row": rejected.row,
                    },
                    sort_keys=True,
                    default=str,
                ),
                "status": "open",
            }
        )
    if issues:
        connection.execute(data_quality_issue.insert().values(issues))
    return len(issues)


def _issue_type(rejected: RejectedCorporateActionRow) -> str:
    if rejected.reason.startswith("unresolved corporate-action owner:"):
        return "corporate_action_identity_unresolved"
    if rejected.reason.startswith("corporate-action owner is not stock:"):
        return "corporate_action_non_stock_owner"
    return f"invalid_{rejected.action_type}"


def finish_corporate_action_quality_check(
    connection: Connection,
    *,
    check_run_id: int,
    status: str,
    issues_found: int,
    error_message: str | None,
) -> None:
    """Finish the parser-quality run with committed issue counts."""
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


def _now_utc() -> datetime:
    return datetime.now(UTC)
