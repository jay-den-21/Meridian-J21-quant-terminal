from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

from fdp_cn.contracts import JobFailure, JobPreflight, JobResult
from fdp_cn.menu import run_menu
from fdp_cn.tushare.catalog import get_endpoint_spec
from fdp_cn.tushare.service import IngestPlan, IngestService


START = date(2026, 8, 1)
END = date(2026, 8, 2)
CODE = "000001.SZ"


class _RecordingDirectJob:
    def __init__(self, *, failing_endpoint: str | None = None) -> None:
        self.failing_endpoint = failing_endpoint
        self.requests = []

    def run(self, request, **kwargs):
        self.requests.append(request)
        if request.endpoint == self.failing_endpoint:
            raise ValueError("invalid endpoint-local parameter")
        preflight = JobPreflight(
            job="ingest.tushare",
            job_module="test",
            target_tables=[],
            work_units=1,
            estimated_api_calls=1,
            parameters={},
            parameter_sources={},
        )
        return JobResult(
            job="ingest.tushare",
            status="success",
            run_id=None,
            parameters={},
            parameter_sources={},
            work_units_total=1,
            work_units_completed=1,
            preflight=preflight,
        )


class _ReturnedGlobalFailureJob:
    def __init__(self, category: str) -> None:
        self.category = category
        self.requests = []

    def run(self, request, **kwargs):
        self.requests.append(request)
        return JobResult(
            job="ingest.tushare",
            status="failed",
            run_id=None,
            parameters={},
            parameter_sources={},
            failures=[JobFailure(request.endpoint, self.category, "global stop")],
            error_message="global stop",
        )


def _service(direct_job: _RecordingDirectJob | None = None) -> IngestService:
    return IngestService(
        direct_job=direct_job or _RecordingDirectJob(),  # type: ignore[arg-type]
        runtime_factory=lambda: SimpleNamespace(engine=object()),  # type: ignore[arg-type]
        control_initializer=lambda engine: None,
    )


