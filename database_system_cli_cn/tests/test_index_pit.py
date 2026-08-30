from __future__ import annotations

from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fdp_cn.cli import _emit_index_pit_result, main
from fdp_cn.contracts import JobFailure, JobPreflight, JobResult
from fdp_cn.menu import run_menu
from fdp_cn.tushare.index_pit import (
    IndexPitJob,
    IndexPitRequest,
    _assert_page_progress,
    _checkpoint_plan_hash,
    _completed_month_windows,
    _finish_run,
    _is_terminal_unit_failure,
    _new_checkpoint,
    _persist_provider_failure_locked,
    _provider_units,
    _provider_log_message,
    _reconcile_page_failure_locked,
    _sw_pit_units,
    _sw_pit_schema_fingerprint,
    _validate_checkpoint_payload,
    _weight_log_message,
    _weight_unit_from_json,
    _weight_units,
)
from fdp_cn.tushare.index_pit_specs import (
    INDEX_BASIC_SPEC,
    INDEX_CLASSIFY_SPEC,
    INDEX_MEMBER_ALL_SPEC,
    INDEX_MEMBER_SPEC,
    INDEX_WEIGHT_SPEC,
    SW_DAILY_DECIMALS,
    SW_DAILY_SPEC,
)
from fdp_cn.tushare.index_pit_storage import (
    IndexMetadata,
    _SW_PIT_DDL,
    upsert_weight_stage,
)
from fdp_cn.tushare.cleaning import clean_page
from fdp_cn.tushare.errors import (
    TushareAuthenticationError,
    TushareDataError,
    TushareRunLeaseCleanupError,
    TushareStorageError,
    TushareTransportError,
)
from fdp_cn.tushare.models import EndpointUnit, TushareResponse


