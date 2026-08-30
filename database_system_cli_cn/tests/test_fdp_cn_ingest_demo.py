from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fdp_cn.cli import main
from fdp_cn.config import tushare_runtime_config_from_env
from fdp_cn.config import database_url_from_env
from fdp_cn.menu import run_menu
from fdp_cn.tushare.catalog import CATALOG, get_endpoint_spec
from fdp_cn.tushare.legacy import LegacyEndpointRunner, LegacyRunResult
from fdp_cn.tushare.legacy_worker import run_endpoint
from fdp_cn.tushare.models import EndpointPlanRequest
from fdp_cn.tushare.planning import plan_endpoint_units
from fdp_cn.tushare.service import IngestPlan, IngestService, list_endpoints


class CatalogAndPlanningTests(unittest.TestCase):
    def test_catalog_exposes_all_legacy_variants_and_tables(self):
        self.assertEqual(len(CATALOG), 93)
        self.assertEqual(len({spec.target_table for spec in CATALOG}), 88)

    def test_retired_limit_list_is_disabled_but_replacement_remains_available(self):
        retired = get_endpoint_spec("stk_limit.stk_limit_list")
        replacement = get_endpoint_spec("stk_limit.stk_limit_list_d")
        rows = {row["key"]: row for row in list_endpoints()}

        self.assertEqual(retired.capability.kind, "disabled_unsupported")
        self.assertFalse(rows[retired.key]["enabled"])
        self.assertNotEqual(replacement.capability.kind, "disabled_unsupported")
        self.assertTrue(rows[replacement.key]["enabled"])

    def test_daily_and_sw_daily_use_documented_page_limits(self):
        daily = get_endpoint_spec("daily")
        sw_daily = get_endpoint_spec("sw_daily")

        daily_unit = plan_endpoint_units(
            daily,
            EndpointPlanRequest(
                date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 2),
                codes=("000001.SZ", "600000.SH"),
            ),
        )[0]
        sw_unit = plan_endpoint_units(
            sw_daily,
            EndpointPlanRequest(
                date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 2),
                codes=("801010.SI",),
            ),
        )[0]

        self.assertEqual(daily_unit.page_limit, 6000)
        self.assertEqual(daily_unit.params["ts_code"], "000001.SZ,600000.SH")
        self.assertEqual(sw_unit.page_limit, 4000)
        self.assertEqual(sw_unit.params["ts_code"], "801010.SI")

    def test_stock_basic_fanout_and_cyq_scope_are_preserved(self):
        listed = plan_endpoint_units(get_endpoint_spec("stock_basic"))
        all_statuses = plan_endpoint_units(get_endpoint_spec("stock_basic_all"))
        cyq = plan_endpoint_units(
            get_endpoint_spec("cyq_chips"),
            EndpointPlanRequest(
                date_from="20200101",
                date_to="20250801",
                codes=("000001.SZ", "600000.SH"),
            ),
        )

        self.assertEqual([unit.params["list_status"] for unit in listed], ["L"])
        self.assertEqual(
            [unit.params["list_status"] for unit in all_statuses],
            ["L", "D", "P"],
        )
        self.assertEqual(len(cyq), 2)
        self.assertEqual([unit.page_limit for unit in cyq], [6000, 6000])
        self.assertEqual(
            [unit.params["ts_code"] for unit in cyq],
            ["000001.SZ", "600000.SH"],
        )
        self.assertEqual(cyq[0].params["start_date"], "20200101")
        self.assertEqual(cyq[0].params["end_date"], "20250801")