class BatchScopeRoutingTests(unittest.TestCase):
    def test_legacy_code_scopes_match_their_actual_request_arguments(self):
        self.assertEqual(
            get_endpoint_spec("fin.fin_income").scope_kind,
            "code_date_range",
        )
        self.assertEqual(
            get_endpoint_spec("fut.fut_mapping").scope_kind,
            "code_date_range",
        )
        self.assertEqual(
            get_endpoint_spec("idx.idx_sw_member").scope_kind,
            "code_list",
        )
        self.assertEqual(
            get_endpoint_spec("idx.idx_sw_member_all").scope_kind,
            "code_list",
        )

    def test_plan_all_without_codes_routes_cyq_through_legacy_getter(self):
        plan = IngestService().plan_all(date_from=START, date_to=END)
        by_key = {item.key: item for item in plan.items}

        self.assertEqual(by_key["cyq_chips"].backend, "legacy_compat")
        self.assertEqual(by_key["daily"].backend, "direct")

    def test_batch_codes_are_forwarded_only_to_code_scoped_endpoint(self):
        direct_job = _RecordingDirectJob()
        service = _service(direct_job)
        full_plan = service.plan_all(
            date_from=START,
            date_to=END,
            codes=(CODE,),
        )
        by_key = {item.key: item for item in full_plan.items}
        self.assertEqual(by_key["cyq_chips"].backend, "direct")

        plan = IngestPlan(
            mode="all",
            items=tuple(by_key[key] for key in ("trade_cal", "daily", "cyq_chips")),
            date_from=START,
            date_to=END,
            codes=(CODE,),
        )
        result = service.run(plan, execute=True, confirmed=True)

        requests = {request.endpoint: request for request in direct_job.requests}
        self.assertEqual(result.status, "success")
        self.assertEqual(requests["trade_cal"].codes, ())
        self.assertEqual(requests["daily"].codes, ())
        self.assertEqual(requests["cyq_chips"].codes, (CODE,))

    def test_batch_codes_reach_pure_code_list_legacy_endpoints(self):
        class RecordingLegacyRunner:
            def __init__(self):
                self.calls = []

            def run(self, spec, **kwargs):
                self.calls.append((spec.key, kwargs["codes"]))
                return SimpleNamespace(status="success", message="ok")

        runner = RecordingLegacyRunner()
        service = IngestService(
            legacy_runner=runner,  # type: ignore[arg-type]
            runtime_factory=lambda: (_ for _ in ()).throw(
                AssertionError("runtime used")
            ),
        )
        full_plan = service.plan_all(
            date_from=START,
            date_to=END,
            codes=(CODE,),
        )
        by_key = {item.key: item for item in full_plan.items}
        keys = (
            "fin.fin_income",
            "fut.fut_mapping",
            "idx.idx_sw_member",
            "idx.idx_sw_member_all",
        )
        plan = IngestPlan(
            mode="all",
            items=tuple(by_key[key] for key in keys),
            date_from=START,
            date_to=END,
            codes=(CODE,),
        )

        result = service.run(plan, execute=True, confirmed=True)

        self.assertEqual(result.status, "success")
        self.assertEqual(runner.calls, [(key, (CODE,)) for key in keys])

    def test_single_endpoint_retains_explicit_codes(self):
        direct_job = _RecordingDirectJob()
        service = _service(direct_job)
        plan = service.plan_endpoint(
            "daily",
            date_from=START,
            date_to=END,
            codes=(CODE,),
        )

        service.run(plan, execute=True, confirmed=True)

        self.assertEqual(direct_job.requests[0].codes, (CODE,))

    def test_batch_params_are_rejected_instead_of_leaking_to_every_endpoint(self):
        with self.assertRaisesRegex(ValueError, "单接口"):
            IngestService().plan_category(
                "stk",
                date_from=START,
                date_to=END,
                params={"trade_date": "20260801"},
            )

    def test_direct_endpoint_value_error_is_recorded_and_batch_continues(self):
        direct_job = _RecordingDirectJob(failing_endpoint="trade_cal")
        service = _service(direct_job)
        full_plan = service.plan_all(date_from=START, date_to=END, codes=(CODE,))
        by_key = {item.key: item for item in full_plan.items}
        plan = IngestPlan(
            mode="all",
            items=tuple(by_key[key] for key in ("trade_cal", "daily")),
            date_from=START,
            date_to=END,
            codes=(CODE,),
        )

        result = service.run(plan, execute=True, confirmed=True)

        self.assertEqual(
            [request.endpoint for request in direct_job.requests],
            ["trade_cal", "daily"],
        )
        self.assertEqual(result.status, "partial_failed")
        self.assertEqual(result.endpoints_completed, 2)
        self.assertEqual(result.endpoints_failed, 1)
        self.assertEqual(result.failures[0].unit, "trade_cal")

    def test_returned_authentication_and_storage_failures_stop_the_batch(self):
        for category in ("authentication", "storage"):
            with self.subTest(category=category):
                direct_job = _ReturnedGlobalFailureJob(category)
                service = _service(direct_job)  # type: ignore[arg-type]
                full_plan = service.plan_all(
                    date_from=START,
                    date_to=END,
                    codes=(CODE,),
                )
                by_key = {item.key: item for item in full_plan.items}
                plan = IngestPlan(
                    mode="all",
                    items=tuple(by_key[key] for key in ("trade_cal", "daily")),
                    date_from=START,
                    date_to=END,
                )

                result = service.run(plan, execute=True, confirmed=True)

                self.assertEqual(
                    [request.endpoint for request in direct_job.requests],
                    ["trade_cal"],
                )
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.endpoints_completed, 1)

    def test_menu_all_and_category_plans_can_be_cancelled_without_execution(self):
        for answers in (
            ("5", "2026-08-01", "2026-08-02", "", "n", "0"),
            ("3", "stk", "2026-08-01", "2026-08-02", "", "n", "0"),
        ):
            with self.subTest(choice=answers[0]):
                output: list[str] = []
                status = run_menu(
                    service=IngestService(),
                    input_func=lambda prompt, values=iter(answers): next(values),
                    output=output.append,
                )

                self.assertEqual(status, 0)
                self.assertTrue(any("cyq_chips" in line for line in output))
                self.assertTrue(
                    any(
                        "cyq_chips" in line and "backend=legacy_compat" in line
                        for line in output
                    )
                )
                self.assertIn("已取消，没有调用 API 或写数据库。", output)


if __name__ == "__main__":
    unittest.main()