class IndexPitPlanningTests(unittest.TestCase):
    def test_all_uses_one_shared_api_budget_and_does_not_double_count_failures(self):
        job = IndexPitJob()
        request = IndexPitRequest(phase="all", max_api_calls=5, execute=True)
        phases = (
            IndexPitRequest(phase="basic", max_api_calls=5),
            IndexPitRequest(phase="classify", max_api_calls=5),
            IndexPitRequest(phase="sw-pit", max_api_calls=5),
            IndexPitRequest(phase="style", months=1, max_api_calls=5),
        )
        preflight = JobPreflight(
            job="ingest.index_pit",
            job_module="fdp_cn.tushare.index_pit",
            target_tables=["multiple"],
            work_units=4,
            estimated_api_calls=4,
            parameters={"phase": "all"},
            parameter_sources={"phase": "test"},
        )
        results = (
            JobResult(
                job="ingest.index_pit",
                status="success",
                run_id=1,
                parameters={"phase": "basic"},
                parameter_sources={},
                api_calls=3,
                work_units_total=1,
                work_units_completed=1,
            ),
            JobResult(
                job="ingest.index_pit",
                status="partial_failed",
                run_id=2,
                parameters={"phase": "classify"},
                parameter_sources={},
                api_calls=2,
                work_units_total=1,
                work_units_failed=1,
                failures=[JobFailure("one-unit", "network", "connection exhausted")],
            ),
            JobResult(
                job="ingest.index_pit",
                status="success",
                run_id=3,
                parameters={"phase": "sw-pit"},
                parameter_sources={},
                work_units_total=1,
                work_units_completed=1,
            ),
        )
        with patch(
            "fdp_cn.tushare.index_pit._all_phase_requests", return_value=phases
        ), patch.object(job, "run", side_effect=results) as run_phase:
            result = job._run_all(  # type: ignore[arg-type]
                request,
                SimpleNamespace(),
                SimpleNamespace(),
                preflight,
            )

        self.assertEqual(result.status, "partial_failed")
        self.assertEqual(result.work_units_failed, 2)
        self.assertEqual(len(result.failures), 2)
        self.assertEqual(result.metrics["remaining_api_calls"], 0)
        self.assertEqual(
            [call.args[0].max_api_calls for call in run_phase.call_args_list],
            [5, 2, None],
        )

    def test_all_stops_after_a_fatal_child_error(self):
        job = IndexPitJob()
        request = IndexPitRequest(phase="all", execute=True)
        phases = (
            IndexPitRequest(phase="basic"),
            IndexPitRequest(phase="classify"),
        )
        preflight = JobPreflight(
            job="ingest.index_pit",
            job_module="fdp_cn.tushare.index_pit",
            target_tables=["multiple"],
            work_units=2,
            estimated_api_calls=2,
            parameters={"phase": "all"},
            parameter_sources={"phase": "test"},
        )
        failed = JobResult(
            job="ingest.index_pit",
            status="failed",
            run_id=1,
            parameters={"phase": "basic"},
            parameter_sources={},
            failures=[JobFailure("basic", "authentication", "bad token")],
            error_message="bad token",
        )
        with patch(
            "fdp_cn.tushare.index_pit._all_phase_requests", return_value=phases
        ), patch.object(job, "run", return_value=failed) as run_phase:
            result = job._run_all(  # type: ignore[arg-type]
                request,
                SimpleNamespace(),
                SimpleNamespace(),
                preflight,
            )

        self.assertEqual(run_phase.call_count, 1)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_message, "bad token")

    def test_provider_contracts_match_reviewed_limits_and_business_keys(self):
        self.assertEqual(INDEX_BASIC_SPEC.page_limit, 8_000)
        self.assertEqual(INDEX_CLASSIFY_SPEC.business_key, ("src", "level", "index_code"))
        self.assertEqual(SW_DAILY_SPEC.page_limit, 4_000)
        self.assertEqual(INDEX_MEMBER_SPEC.page_limit, 2_000)
        self.assertEqual(INDEX_MEMBER_ALL_SPEC.page_limit, 2_000)
        self.assertEqual(INDEX_WEIGHT_SPEC.pagination.kind, "offset_limit")
        self.assertTrue(INDEX_WEIGHT_SPEC.pagination.source.startswith("J21 probe"))

    def test_classify_plans_both_versions_and_all_three_levels(self):
        units = _provider_units(IndexPitRequest(phase="classify"), runtime=None)

        self.assertEqual(len(units), 6)
        self.assertEqual(
            {(unit.params["src"], unit.params["level"]) for unit in units},
            {
                ("SW2014", "L1"),
                ("SW2014", "L2"),
                ("SW2014", "L3"),
                ("SW2021", "L1"),
                ("SW2021", "L2"),
                ("SW2021", "L3"),
            },
        )

    def test_sw_daily_splits_broad_history_into_month_scopes(self):
        units = _provider_units(
            IndexPitRequest(
                phase="sw-daily",
                date_from=date(2026, 1, 15),
                date_to=date(2026, 3, 2),
            ),
            runtime=None,
        )

        self.assertEqual(
            [unit.scope_key for unit in units],
            [
                "20260115..20260131",
                "20260201..20260228",
                "20260301..20260302",
            ],
        )
        self.assertTrue(all(unit.page_limit == 4_000 for unit in units))

    def test_sw_daily_allows_historic_null_numeric_values_but_not_null_keys(self):
        self.assertEqual(
            SW_DAILY_SPEC.nullable_columns,
            frozenset(SW_DAILY_DECIMALS),
        )
        self.assertTrue(
            {"ts_code", "trade_date", "name"}.isdisjoint(
                SW_DAILY_SPEC.nullable_columns
            )
        )
        response = TushareResponse(
            endpoint_key=SW_DAILY_SPEC.key,
            api_name=SW_DAILY_SPEC.api_name,
            fields=SW_DAILY_SPEC.fields,
            items=(
                (
                    "801863.SI",
                    "20131023",
                    "新股指数",
                    *(None for _ in SW_DAILY_DECIMALS),
                ),
            ),
            attempts=1,
        )

        cleaned = clean_page(SW_DAILY_SPEC, response)

        self.assertEqual(cleaned.cleaned_rows, 1)
        self.assertIsNone(cleaned.rows[0]["open"])

    def test_sw_daily_accepts_partially_missing_ohlc(self):
        values = {name: "1" for name in SW_DAILY_DECIMALS}
        values["open"] = None

        cleaned = clean_page(SW_DAILY_SPEC, _sw_daily_response(values))

        self.assertIsNone(cleaned.rows[0]["open"])

    def test_sw_daily_preserves_provider_ohlc_anomaly_without_rewriting(self):
        values = {name: "1" for name in SW_DAILY_DECIMALS}
        values.update(
            {
                "open": "5483.31",
                "low": "5199.63",
                "high": "5288.35",
                "close": "5251.51",
            }
        )

        cleaned = clean_page(SW_DAILY_SPEC, _sw_daily_response(values))

        self.assertEqual(cleaned.rows[0]["open"], Decimal("5483.31"))
        self.assertEqual(cleaned.rows[0]["high"], Decimal("5288.35"))

    def test_sw_pit_cutover_has_no_weekend_bridge(self):
        units = _sw_pit_units(
            IndexPitRequest(
                phase="sw-pit",
                date_from=date(2021, 12, 1),
                date_to=date(2021, 12, 31),
            )
        )

        self.assertEqual(
            [(unit["version"], unit["date_from"], unit["date_to"]) for unit in units],
            [
                ("SW2014", "2021-12-01", "2021-12-10"),
                ("SW2021", "2021-12-13", "2021-12-31"),
            ],
        )

    def test_sw_pit_keeps_only_the_date_first_primary_index(self):
        self.assertIn(
            "PRIMARY KEY (trade_date, industry_version, level, index_code, con_code)",
            _SW_PIT_DDL,
        )
        self.assertNotIn("KEY ix_idx_sw_member_pit_", _SW_PIT_DDL)

    def test_month_windows_exclude_the_current_partial_month(self):
        windows = _completed_month_windows(6)
        current_month = date(date.today().year, date.today().month, 1)

        self.assertEqual(len(windows), 6)
        self.assertEqual(windows[-1][1], current_month - timedelta(days=1))
        self.assertLess(windows[-1][1], current_month)

    def test_style_routing_is_exact_and_general_rejects_style_codes(self):
        metadata = (
            _metadata("000918.CSI", "风格指数"),
            _metadata("000300.SH", "规模指数"),
            _metadata("980080.CNI", "风格指数增强"),
        )
        runtime = SimpleNamespace(engine=object())
        with patch(
            "fdp_cn.tushare.index_pit.load_index_metadata",
            return_value=metadata,
        ):
            style = _weight_units(
                IndexPitRequest(phase="style", months=1),
                runtime=runtime,
            )
            with self.assertRaisesRegex(Exception, "style indices"):
                _weight_units(
                    IndexPitRequest(
                        phase="general",
                        months=1,
                        codes=("000918.CSI",),
                    ),
                    runtime=runtime,
                )

        self.assertEqual({unit.metadata.index_code for unit in style}, {"000918.CSI"})

    def test_style_can_plan_an_exact_completed_month_range(self):
        runtime = SimpleNamespace(engine=object())
        with patch(
            "fdp_cn.tushare.index_pit.load_index_metadata",
            return_value=(_metadata("000918.CSI", "风格指数"),),
        ):
            units = _weight_units(
                IndexPitRequest(
                    phase="style",
                    date_from=date(2021, 8, 1),
                    date_to=date(2026, 1, 31),
                ),
                runtime=runtime,
            )

        self.assertEqual(len(units), 54)
        self.assertEqual(units[0].month_start, date(2021, 8, 1))
        self.assertEqual(units[-1].month_end, date(2026, 1, 31))

    def test_resume_rejects_scope_changes(self):
        with self.assertRaisesRegex(ValueError, "restores dates"):
            IndexPitRequest(
                resume_run_id=12,
                codes=("000300.SH",),
            )

    def test_provider_log_includes_the_exact_fanout_scope(self):
        unit = EndpointUnit(
            endpoint_key=INDEX_CLASSIFY_SPEC.key,
            scope_key="src=SW2014|level=L3",
            params={"src": "SW2014", "level": "L3"},
            page_limit=10_000,
        )

        message = _provider_log_message(
            INDEX_CLASSIFY_SPEC,
            unit,
            offset=0,
            fetched=227,
            cleaned=227,
            written=227,
            calls=1,
            status="committed",
        )

        self.assertIn("scope=src=SW2014|level=L3", message)

    def test_weight_failure_log_keeps_explicit_scope_and_call_count(self):
        month_start = _completed_month_windows(1)[0][0]
        payload = _weight_unit_payload(
            _metadata("480080.CNI", "风格指数"), month_start
        )
        payload["table_name"] = "idx_style_member_pit"
        payload["unit_key"] = f"idx_style_member_pit:480080.CNI:{month_start:%Y%m}"
        unit = _weight_unit_from_json(payload)

        message = _weight_log_message(
            unit,
            offset=0,
            fetched=0,
            cleaned=0,
            published=0,
            calls=207,
            status="failed:no_data",
        )

        self.assertIn("endpoint=index_weight", message)
        self.assertIn("table=idx_style_member_pit", message)
        self.assertIn("index=480080.CNI", message)
        self.assertIn(f"month={month_start:%Y-%m}", message)
        self.assertIn("offset=0 fetched=0 cleaned=0 published=0", message)
        self.assertIn("cumulative_calls=207 status=failed:no_data", message)

    def test_post_commit_failure_keeps_the_advanced_checkpoint(self):
        checkpoint = _checkpoint()
        candidate = deepcopy(checkpoint)
        candidate["cursor"]["unit_index"] = 1
        unit = _basic_unit()
        with patch(
            "fdp_cn.tushare.index_pit._load_checkpoint", return_value=candidate
        ):
            actual, committed = _reconcile_page_failure_locked(
                object(),  # type: ignore[arg-type]
                run_id=9,
                checkpoint=checkpoint,
                candidate=candidate,
                spec=INDEX_BASIC_SPEC,
                unit=unit,
                response=_response(),
                cleaned_rows=1,
                error=TushareStorageError("lock cleanup failed"),
            )

        self.assertTrue(committed)
        self.assertIs(actual, candidate)

    def test_uncommitted_failure_accounts_usage_without_advancing_cursor(self):
        checkpoint = _checkpoint()
        unit = _basic_unit()
        candidate = deepcopy(checkpoint)
        candidate["cursor"]["offset"] = 8_000
        persisted = deepcopy(checkpoint)
        persisted["counters"]["api_calls"] = 1

        with patch(
            "fdp_cn.tushare.index_pit._load_checkpoint", return_value=checkpoint
        ), patch(
            "fdp_cn.tushare.index_pit._persist_uncommitted_page_usage_locked",
            return_value=persisted,
        ) as persist_usage:
            actual, committed = _reconcile_page_failure_locked(
                object(),  # type: ignore[arg-type]
                run_id=10,
                checkpoint=checkpoint,
                candidate=candidate,
                spec=INDEX_BASIC_SPEC,
                unit=unit,
                response=_response(),
                cleaned_rows=1,
                error=TushareStorageError("write rolled back"),
            )

        self.assertFalse(committed)
        self.assertEqual(actual, persisted)
        self.assertEqual(persist_usage.call_args.kwargs["cleaned_rows"], 1)

    def test_completed_run_succeeds_after_transient_failures_are_recovered(self):
        checkpoint = _checkpoint()
        checkpoint["cursor"]["unit_index"] = 1
        checkpoint["counters"]["units_completed"] = 1
        checkpoint["failures"] = [
            {
                "unit": "20131001..20131031",
                "category": "data",
                "message": "historic strict validation failure",
                "terminal": False,
            }
        ]

        with patch(
            "fdp_cn.tushare.index_pit.tushare_run_lease",
            return_value=nullcontext(),
        ), patch(
            "fdp_cn.tushare.index_pit._assert_durable_checkpoint"
        ), patch(
            "fdp_cn.tushare.index_pit._save_checkpoint_engine"
        ):
            finished = _finish_run(
                object(),  # type: ignore[arg-type]
                10,
                checkpoint,
                total_units=1,
                error_message=None,
            )

        self.assertEqual(finished["status"], "success")
        self.assertEqual(len(finished["failures"]), 1)

    def test_scope_error_accounts_real_response_attempts_without_skipping_unit(self):
        checkpoint = _checkpoint()
        response = _response(attempts=3)
        error = TushareDataError(
            "scope mismatch",
            endpoint=INDEX_BASIC_SPEC.key,
            attempts=3,
            status_code=200,
        )
        connection = SimpleNamespace()
        begin = MagicMock()
        begin.__enter__.return_value = connection
        begin.__exit__.return_value = False
        engine = SimpleNamespace(begin=lambda: begin)

        with patch("fdp_cn.tushare.index_pit._record_api_call") as record, patch(
            "fdp_cn.tushare.index_pit._save_checkpoint"
        ):
            actual = _persist_provider_failure_locked(
                engine,  # type: ignore[arg-type]
                run_id=11,
                checkpoint=checkpoint,
                spec=INDEX_BASIC_SPEC,
                unit=_basic_unit(),
                error=error,
                response=response,
                cleaned_rows=1,
                advance=False,
            )

        self.assertEqual(actual["counters"]["api_calls"], 3)
        self.assertEqual(actual["counters"]["rows_fetched"], 1)
        self.assertEqual(actual["counters"]["rows_cleaned"], 1)
        self.assertEqual(actual["counters"]["units_failed"], 0)
        self.assertEqual(actual["cursor"], checkpoint["cursor"])
        self.assertIs(record.call_args.kwargs["response"], response)

    def test_terminal_failure_advances_and_clears_page_history(self):
        checkpoint = _checkpoint()
        checkpoint["page_signatures"] = ["page-a", "page-b"]
        error = TushareTransportError("connection exhausted", attempts=3)
        connection = SimpleNamespace()
        begin = MagicMock()
        begin.__enter__.return_value = connection
        begin.__exit__.return_value = False
        engine = SimpleNamespace(begin=lambda: begin)

        with patch("fdp_cn.tushare.index_pit._record_api_call"), patch(
            "fdp_cn.tushare.index_pit._save_checkpoint"
        ):
            actual = _persist_provider_failure_locked(
                engine,  # type: ignore[arg-type]
                run_id=12,
                checkpoint=checkpoint,
                spec=INDEX_BASIC_SPEC,
                unit=_basic_unit(),
                error=error,
                response=None,
                cleaned_rows=0,
                advance=_is_terminal_unit_failure(error, response=None),
            )

        self.assertEqual(actual["cursor"], {"unit_index": 1, "offset": 0})
        self.assertEqual(actual["page_signatures"], [])
        self.assertEqual(actual["counters"]["units_failed"], 1)
        self.assertFalse(
            _is_terminal_unit_failure(
                TushareAuthenticationError("bad token", provider_code=-1),
                response=None,
            )
        )

    def test_failure_commit_uncertainty_accepts_the_durable_candidate(self):
        checkpoint = _checkpoint()
        error = TushareTransportError("connection exhausted", attempts=2)
        expected = deepcopy(checkpoint)
        expected["counters"]["api_calls"] = 2
        expected["counters"]["units_failed"] = 1
        expected["cursor"] = {"unit_index": 1, "offset": 0}
        expected["page_signatures"] = []
        expected["failures"] = [
            {
                "unit": "basic",
                "category": "network",
                "message": "connection exhausted",
                "terminal": True,
            }
        ]
        begin = MagicMock()
        begin.__enter__.return_value = SimpleNamespace()
        begin.__exit__.side_effect = RuntimeError("commit outcome unknown")
        engine = SimpleNamespace(begin=lambda: begin)

        with patch("fdp_cn.tushare.index_pit._record_api_call"), patch(
            "fdp_cn.tushare.index_pit._save_checkpoint"
        ), patch(
            "fdp_cn.tushare.index_pit._load_checkpoint", return_value=expected
        ):
            actual = _persist_provider_failure_locked(
                engine,  # type: ignore[arg-type]
                run_id=13,
                checkpoint=checkpoint,
                spec=INDEX_BASIC_SPEC,
                unit=_basic_unit(),
                error=error,
                response=None,
                cleaned_rows=0,
                advance=True,
            )

        self.assertEqual(actual, expected)

    def test_finish_commit_reconciles_run_lease_cleanup(self):
        checkpoint = _checkpoint()
        checkpoint["cursor"]["unit_index"] = 1
        checkpoint["counters"]["units_completed"] = 1
        expected = deepcopy(checkpoint)
        expected["complete"] = True
        expected["status"] = "success"

        @contextmanager
        def cleanup_failure():
            yield
            raise TushareRunLeaseCleanupError("release outcome unknown")

        with patch(
            "fdp_cn.tushare.index_pit.tushare_run_lease",
            return_value=cleanup_failure(),
        ), patch(
            "fdp_cn.tushare.index_pit._assert_durable_checkpoint"
        ), patch(
            "fdp_cn.tushare.index_pit._save_checkpoint_engine"
        ), patch(
            "fdp_cn.tushare.index_pit._load_checkpoint", return_value=expected
        ):
            actual = _finish_run(
                object(),  # type: ignore[arg-type]
                14,
                checkpoint,
                total_units=1,
                error_message=None,
            )

        self.assertEqual(actual, expected)

    def test_checkpoint_validation_rejects_weight_table_tampering(self):
        metadata = _metadata("000300.SH", "规模指数")
        units = [
            {
                "unit_key": "idx_member_pit:000300.SH:202607",
                "table_name": "idx_member_pit",
                "metadata": {
                    **metadata.__dict__,
                    "list_date": "2000-01-01",
                    "exp_date": None,
                },
                "month_start": "2026-07-01",
                "month_end": "2026-07-31",
            }
        ]
        checkpoint = _full_checkpoint(kind="weight", phase="general", units=units)
        checkpoint["units"][0]["table_name"] = "idx_style_member_pit"
        checkpoint["plan_hash"] = _checkpoint_plan_hash(
            checkpoint["kind"], checkpoint["parameters"], checkpoint["units"]
        )

        with self.assertRaisesRegex(TushareStorageError, "table, scope, or category"):
            _validate_checkpoint_payload(
                checkpoint,
                job_name="index_pit_weight_general",
                config_hash=checkpoint["plan_hash"],
            )

    def test_checkpoint_validation_rejects_missing_weight_month(self):
        metadata = _metadata("000300.SH", "规模指数")
        units = [
            _weight_unit_payload(metadata, date(2026, 1, 1)),
            _weight_unit_payload(metadata, date(2026, 3, 1)),
        ]
        checkpoint = _full_checkpoint(kind="weight", phase="general", units=units)
        checkpoint["parameters"] = {
            "phase": "general",
            "date_from": "2026-01-01",
            "date_to": "2026-03-31",
            "months": None,
            "codes": ["000300.SH"],
        }
        checkpoint["plan_hash"] = _checkpoint_plan_hash(
            checkpoint["kind"], checkpoint["parameters"], checkpoint["units"]
        )

        with self.assertRaisesRegex(TushareStorageError, "not continuous"):
            _validate_checkpoint_payload(
                checkpoint,
                job_name="index_pit_weight_general",
                config_hash=checkpoint["plan_hash"],
            )

    def test_weight_resume_keeps_requested_window_when_code_expired_mid_range(self):
        windows = _completed_month_windows(6)
        metadata = _metadata("000300.SH", "规模指数")
        metadata = IndexMetadata(
            **{
                **metadata.__dict__,
                "exp_date": windows[2][1],
            }
        )
        request = IndexPitRequest(
            phase="general",
            months=6,
            codes=(metadata.index_code,),
        )
        units = [
            _weight_unit_payload(metadata, month_start)
            for month_start, _month_end in windows[:3]
        ]
        preflight = JobPreflight(
            job="ingest.index_pit",
            job_module="fdp_cn.tushare.index_pit",
            target_tables=["idx_member_pit"],
            work_units=len(units),
            estimated_api_calls=len(units),
            parameters={"phase": "general"},
            parameter_sources={"phase": "test"},
        )
        checkpoint = _new_checkpoint(
            kind="weight",
            request=request,
            preflight=preflight,
            units=units,
        )

        _validate_checkpoint_payload(
            checkpoint,
            job_name="index_pit_weight_general",
            config_hash=checkpoint["plan_hash"],
        )

        self.assertEqual(
            checkpoint["parameters"]["resolved_weight_date_from"],
            windows[0][0].isoformat(),
        )
        self.assertEqual(
            checkpoint["parameters"]["resolved_weight_date_to"],
            windows[-1][1].isoformat(),
        )

    def test_sw_schema_fingerprint_rejects_secondary_indexes(self):
        column_rows = [
            {
                "column_name": name,
                "column_type": sql_type,
                "is_nullable": nullable,
            }
            for name, sql_type, nullable in (
                ("trade_date", "date", "NO"),
                ("industry_version", "varchar(8)", "NO"),
                ("level", "varchar(2)", "NO"),
                ("index_code", "varchar(20)", "NO"),
                ("con_code", "varchar(20)", "NO"),
                ("in_date", "date", "NO"),
                ("out_date", "date", "YES"),
                ("is_new", "varchar(2)", "NO"),
                ("source_endpoint", "varchar(32)", "NO"),
            )
        ]
        index_rows = [
            {
                "index_name": "PRIMARY",
                "non_unique": 0,
                "seq_in_index": sequence,
                "column_name": column,
            }
            for sequence, column in enumerate(
                (
                    "trade_date",
                    "industry_version",
                    "level",
                    "index_code",
                    "con_code",
                ),
                start=1,
            )
        ]
        index_rows.append(
            {
                "index_name": "retired_secondary",
                "non_unique": 1,
                "seq_in_index": 1,
                "column_name": "con_code",
            }
        )
        connection = MagicMock()
        column_result = MagicMock()
        column_result.mappings.return_value.all.return_value = column_rows
        index_result = MagicMock()
        index_result.mappings.return_value.all.return_value = index_rows
        connection.execute.side_effect = (column_result, index_result)
        connect = MagicMock()
        connect.__enter__.return_value = connection
        connect.__exit__.return_value = False
        engine = SimpleNamespace(connect=lambda: connect)

        with self.assertRaisesRegex(TushareStorageError, "only the exact"):
            _sw_pit_schema_fingerprint(  # type: ignore[arg-type]
                engine, "idx_sw_member_pit__staging"
            )

    def test_checkpoint_validation_rejects_hash_mismatch(self):
        units = [
            {
                "endpoint_key": INDEX_BASIC_SPEC.key,
                "scope_key": "basic",
                "params": {},
                "page_limit": 8_000,
            }
        ]
        checkpoint = _full_checkpoint(kind="provider", phase="basic", units=units)

        with self.assertRaisesRegex(TushareStorageError, "plan hash"):
            _validate_checkpoint_payload(
                checkpoint,
                job_name="index_pit_provider_basic",
                config_hash="tampered",
            )

    def test_page_history_rejects_a_b_a_cycle(self):
        checkpoint = _checkpoint()
        checkpoint["page_signatures"] = ["page-a", "page-b"]

        with self.assertRaisesRegex(TushareDataError, "earlier page"):
            _assert_page_progress(checkpoint, 0, 16_000, "page-a")

    def test_weight_stage_rejects_conflicting_keys_before_sql(self):
        rows = (
            {
                "trade_date": date(2026, 7, 31),
                "index_code": "000300.SH",
                "con_code": "000001.SZ",
                "weight": 1,
            },
            {
                "trade_date": date(2026, 7, 31),
                "index_code": "000300.SH",
                "con_code": "000001.SZ",
                "weight": 2,
            },
        )

        with self.assertRaisesRegex(TushareDataError, "conflicting weights"):
            upsert_weight_stage(  # type: ignore[arg-type]
                object(), run_id=1, unit_key="unit", rows=rows
            )


