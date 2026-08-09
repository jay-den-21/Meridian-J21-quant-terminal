"""Strict one-time adoption of evidence-complete legacy Bulk Daily runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import Connection

from fdp.get_data.task_ledger import (
    TASK_WORKFLOW_VERSION,
    DailyTaskScope,
    stable_fingerprint,
)
from fdp.storage.tables import (
    DAILY_PRICE_TABLES,
    api_call_log,
    bulk_unmatched_daily_price_observation,
    ingestion_task_run,
    ingestion_task_work_unit,
    market_calendar,
)

LEGACY_JOB_NAME = "eodhd_bulk_daily_price"
TERMINAL_OBSERVATION_STATUSES = frozenset({"resolved", "routed", "shadowed"})


@dataclass(frozen=True)
class LegacyDailyVerification:
    run_id: int
    trade_date: date
    verified: bool
    rows_fetched: int
    rows_published_at_ingest: int
    rows_published_verified: int
    observation_rows: int
    canonical_rows_now: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "trade_date": self.trade_date,
            "verified": self.verified,
            "rows_fetched": self.rows_fetched,
            "rows_published_at_ingest": self.rows_published_at_ingest,
            "rows_published_verified": self.rows_published_verified,
            "observation_rows": self.observation_rows,
            "canonical_rows_now": self.canonical_rows_now,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LegacyDailyAdoptionResult:
    candidates: int
    verified: int
    adopted: int
    rejected: int
    rows: tuple[LegacyDailyVerification, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "candidates": self.candidates,
            "verified": self.verified,
            "adopted": self.adopted,
            "rejected": self.rejected,
            "rows": [row.to_dict() for row in self.rows],
        }


class LegacyDailyAdoption:
    """Verify full source-row closure before making a legacy date reusable."""

    def inspect(
        self,
        connection: Connection,
        *,
        date_from: date,
        date_to: date,
        market: str,
        exchange: str,
        asset_types: Sequence[str],
        instrument_status: str,
        limit: int | None = None,
    ) -> list[LegacyDailyVerification]:
        if date_to < date_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        normalized_assets = tuple(sorted(set(asset_types)))
        expected_targets = {f"{value}_daily_price" for value in normalized_assets}
        statement = (
            select(ingestion_task_run)
            .where(
                ingestion_task_run.c.job_name == LEGACY_JOB_NAME,
                ingestion_task_run.c.market == market.upper(),
                ingestion_task_run.c.date_from >= date_from,
                ingestion_task_run.c.date_to <= date_to,
                ingestion_task_run.c.date_from == ingestion_task_run.c.date_to,
                ingestion_task_run.c.task_fingerprint.is_(None),
                ingestion_task_run.c.status.in_(("success", "partial_failed")),
            )
            .order_by(ingestion_task_run.c.date_from, ingestion_task_run.c.run_id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        rows = connection.execute(statement).mappings()
        return [
            self._verify_row(
                connection,
                row,
                exchange=exchange.upper(),
                expected_targets=expected_targets,
                asset_types=normalized_assets,
                instrument_status=instrument_status,
            )
            for row in rows
        ]

    def adopt(
        self,
        connection: Connection,
        *,
        date_from: date,
        date_to: date,
        market: str,
        exchange: str,
        asset_types: Sequence[str],
        instrument_status: str,
        limit: int | None = None,
    ) -> LegacyDailyAdoptionResult:
        rows = self.inspect(
            connection,
            date_from=date_from,
            date_to=date_to,
            market=market,
            exchange=exchange,
            asset_types=asset_types,
            instrument_status=instrument_status,
            limit=limit,
        )
        adopted = 0
        for verification in rows:
            if not verification.verified:
                continue
            if self._adopt_verified(
                connection,
                verification,
                market=market,
                exchange=exchange,
                asset_types=asset_types,
                instrument_status=instrument_status,
            ):
                adopted += 1
        verified = sum(row.verified for row in rows)
        return LegacyDailyAdoptionResult(
            candidates=len(rows),
            verified=verified,
            adopted=adopted,
            rejected=len(rows) - verified,
            rows=tuple(rows),
        )

    def _verify_row(
        self,
        connection: Connection,
        row: Mapping[str, object],
        *,
        exchange: str,
        expected_targets: set[str],
        asset_types: Sequence[str],
        instrument_status: str,
    ) -> LegacyDailyVerification:
        run_id = int(row["run_id"])
        trade_date = row["date_from"]
        if not isinstance(trade_date, date):
            raise RuntimeError(f"legacy run_id={run_id} has an invalid date")
        reasons: list[str] = []
        actual_targets = {
            value.strip()
            for value in str(row["target_table"]).split(",")
            if value.strip()
        }
        if actual_targets != expected_targets:
            reasons.append(
                f"target_tables_mismatch:actual={sorted(actual_targets)}"
            )

        api_rows = list(
            connection.execute(
                select(api_call_log).where(api_call_log.c.run_id == run_id)
            ).mappings()
        )
        expected_endpoint = f"/eod-bulk-last-day/{exchange}"
        if len(api_rows) != 1:
            reasons.append(f"api_log_count={len(api_rows)}")
        elif not bool(api_rows[0]["success"]):
            reasons.append("api_call_not_successful")
        elif str(api_rows[0]["endpoint"]) != expected_endpoint:
            reasons.append(f"endpoint_mismatch={api_rows[0]['endpoint']}")

        observation_counts = {
            str(value[0]): int(value[1])
            for value in connection.execute(
                select(
                    bulk_unmatched_daily_price_observation.c.classification_status,
                    func.count(),
                )
                .where(
                    bulk_unmatched_daily_price_observation.c.run_id == run_id,
                    bulk_unmatched_daily_price_observation.c.trade_date == trade_date,
                )
                .group_by(
                    bulk_unmatched_daily_price_observation.c.classification_status
                )
            )
        }
        non_terminal = sorted(
            status
            for status, count in observation_counts.items()
            if count and status not in TERMINAL_OBSERVATION_STATUSES
        )
        if non_terminal:
            reasons.append("non_terminal_observations=" + ",".join(non_terminal))
        observation_source_rows = sum(observation_counts.values())
        rows_fetched = int(row.get("rows_fetched") or 0)
        rows_published = int(row.get("rows_inserted") or 0)
        if rows_fetched <= 0:
            reasons.append("rows_fetched_not_positive")
        if rows_fetched != rows_published + observation_source_rows:
            reasons.append(
                "source_row_closure_mismatch:"
                f"fetched={rows_fetched};published={rows_published};"
                f"observed={observation_source_rows}"
            )

        calendar_flag = connection.execute(
            select(market_calendar.c.is_trading_day).where(
                market_calendar.c.calendar_date == trade_date
            )
        ).scalar_one_or_none()
        if calendar_flag is not True:
            reasons.append(f"calendar_not_verified={calendar_flag!r}")

        canonical_rows = 0
        invalid_rows = 0
        for asset_type in asset_types:
            table = DAILY_PRICE_TABLES[str(asset_type)]
            canonical_rows += int(
                connection.execute(
                    select(func.count()).select_from(table).where(
                        table.c.trade_date == trade_date
                    )
                ).scalar_one()
            )
            invalid_rows += int(
                connection.execute(
                    select(func.count()).select_from(table).where(
                        table.c.trade_date == trade_date,
                        or_(
                            table.c.open < 0,
                            table.c.high < 0,
                            table.c.low < 0,
                            table.c.close < 0,
                            table.c.high < table.c.low,
                            table.c.high < table.c.open,
                            table.c.high < table.c.close,
                            table.c.low > table.c.open,
                            table.c.low > table.c.close,
                            table.c.volume < 0,
                        ),
                    )
                ).scalar_one()
            )
        routed_or_resolved = observation_counts.get("routed", 0) + observation_counts.get(
            "resolved", 0
        )
        verified_published = rows_published + routed_or_resolved
        if canonical_rows < verified_published:
            reasons.append(
                "canonical_rows_below_evidence:"
                f"current={canonical_rows};expected_at_least={verified_published}"
            )
        if invalid_rows:
            reasons.append(f"invalid_canonical_rows={invalid_rows}")
        if instrument_status not in {"active", "all"}:
            reasons.append(f"unsupported_instrument_status={instrument_status}")

        return LegacyDailyVerification(
            run_id=run_id,
            trade_date=trade_date,
            verified=not reasons,
            rows_fetched=rows_fetched,
            rows_published_at_ingest=rows_published,
            rows_published_verified=verified_published,
            observation_rows=observation_source_rows,
            canonical_rows_now=canonical_rows,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _adopt_verified(
        connection: Connection,
        verification: LegacyDailyVerification,
        *,
        market: str,
        exchange: str,
        asset_types: Sequence[str],
        instrument_status: str,
    ) -> bool:
        run_id = verification.run_id
        existing = connection.execute(
            select(ingestion_task_work_unit.c.work_unit_id).where(
                ingestion_task_work_unit.c.run_id == run_id
            )
        ).first()
        if existing is not None:
            return False
        scope = DailyTaskScope.create(
            source="eodhd",
            market=market,
            exchange=exchange,
            date_from=verification.trade_date,
            date_to=verification.trade_date,
            asset_types=asset_types,
            instrument_status=instrument_status,
        )
        evidence = verification.to_dict()
        evidence["scope"] = scope.payload()
        response_hash = stable_fingerprint(evidence)
        api_metrics = connection.execute(
            select(
                func.count(),
                func.coalesce(func.sum(api_call_log.c.retry_count + 1), 0),
            ).where(api_call_log.c.run_id == run_id)
        ).one()
        api_calls = int(api_metrics[1])
        result = connection.execute(
            ingestion_task_work_unit.insert().values(
                run_id=run_id,
                unit_type="trade_date",
                unit_key=verification.trade_date.isoformat(),
                unit_fingerprint=scope.unit_fingerprint(verification.trade_date),
                series_fingerprint=scope.series_fingerprint,
                status="success",
                attempt_count=api_calls,
                evidence_run_id=run_id,
                rows_fetched=verification.rows_fetched,
                rows_published=verification.rows_published_verified,
                rows_pending=0,
                rows_rejected=0,
                api_calls=api_calls,
                api_units=100 * api_calls,
                response_hash=response_hash,
                quality_status="verified",
                metrics_json={
                    "legacy_adoption": True,
                    "evidence": evidence,
                    "asset_type_counts": {},
                },
                finished_at=func.current_timestamp(),
            )
        )
        work_unit_id = int(result.inserted_primary_key[0])
        checkpoint = {
            "version": TASK_WORKFLOW_VERSION,
            "workflow": "bulk_daily",
            "phase": "complete",
            "scope": scope.payload(),
            "work_units_total": 1,
            "review_required": False,
            "legacy_adoption": evidence,
        }
        connection.execute(
            update(ingestion_task_run)
            .where(ingestion_task_run.c.run_id == run_id)
            .values(
                status="success",
                checkpoint_json=checkpoint,
                task_fingerprint=scope.fingerprint,
                active_resume_key=None,
                workflow_version=TASK_WORKFLOW_VERSION,
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=func.current_timestamp(),
            )
        )
        connection.execute(
            update(api_call_log)
            .where(api_call_log.c.run_id == run_id)
            .values(work_unit_id=work_unit_id)
        )
        return True
