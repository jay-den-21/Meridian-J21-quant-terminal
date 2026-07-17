"""Canonical persistence for one instrument's EODHD corporate actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.engine import Connection

from fdp.quality.corporate_actions import record_corporate_action_quality_issues
from fdp.sources.eodhd.client import EodhdApiResponse, EodhdClient
from fdp.sources.eodhd.corporate_action_identity import CorporateActionIdentityResolver
from fdp.sources.eodhd.corporate_actions import (
    ParsedCorporateActionRows,
    RejectedCorporateActionRow,
    parse_dividend_row,
    parse_dividend_rows,
    parse_split_row,
    parse_split_rows,
)
from fdp.sources.eodhd.ingest.common import record_api_call
from fdp.storage.upsert import build_corporate_action_upsert

SUPPORTED_ACTION_TYPES = frozenset({"dividend", "split"})
FATAL_HTTP_STATUS_CODES = frozenset({401, 402, 403})


@dataclass(frozen=True)
class CorporateActionUnitResult:
    """Committed facts for one instrument inside an aggregate backfill run."""

    instrument_id: int
    provider_symbol: str
    status: str
    rows_fetched: int
    rows_inserted: int
    rows_rejected: int
    api_calls: int
    requests_succeeded: int
    requests_failed: int
    rejected_rows: list[RejectedCorporateActionRow]
    status_code: int | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class FetchedCorporateActionResponse:
    """One already-completed provider request and its action type."""

    action_type: str
    response: EodhdApiResponse


@dataclass(frozen=True)
class FetchedCorporateActionUnit:
    """Provider responses fetched without holding a database transaction."""

    provider_symbol: str
    responses: list[FetchedCorporateActionResponse]

    @property
    def api_calls(self) -> int:
        return sum(item.response.retry_count + 1 for item in self.responses)


def fetch_corporate_action_unit(
    client: EodhdClient,
    *,
    provider_symbol: str,
    action_types: list[str],
    date_from: date | None,
    date_to: date | None,
) -> FetchedCorporateActionUnit:
    """Call selected endpoints without opening or holding a database transaction."""
    responses: list[FetchedCorporateActionResponse] = []
    for action_type in normalize_action_types(action_types):
        response = _fetch_action_response(
            client,
            provider_symbol=provider_symbol,
            action_type=action_type,
            date_from=date_from,
            date_to=date_to,
        )
        responses.append(FetchedCorporateActionResponse(action_type, response))
        if response.status_code in FATAL_HTTP_STATUS_CODES:
            break
    return FetchedCorporateActionUnit(provider_symbol, responses)


def record_corporate_action_api_calls(
    connection: Connection,
    *,
    run_id: int,
    fetched: FetchedCorporateActionUnit,
    date_from: date | None,
    date_to: date | None,
) -> None:
    """Commit provider request evidence separately from canonical event writes."""
    for item in fetched.responses:
        record_api_call(
            connection,
            run_id=run_id,
            response=item.response,
            provider_symbol=fetched.provider_symbol,
            date_from=date_from,
            date_to=date_to,
        )


def persist_corporate_action_unit(
    connection: Connection,
    *,
    fetched: FetchedCorporateActionUnit,
    check_run_id: int,
    market: str,
    instrument_row: dict[str, object],
    identity_resolver: CorporateActionIdentityResolver | None = None,
) -> CorporateActionUnitResult:
    """Parse and upsert already-fetched responses in one short write transaction."""
    instrument_id = int(instrument_row["instrument_id"])
    symbol = str(instrument_row["symbol"])
    rows_fetched = 0
    rows_inserted = 0
    succeeded = 0
    failed = 0
    rejected_rows: list[RejectedCorporateActionRow] = []
    failures: list[str] = []
    last_status_code: int | None = None

    for item in fetched.responses:
        response = item.response
        last_status_code = response.status_code
        if not response.success:
            failed += 1
            failures.append(
                f"{item.action_type}: "
                f"{response.error_message or response.status_code or 'request failed'}"
            )
            continue
        succeeded += 1
        rows_fetched += response.rows_returned
        parsed = _parse_action_response(
            response.payload,
            instrument_row=instrument_row,
            action_type=item.action_type,
            identity_resolver=identity_resolver,
        )
        rejected_rows.extend(parsed.rejected)
        if parsed.accepted:
            connection.execute(build_corporate_action_upsert(parsed.accepted))
            rows_inserted += len(parsed.accepted)

    if rejected_rows:
        record_corporate_action_quality_issues(
            connection,
            check_run_id=check_run_id,
            market=market,
            instrument_id=instrument_id,
            symbol=symbol,
            rows=rejected_rows,
        )

    if failed == 0 and not rejected_rows:
        status = "success"
    elif succeeded > 0:
        status = "partial_failed"
    else:
        status = "failed"
    problems = failures + (
        [f"{len(rejected_rows)} provider row(s) rejected"] if rejected_rows else []
    )
    return CorporateActionUnitResult(
        instrument_id=instrument_id,
        provider_symbol=fetched.provider_symbol,
        status=status,
        rows_fetched=rows_fetched,
        rows_inserted=rows_inserted,
        rows_rejected=len(rejected_rows),
        api_calls=fetched.api_calls,
        requests_succeeded=succeeded,
        requests_failed=failed,
        rejected_rows=rejected_rows,
        status_code=last_status_code,
        error_message="; ".join(problems) or None,
    )


def load_corporate_action_unit(
    connection: Connection,
    client: EodhdClient,
    *,
    run_id: int,
    check_run_id: int,
    market: str,
    instrument_row: dict[str, object],
    action_types: list[str],
    date_from: date | None,
    date_to: date | None,
) -> CorporateActionUnitResult:
    """Fetch, validate, audit, and upsert selected events for one instrument."""
    provider_symbol = str(instrument_row["provider_symbol"])
    fetched = fetch_corporate_action_unit(
        client,
        provider_symbol=provider_symbol,
        action_types=action_types,
        date_from=date_from,
        date_to=date_to,
    )
    record_corporate_action_api_calls(
        connection,
        run_id=run_id,
        fetched=fetched,
        date_from=date_from,
        date_to=date_to,
    )
    return persist_corporate_action_unit(
        connection,
        fetched=fetched,
        check_run_id=check_run_id,
        market=market,
        instrument_row=instrument_row,
    )


def normalize_action_types(action_types: list[str]) -> list[str]:
    """Normalize selected action types while preserving caller order."""
    normalized: list[str] = []
    for value in action_types:
        action_type = value.strip().lower()
        if not action_type or action_type in normalized:
            continue
        if action_type not in SUPPORTED_ACTION_TYPES:
            expected = ",".join(sorted(SUPPORTED_ACTION_TYPES))
            raise ValueError(
                f"unsupported corporate action type: {action_type}; expected {expected}"
            )
        normalized.append(action_type)
    if not normalized:
        raise ValueError("action_types must contain at least one action type")
    return normalized


def _fetch_action_response(
    client: EodhdClient,
    *,
    provider_symbol: str,
    action_type: str,
    date_from: date | None,
    date_to: date | None,
):
    if action_type == "dividend":
        return client.get_dividends(
            provider_symbol,
            date_from=date_from,
            date_to=date_to,
        )
    if action_type == "split":
        return client.get_splits(
            provider_symbol,
            date_from=date_from,
            date_to=date_to,
        )
    raise ValueError(f"unsupported corporate action type: {action_type}")


def _parse_action_response(
    rows: list[dict[str, object]],
    *,
    instrument_row: dict[str, object],
    action_type: str,
    identity_resolver: CorporateActionIdentityResolver | None = None,
):
    if identity_resolver is not None:
        return _parse_routed_action_response(
            rows,
            instrument_row=instrument_row,
            action_type=action_type,
            identity_resolver=identity_resolver,
        )
    arguments = {
        "instrument_id": int(instrument_row["instrument_id"]),
        "symbol": str(instrument_row["symbol"]),
        "provider_symbol": str(instrument_row["provider_symbol"]),
    }
    if action_type == "dividend":
        return parse_dividend_rows(rows, **arguments)
    if action_type == "split":
        return parse_split_rows(rows, **arguments)
    raise ValueError(f"unsupported corporate action type: {action_type}")


def _parse_routed_action_response(
    rows: list[dict[str, object]],
    *,
    instrument_row: dict[str, object],
    action_type: str,
    identity_resolver: CorporateActionIdentityResolver,
) -> ParsedCorporateActionRows:
    """Route each historical event to its dated stock owner before parsing."""
    parser = parse_dividend_row if action_type == "dividend" else parse_split_row
    if action_type not in SUPPORTED_ACTION_TYPES:
        raise ValueError(f"unsupported corporate action type: {action_type}")
    provider_symbol = str(instrument_row["provider_symbol"])
    groups: dict[
        tuple[int, date],
        list[tuple[int, dict[str, Any], dict[str, Any]]],
    ] = {}
    rejected: list[RejectedCorporateActionRow] = []

    for index, raw_row in enumerate(rows):
        row = dict(raw_row)
        try:
            raw_date = row.get("date")
            if raw_date in (None, ""):
                raise ValueError("missing required EODHD date field: date")
            try:
                action_date = (
                    raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
                )
            except ValueError as exc:
                raise ValueError("invalid date EODHD field: date") from exc
            resolution = identity_resolver.resolve(
                provider_symbol=provider_symbol,
                action_date=action_date,
            )
            target = resolution.instrument
            if target is None:
                candidates = ",".join(
                    str(value) for value in resolution.candidate_instrument_ids
                )
                suffix = f" candidates={candidates}" if candidates else ""
                raise ValueError(
                    f"unresolved corporate-action owner: {resolution.reason}{suffix}"
                )
            if str(target["asset_type"]) != "stock":
                raise ValueError(
                    "corporate-action owner is not stock: "
                    f"instrument_id={target['instrument_id']} "
                    f"asset_type={target['asset_type']}"
                )
            parsed = parser(
                row,
                instrument_id=int(target["instrument_id"]),
                symbol=str(target["symbol"]),
                provider_symbol=provider_symbol,
            )
        except ValueError as exc:
            rejected.append(
                RejectedCorporateActionRow(
                    index=index,
                    provider_symbol=provider_symbol,
                    action_type=action_type,
                    reason=str(exc),
                    row=row,
                )
            )
            continue
        groups.setdefault(
            (int(parsed["instrument_id"]), parsed["action_date"]),
            [],
        ).append((index, row, parsed))

    accepted: list[dict[str, Any]] = []
    for (instrument_id, action_date), group in groups.items():
        first = group[0][2]
        if all(entry[2] == first for entry in group[1:]):
            accepted.append(first)
            continue
        reason = (
            f"conflicting EODHD {action_type} rows for instrument_id={instrument_id} "
            f"action_date={action_date.isoformat()}"
        )
        rejected.extend(
            RejectedCorporateActionRow(
                index=index,
                provider_symbol=provider_symbol,
                action_type=action_type,
                reason=reason,
                row=row,
            )
            for index, row, _ in group
        )

    accepted.sort(key=lambda row: (int(row["instrument_id"]), row["action_date"]))
    rejected.sort(key=lambda row: row.index)
    return ParsedCorporateActionRows(accepted=accepted, rejected=rejected)