class IndexPitCliMenuTests(unittest.TestCase):
    def test_cli_basic_dry_run_is_one_json_object(self):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(
                ["ingest", "index-pit", "--phase", "basic", "--output", "json"]
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(payload["parameters"]["phase"], "basic")
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_requires_execute_and_yes_together(self):
        stderr = StringIO()
        with redirect_stderr(stderr):
            status = main(
                ["ingest", "index-pit", "--phase", "basic", "--execute"]
            )

        self.assertEqual(status, 2)
        self.assertIn("--execute", stderr.getvalue())

    def test_text_result_prints_top_level_error(self):
        output = StringIO()
        with redirect_stdout(output):
            _emit_index_pit_result(
                JobResult(
                    job="ingest.index_pit",
                    status="failed",
                    run_id=12,
                    parameters={},
                    parameter_sources={},
                    error_message="max_api_calls reached",
                ),
                output="text",
            )

        self.assertIn("错误: max_api_calls reached", output.getvalue())

    def test_menu_index_pit_cancel_only_runs_dry_preflight(self):
        preflight = JobPreflight(
            job="ingest.index_pit",
            job_module="fdp_cn.tushare.index_pit",
            target_tables=["hq_idx_basic"],
            work_units=1,
            estimated_api_calls=1,
            parameters={"phase": "basic"},
            parameter_sources={"phase": "menu"},
        )

        class FakeJob:
            def __init__(self):
                self.requests = []

            def run(self, request, **kwargs):
                self.requests.append(request)
                return JobResult(
                    job="ingest.index_pit",
                    status="dry_run",
                    run_id=None,
                    parameters=preflight.parameters,
                    parameter_sources=preflight.parameter_sources,
                    work_units_total=1,
                    preflight=preflight,
                )

        fake = FakeJob()
        answers = iter(("7", "basic", "", "n", "0"))
        output: list[str] = []

        status = run_menu(
            index_pit_job=fake,  # type: ignore[arg-type]
            input_func=lambda prompt: next(answers),
            output=output.append,
        )

        self.assertEqual(status, 0)
        self.assertEqual(len(fake.requests), 1)
        self.assertFalse(fake.requests[0].execute)
        self.assertIn("已取消，没有调用 API 或写数据库。", output)


def _sw_daily_response(values: dict[str, object]) -> TushareResponse:
    return TushareResponse(
        endpoint_key=SW_DAILY_SPEC.key,
        api_name=SW_DAILY_SPEC.api_name,
        fields=SW_DAILY_SPEC.fields,
        items=(
            (
                "801863.SI",
                "20131023",
                "新股指数",
                *(values[name] for name in SW_DAILY_DECIMALS),
            ),
        ),
        attempts=1,
    )


def _metadata(code: str, category: str) -> IndexMetadata:
    return IndexMetadata(
        index_code=code,
        index_name=code,
        index_fullname=None,
        market="CSI",
        publisher="测试",
        category=category,
        index_type=None,
        list_date=date(2000, 1, 1),
        exp_date=None,
    )


def _weight_unit_payload(
    metadata: IndexMetadata,
    month_start: date,
) -> dict[str, object]:
    table_name = "idx_member_pit"
    return {
        "unit_key": f"{table_name}:{metadata.index_code}:{month_start:%Y%m}",
        "table_name": table_name,
        "metadata": {
            **metadata.__dict__,
            "list_date": metadata.list_date.isoformat() if metadata.list_date else None,
            "exp_date": metadata.exp_date.isoformat() if metadata.exp_date else None,
        },
        "month_start": month_start.isoformat(),
        "month_end": (_next_test_month(month_start) - timedelta(days=1)).isoformat(),
    }


def _next_test_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _checkpoint() -> dict[str, object]:
    return {
        "cursor": {"unit_index": 0, "offset": 0},
        "counters": {
            "units_completed": 0,
            "units_failed": 0,
            "pages_committed": 0,
            "rows_fetched": 0,
            "rows_cleaned": 0,
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_rejected": 0,
            "api_calls": 0,
        },
        "failures": [],
    }


def _basic_unit() -> EndpointUnit:
    return EndpointUnit(
        endpoint_key=INDEX_BASIC_SPEC.key,
        scope_key="basic",
        params={},
        page_limit=8_000,
    )


def _response(*, attempts: int = 1) -> TushareResponse:
    return TushareResponse(
        endpoint_key=INDEX_BASIC_SPEC.key,
        api_name=INDEX_BASIC_SPEC.api_name,
        fields=INDEX_BASIC_SPEC.fields,
        items=(tuple(None for _field in INDEX_BASIC_SPEC.fields),),
        attempts=attempts,
    )


def _full_checkpoint(
    *, kind: str, phase: str, units: list[dict[str, object]]
) -> dict[str, object]:
    parameters = {
        "phase": phase,
        "date_from": None,
        "date_to": None,
        "months": 1 if kind == "weight" else None,
        "codes": ["000300.SH"] if kind == "weight" else [],
    }
    checkpoint = _checkpoint()
    checkpoint.update(
        {
            "version": 1,
            "kind": kind,
            "phase": phase,
            "parameters": parameters,
            "units": units,
            "preflight": {"work_units": len(units)},
            "plan_hash": _checkpoint_plan_hash(kind, parameters, units),
        }
    )
    return checkpoint


if __name__ == "__main__":
    unittest.main()