class ServiceAndCompatibilityTests(unittest.TestCase):
    def test_init_and_all_have_honest_backends(self):
        service = IngestService()
        start = date(2026, 8, 1)
        end = date(2026, 8, 2)

        init_plan = service.plan_init(date_from=start, date_to=end)
        all_plan = service.plan_all(date_from=start, date_to=end)
        by_key = {item.key: item for item in all_plan.items}

        self.assertTrue(init_plan.items)
        self.assertTrue(
            all(item.backend == "legacy_compat" for item in init_plan.items)
        )
        self.assertEqual(by_key["daily"].backend, "direct")
        self.assertEqual(by_key["sw_daily"].backend, "direct")
        self.assertEqual(by_key["stock_basic"].backend, "direct")
        self.assertEqual(by_key["fin.fin_balancesheet_vip"].backend, "legacy_compat")
        self.assertNotIn("stk.stk_1min", by_key)
        self.assertNotIn("realtime.rt_stk_tick_east", by_key)

    def test_financial_legacy_runner_uses_isolated_child(self):
        calls: list[tuple[list[str], dict[str, object]]] = []

        def execute(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        runner = LegacyEndpointRunner(
            executor=execute,
            python_executable="/private/tmp/python-for-test",
        )
        result = runner.run(
            get_endpoint_spec("fin.fin_balancesheet_vip"),
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            params={"report_type": 1},
            timeout_seconds=90,
        )

        self.assertEqual(result.status, "success")
        command, kwargs = calls[0]
        self.assertEqual(
            command[:4],
            [
                "/private/tmp/python-for-test",
                "-B",
                "-m",
                "fdp_cn.tushare.legacy_worker",
            ],
        )
        self.assertIn("fin.fin_balancesheet_vip", command)
        self.assertEqual(kwargs["timeout"], 90)

    def test_legacy_runner_reports_timeout_without_raising(self):
        def execute(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        runner = LegacyEndpointRunner(executor=execute)
        result = runner.run(
            get_endpoint_spec("fin.fin_balancesheet_vip"),
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            timeout_seconds=90,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.returncode, 124)
        self.assertIn("90 秒", result.message)

    def test_legacy_runner_reports_nonzero_exit_without_raising(self):
        def execute(command, **kwargs):
            return subprocess.CompletedProcess(command, 7)

        runner = LegacyEndpointRunner(executor=execute)
        result = runner.run(
            get_endpoint_spec("fin.fin_balancesheet_vip"),
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.returncode, 7)
        self.assertIn("退出码 7", result.message)

    def test_legacy_runner_reports_spawn_failure_without_stopping_batch(self):
        def execute(command, **kwargs):
            raise OSError("interpreter unavailable")

        runner = LegacyEndpointRunner(executor=execute)
        service = IngestService(
            legacy_runner=runner,
            runtime_factory=lambda: (_ for _ in ()).throw(
                AssertionError("runtime used")
            ),
        )
        first = service.plan_endpoint(
            "fin.fin_balancesheet_vip",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            backend="legacy",
        )
        second = service.plan_endpoint(
            "fin.fin_cashflow_vip",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            backend="legacy",
        )
        plan = IngestPlan(
            mode="all",
            items=first.items + second.items,
            date_from=first.date_from,
            date_to=first.date_to,
        )

        result = service.run(plan, execute=True, confirmed=True)

        self.assertEqual(result.status, "partial_failed")
        self.assertEqual(result.endpoints_completed, 2)
        self.assertEqual(result.endpoints_failed, 2)
        self.assertTrue(
            all("启动失败" in failure.message for failure in result.failures)
        )

    def test_financial_worker_uses_the_original_report_type_wrapper(self):
        received: list[object] = []
        fake_module = SimpleNamespace(
            get_fin_balancesheet_vip_run=received.append,
            get_fin_balancesheet_vip=lambda params: (_ for _ in ()).throw(
                AssertionError("class path used")
            ),
        )

        with (
            patch("fdp_cn.tushare.legacy_worker._assert_legacy_database_target"),
            patch(
                "fdp_cn.tushare.legacy_worker._params",
                return_value=SimpleNamespace(),
            ),
            patch(
                "fdp_cn.tushare.legacy_worker.importlib.import_module",
                return_value=fake_module,
            ),
        ):
            run_endpoint(
                "fin.fin_balancesheet_vip",
                date_from="20250101",
                date_to="20251231",
                params={"report_type": 1},
            )

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].report_type, 1)

    def test_legacy_worker_rejects_old_database_before_importing_getter(self):
        with (
            patch(
                "fdp_cn.tushare.legacy_worker._configured_database_name",
                return_value="qtdb_pro_rep",
            ),
            patch(
                "fdp_cn.tushare.legacy_worker.importlib.import_module"
            ) as import_module,
        ):
            with self.assertRaisesRegex(RuntimeError, "requires config db=a_share"):
                run_endpoint(
                    "fin.fin_balancesheet_vip",
                    date_from="20250101",
                    date_to="20251231",
                )

        import_module.assert_not_called()

    def test_legacy_failure_does_not_stop_the_next_endpoint(self):
        class FakeLegacyRunner:
            def __init__(self):
                self.keys: list[str] = []

            def run(self, spec, **kwargs):
                self.keys.append(spec.key)
                if len(self.keys) == 1:
                    return LegacyRunResult(
                        spec.key, spec.target_table, "failed", 1, "boom"
                    )
                return LegacyRunResult(spec.key, spec.target_table, "success", 0, "ok")

        runner = FakeLegacyRunner()
        service = IngestService(
            legacy_runner=runner,  # type: ignore[arg-type]
            runtime_factory=lambda: (_ for _ in ()).throw(
                AssertionError("runtime used")
            ),
        )
        first = service.plan_endpoint(
            "fin.fin_balancesheet_vip",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            backend="legacy",
        )
        second = service.plan_endpoint(
            "fin.fin_cashflow_vip",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            backend="legacy",
        )
        plan = IngestPlan(
            mode="all",
            items=first.items + second.items,
            date_from=first.date_from,
            date_to=first.date_to,
        )

        result = service.run(plan, execute=True, confirmed=True)

        self.assertEqual(
            runner.keys, ["fin.fin_balancesheet_vip", "fin.fin_cashflow_vip"]
        )
        self.assertEqual(result.status, "partial_failed")
        self.assertEqual(result.endpoints_completed, 2)
        self.assertEqual(result.endpoints_failed, 1)

    def test_unexpected_legacy_runner_exception_does_not_stop_next_endpoint(self):
        class RaisingLegacyRunner:
            def __init__(self):
                self.keys: list[str] = []

            def run(self, spec, **kwargs):
                self.keys.append(spec.key)
                if len(self.keys) == 1:
                    raise RuntimeError("adapter failed")
                return LegacyRunResult(
                    spec.key,
                    spec.target_table,
                    "success",
                    0,
                    "ok",
                )

        runner = RaisingLegacyRunner()
        service = IngestService(
            legacy_runner=runner,  # type: ignore[arg-type]
            runtime_factory=lambda: (_ for _ in ()).throw(
                AssertionError("runtime used")
            ),
        )
        first = service.plan_endpoint(
            "fin.fin_balancesheet_vip",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            backend="legacy",
        )
        second = service.plan_endpoint(
            "fin.fin_cashflow_vip",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            backend="legacy",
        )
        plan = IngestPlan(
            mode="all",
            items=first.items + second.items,
            date_from=first.date_from,
            date_to=first.date_to,
        )

        result = service.run(plan, execute=True, confirmed=True)

        self.assertEqual(
            runner.keys, ["fin.fin_balancesheet_vip", "fin.fin_cashflow_vip"]
        )
        self.assertEqual(result.status, "partial_failed")
        self.assertEqual(result.endpoints_completed, 2)
        self.assertEqual(result.endpoints_failed, 1)


class CliAndMenuTests(unittest.TestCase):
    def test_database_url_accepts_numeric_yaml_password(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "fdp_cn.config._load_config",
                return_value={
                    "db_config": {
                        "user": "jayden",
                        "pwd": 123456,
                        "host": "127.0.0.1",
                        "port": 3306,
                        "db": "a_share",
                    }
                },
            ),
        ):
            url = database_url_from_env()

        self.assertEqual(url.password, "123456")
        self.assertEqual(url.database, "a_share")

    def test_runtime_retry_settings_can_be_environment_only(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "TUSHARE_MAX_RETRIES": "2",
                    "TUSHARE_RETRY_DELAY_SECONDS": "7",
                },
                clear=False,
            ),
            patch(
                "fdp_cn.config._load_config",
                side_effect=AssertionError("private config read"),
            ),
        ):
            config = tushare_runtime_config_from_env()

        self.assertEqual(config.max_retries, 2)
        self.assertEqual(config.retry_delay_seconds, 7)

    def test_cli_daily_dry_run_is_one_json_object(self):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(
                [
                    "ingest",
                    "tushare",
                    "--endpoint",
                    "daily",
                    "--from",
                    "2026-08-01",
                    "--to",
                    "2026-08-02",
                    "--output",
                    "json",
                ]
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(payload["plan"]["items"][0]["key"], "daily")
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_list_exposes_points_tier_separately_from_page_limit(self):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(["ingest", "list", "--output", "json"])

        rows = {row["key"]: row for row in json.loads(stdout.getvalue())}
        self.assertEqual(status, 0)
        self.assertEqual(rows["daily"]["points_tier"], 10_000)
        self.assertEqual(rows["daily"]["page_limit"], 6_000)
        self.assertIsNone(rows["us.us_daily"]["points_tier"])
        self.assertEqual(rows["us.us_daily"]["access"], "separate_purchase")
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_rejects_batch_params_instead_of_silently_ignoring_them(self):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(
                [
                    "ingest",
                    "all",
                    "--from",
                    "2026-08-01",
                    "--to",
                    "2026-08-02",
                    "--param",
                    "trade_date=20260801",
                ]
            )

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--param 仅支持单接口模式", stderr.getvalue())

    def test_menu_is_chinese_first_and_cancel_does_not_execute(self):
        answers = iter(("2", "daily", "2026-08-01", "2026-08-02", "n", "0"))
        output: list[str] = []

        status = run_menu(
            input_func=lambda prompt: next(answers),
            output=output.append,
        )

        self.assertEqual(status, 0)
        self.assertIn("J21 database 数据菜单", output)
        self.assertIn("已取消，没有调用 API 或写数据库。", output)

    def test_menu_can_plan_a_financial_category_without_execution(self):
        answers = iter(("3", "fin", "2025-01-01", "2025-12-31", "", "n", "0"))
        output: list[str] = []

        status = run_menu(
            input_func=lambda prompt: next(answers),
            output=output.append,
        )

        self.assertEqual(status, 0)
        self.assertTrue(any("mode=category" in line for line in output))
        self.assertTrue(any("fin.fin_balancesheet_vip" in line for line in output))
        self.assertIn("已取消，没有调用 API 或写数据库。", output)

    def test_menu_pure_code_list_endpoint_accepts_codes(self):
        class RecordingService(IngestService):
            def __init__(self):
                super().__init__()
                self.received_codes: tuple[str, ...] | None = None

            def plan_endpoint(self, endpoint, **kwargs):
                self.received_codes = kwargs["codes"]
                return super().plan_endpoint(endpoint, **kwargs)

        service = RecordingService()
        answers = iter(("2", "idx.idx_sw_member", "801010.SI", "n", "0"))
        output: list[str] = []

        status = run_menu(
            service=service,
            input_func=lambda prompt: next(answers),
            output=output.append,
        )

        self.assertEqual(status, 0)
        self.assertEqual(service.received_codes, ("801010.SI",))
        self.assertIn("已取消，没有调用 API 或写数据库。", output)


if __name__ == "__main__":
    unittest.main()
