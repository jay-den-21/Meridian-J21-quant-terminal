from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import pandas as pd

# The compatibility package loads configuration at import time. Use an explicit
# synthetic module so unit tests never read the operator's private YAML or token.
_logs = TemporaryDirectory(prefix="j21-cn-test-logs-")
unittest.addModuleCleanup(_logs.cleanup)
_constant = ModuleType("basis.constant")
_constant.ts2db_config = SimpleNamespace(
    log_path=_logs.name,
    dbPath="mysql+pymysql://localhost/a_share",
    ts2db_config={"server_config": [], "run_config": {}},
    retry_times=3,
    retry_sleep_time=0,
)
_log_module = ModuleType("basis.log_man")
_log_module.logging = mock.Mock()
_log_module.Start_loggings = mock.Mock()
with mock.patch.dict(
    sys.modules, {"basis.constant": _constant, "basis.log_man": _log_module}
):
    import basis

    basis.constant = _constant
    from basis import init_env, tools
    from deal_data import deal_duplicatetData as duplicate_data
    from get_ph_data_from_ts.stk import Get_stk_cyq_chips as cyq_chips


class _FixtureEndpoint(tools.ts2db_father_template):
    def _run(self):
        return 1


def _bare_endpoint(**params):
    endpoint = object.__new__(_FixtureEndpoint)
    endpoint.df = None
    endpoint.df_get_count_all = 0
    endpoint.df_clean_count_all = 0
    endpoint.df_write_count_all = 0
    endpoint.df_cache = None
    endpoint.df_cache_count_all = 0
    endpoint.params = SimpleNamespace(**params)
    return endpoint


class BasisRuntimeBehaviorTests(unittest.TestCase):
    def test_initialization_logs_use_j21_database_product_name(self):
        api = object()
        with (
            mock.patch.object(init_env, "_tushare_token", return_value="test-token"),
            mock.patch.object(init_env.ts, "set_token"),
            mock.patch.object(init_env.ts, "pro_api", return_value=api),
            mock.patch.object(init_env, "logging") as logger,
        ):
            self.assertIs(init_env.init_ts_pro(), api)
            self.assertIs(init_env.init_ts(), init_env.ts)

        messages = [str(call.args[0]) for call in logger.info.call_args_list]
        self.assertEqual(len(messages), 2)
        self.assertTrue(
            all("J21 database 框架版本: 7.0" in message for message in messages)
        )
        self.assertTrue(
            all(
                "database_system_cli_cn 框架版本" not in message for message in messages
            )
        )

    def test_controller_adds_project_root_before_importing_basis(self):
        controller = (
            Path(__file__).resolve().parents[1]
            / "主控程序"
            / "盘后__串行抓取接口列表.py"
        )
        source = controller.read_text(encoding="utf-8")

        self.assertIn("PROJECT_ROOT = Path(__file__).resolve().parents[1]", source)
        self.assertLess(
            source.index("sys.path.insert(0, str(PROJECT_ROOT))"),
            source.index("from basis import *"),
        )

    def test_template_log_titles_use_j21_database_product_name(self):
        template_classes = (
            tools.ts2db_by_limit_template,
            tools.ts2db_by_date_template,
            tools.ts2db_by_period_template,
            tools.ts2db_by_codelist_template,
            tools.ts2db_by_period_and_codelist_template,
            tools.ts2db_by_date_and_codelist_template,
            tools.ts2db_rt_by_src_template,
            tools.ts2db_rt_by_src_and_codelist_template,
        )

        for template_class in template_classes:
            with self.subTest(template=template_class.__name__):
                endpoint = object.__new__(template_class)
                endpoint.params = SimpleNamespace(table_name="hq_test")
                endpoint.ts2db_init_after()
                self.assertTrue(
                    endpoint.params.msg_title.startswith("J21 database[")
                )

    def test_cyq_chips_uses_the_official_6000_row_page_limit(self):
        provider = mock.Mock(return_value=pd.DataFrame())
        endpoint = object.__new__(cyq_chips.get_stk_cyq_chips)
        endpoint.params = SimpleNamespace(
            ts_pro=SimpleNamespace(cyq_chips=provider),
            db_engine=object(),
            one_time_rows_limit=50_000,
            code="000001.SZ",
            str_date="20260801",
            end_date="20260812",
            offset=0,
        )

        with mock.patch.object(
            cyq_chips.init_data,
            "init_codeList",
            return_value=pd.DataFrame({"ts_code": ["000001.SZ"]}),
        ):
            endpoint.ts2db_init()
        endpoint.ts2db_get_data()

        self.assertEqual(endpoint.params.one_time_rows_limit, 6_000)
        provider.assert_called_once_with(
            ts_code="000001.SZ",
            start_date="20260801",
            end_date="20260812",
            limit=6_000,
            offset=0,
        )

    def test_cyq_chips_paginates_with_official_6000_row_offsets(self):
        provider = mock.Mock(
            side_effect=(
                pd.DataFrame({"row": range(6_000)}),
                pd.DataFrame({"row": range(6_000)}),
                pd.DataFrame({"row": range(2_344)}),
            )
        )
        endpoint = object.__new__(cyq_chips.get_stk_cyq_chips)
        endpoint.df = None
        endpoint.df_get_count_all = 0
        endpoint.df_clean_count_all = 0
        endpoint.df_write_count_all = 0
        endpoint.ts_api_call_count_all = 0
        endpoint.params = SimpleNamespace(
            ts_pro=SimpleNamespace(cyq_chips=provider),
            db_engine=object(),
            one_time_rows_limit=50_000,
            code="000001.SZ",
            str_date="20260801",
            end_date="20260812",
            offset=0,
            retry_times=1,
            retry_sleep_time=0,
            times_limit_in_1min=100_000,
            sleep_time=0,
            msg_title="J21 database[日期段+代码列表模式][hq_stk_cyq_chips]：",
        )

        with mock.patch.object(
            cyq_chips.init_data,
            "init_codeList",
            return_value=pd.DataFrame({"ts_code": ["000001.SZ"]}),
        ):
            endpoint.ts2db_init()
        endpoint.ts2db_clean_data = mock.Mock()
        endpoint.ts2db_write_db = mock.Mock(side_effect=lambda: len(endpoint.df))

        with mock.patch.object(tools, "logging"):
            final_count, calls = endpoint._run_paginated()

        self.assertEqual(final_count, 2_344)
        self.assertEqual(calls, 3)
        self.assertEqual(
            [call.kwargs["offset"] for call in provider.call_args_list],
            [0, 6_000, 12_000],
        )
        self.assertTrue(
            all(call.kwargs["limit"] == 6_000 for call in provider.call_args_list)
        )
        self.assertEqual(endpoint.df_get_count_all, 14_344)
        self.assertEqual(endpoint.df_write_count_all, 14_344)

    def test_fetch_retries_are_bounded_and_final_failure_is_visible(self):
        endpoint = _bare_endpoint(
            msg_title="J21 database[测试模式][hq_test]：",
            table_name="hq_test",
            retry_times=3,
            retry_sleep_time=0,
        )
        endpoint.ts2db_get_data = mock.Mock(
            side_effect=ConnectionError("planned disconnect")
        )

        with mock.patch.object(tools, "logging") as logger:
            with self.assertRaisesRegex(ConnectionError, "planned disconnect"):
                endpoint.ts2db_get_data_agent()

        self.assertEqual(endpoint.ts2db_get_data.call_count, 3)
        warning_text = "\n".join(
            str(call.args[0]) for call in logger.warning.call_args_list
        )
        self.assertIn("第 1/3 次", warning_text)
        self.assertIn("第 2/3 次", warning_text)
        self.assertIn("等待 0 秒后重试", warning_text)
        self.assertIn("连续失败 3 次", logger.error.call_args.args[0])
        self.assertIn("停止当前接口", logger.error.call_args.args[0])

    def test_smaller_server_page_enables_adaptive_pagination(self):
        endpoint = _bare_endpoint(
            one_time_rows_limit=50_000,
            offset=0,
            times_limit_in_1min=100_000,
            sleep_time=0,
        )
        offsets = []
        pages = iter((6_000, 6_000, 1_096))

        def run_one_page():
            offsets.append(endpoint.params.offset)
            count = next(pages)
            return count, count, count

        endpoint._run_one_page = run_one_page

        with mock.patch.object(tools, "logging") as logger:
            final_count, calls = endpoint._run_paginated()

        self.assertEqual(final_count, 1_096)
        self.assertEqual(calls, 3)
        self.assertEqual(offsets, [0, 6_000, 12_000])
        self.assertEqual(endpoint.params.one_time_rows_limit, 6_000)
        info_text = "\n".join(str(call.args[0]) for call in logger.info.call_args_list)
        self.assertIn("检测到该接口限制为 6000 每次", info_text)
        self.assertIn("框架启动自适应", info_text)

    def test_each_pagination_scope_restores_the_getter_page_limit(self):
        endpoint = _bare_endpoint(
            one_time_rows_limit=8_000,
            offset=0,
            times_limit_in_1min=100_000,
            sleep_time=0,
        )
        endpoint._configured_one_time_rows_limit = 8_000
        requested_limits = []
        pages = iter((3, 0, 2, 0))

        def run_one_page():
            requested_limits.append(endpoint.params.one_time_rows_limit)
            count = next(pages)
            return count, count, count

        endpoint._run_one_page = run_one_page

        with mock.patch.object(tools, "logging"):
            endpoint._run_paginated()
            endpoint._run_paginated()

        self.assertEqual(requested_limits, [8_000, 3, 8_000, 2])

    def test_run_logs_lifecycle_and_disposes_database_engine(self):
        engine = mock.Mock()
        endpoint = _bare_endpoint(
            table_name="hq_test",
            table_name_cn="测试表",
            msg_title="J21 database[测试模式][hq_test]：",
            db_engine=engine,
            ts=object(),
            ts_pro=object(),
            ts_api=object(),
            auto_detect__break_point_type=0,
            data_already_ok=False,
        )
        endpoint.df_get_count_all = 12
        endpoint.df_clean_count_all = 11
        endpoint.df_write_count_all = 10
        endpoint.ts2db_set_db_index = mock.Mock()
        endpoint.ts2db_clean_up_data = mock.Mock()
        endpoint.ts2db_after_run = mock.Mock()

        with mock.patch.object(tools, "logging") as logger:
            self.assertEqual(endpoint.run(), 1)

        success_text = "\n".join(
            str(call.args[0]) for call in logger.success.call_args_list
        )
        info_text = "\n".join(str(call.args[0]) for call in logger.info.call_args_list)
        self.assertIn("数据表 hq_test (测试表) 开始同步数据", success_text)
        self.assertIn("本次总共抓取数据 12 条", info_text)
        self.assertIn("清洗后 11 最终入库 10", info_text)
        engine.dispose.assert_called_once_with()
        self.assertIsNone(endpoint.params.db_engine)
        self.assertIsNone(endpoint.params.ts_api)

    def test_run_failure_propagates_and_disposes_database_engine(self):
        engine = mock.Mock()
        endpoint = _bare_endpoint(
            table_name="hq_test",
            table_name_cn="测试表",
            msg_title="J21 database[测试模式][hq_test]：",
            db_engine=engine,
            ts=object(),
            ts_pro=object(),
            ts_api=object(),
            auto_detect__break_point_type=0,
            data_already_ok=False,
        )
        endpoint._run = mock.Mock(
            side_effect=ConnectionError("planned terminal failure")
        )

        with mock.patch.object(tools, "logging") as logger:
            with self.assertRaisesRegex(
                ConnectionError,
                "planned terminal failure",
            ):
                endpoint.run()

        engine.dispose.assert_called_once_with()
        self.assertIn("同步失败", logger.error.call_args.args[0])
        self.assertIsNone(endpoint.params.db_engine)

    def test_each_page_logs_scope_and_row_counts(self):
        endpoint = _bare_endpoint(
            msg_title="J21 database[日期段+代码列表模式][hq_test]：",
            str_date="20250501",
            end_date="20260812",
            code="000001.SZ",
        )
        endpoint.ts2db_get_data = mock.Mock(
            return_value=pd.DataFrame({"x": range(6_000)})
        )

        def clean_data():
            endpoint.df = endpoint.df.iloc[:5_999]

        endpoint.ts2db_clean_data = clean_data
        endpoint.ts2db_write_db = mock.Mock(return_value=5_998)

        with mock.patch.object(tools, "logging") as logger:
            self.assertEqual(endpoint._run_one_page(), (6_000, 5_999, 5_998))

        message = logger.info.call_args.args[0]
        self.assertIn("对应的接口已调用 1次", message)
        self.assertIn("日期段 20250501 到 20260812", message)
        self.assertIn("000001.SZ", message)
        self.assertIn("抓取条数 6000 清洗后 5999 最终入库 5998", message)

    def test_page_scope_descriptions_cover_every_batch_template(self):
        cases = (
            (
                "J21 database[全加载模式][hq_test]：",
                {},
                "",
            ),
            (
                "J21 database[逐日模式][hq_test]：",
                {"idate": "20260811"},
                "抓取日期 20260811",
            ),
            (
                "J21 database[日期段模式][hq_test]：",
                {"str_date": "20260801", "end_date": "20260811"},
                "抓取日期 20260801 到 20260811",
            ),
            (
                "J21 database[代码列表模式][hq_test]：",
                {"code": "000001.SZ,600000.SH"},
                "从 000001.SZ 到 600000.SH 共 2 个代码的数据",
            ),
            (
                "J21 database[逐日+代码模式][hq_test]：",
                {"idate": "20260811", "code": "000001.SZ"},
                "在日期 20260811 上",
            ),
            (
                "J21 database[实时模式_按数据源][hq_test]：",
                {"src": "sina"},
                "数据源 sina",
            ),
            (
                "J21 database[实时模式_按数据源+代码列表][hq_test]：",
                {"src": "dc", "code": "000001.SZ"},
                "数据源 dc",
            ),
        )
        for title, overrides, expected in cases:
            with self.subTest(title=title):
                params = {
                    "msg_title": title,
                    "str_date": "",
                    "end_date": "",
                    "idate": "",
                    "code": "",
                }
                params.update(overrides)
                endpoint = _bare_endpoint(**params)
                self.assertIn(expected, endpoint._page_scope_description())

    def test_realtime_result_uses_the_same_per_call_log(self):
        endpoint = _bare_endpoint(
            msg_title="J21 database[实时模式_按数据源][hq_test]：",
            src="sina",
            code="",
        )

        with mock.patch.object(tools, "logging") as logger:
            endpoint._log_call_result(12, 11, 10)

        message = logger.info.call_args.args[0]
        self.assertIn("对应的接口已调用 1次", message)
        self.assertIn("数据源 sina", message)
        self.assertIn("抓取条数 12 清洗后 11 最终入库 10", message)


class DuplicateCleanupBehaviorTests(unittest.TestCase):
    def test_duplicate_scope_rejects_sql_like_values(self):
        params = SimpleNamespace(
            deal_duplicate_scope_filters={
                "ts_code": "000001.SZ' or 1=1 --",
            }
        )
        with self.assertRaisesRegex(ValueError, "scope value"):
            duplicate_data._scope_filters(params)

    def test_duplicate_cleanup_deletes_selected_primary_keys_in_one_batch(self):
        executed = []

        class Result:
            rowcount = 2

        class Engine:
            def execute(self, sql):
                executed.append(sql)
                if sql.startswith("alter table") or sql.startswith("create index"):
                    raise RuntimeError("already exists")
                return Result()

        duplicate_id_reads = 0

        def read_sql(query, _engine):
            nonlocal duplicate_id_reads
            if query.startswith("select count(*) as duplicate_groups"):
                self.assertIn("`ts_code` = '000001.SZ'", query)
                return pd.DataFrame([[2, 4]])
            if query.startswith("select old.`id`"):
                self.assertIn("old.`ts_code` = '000001.SZ'", query)
                self.assertIn("newer.`ts_code` = '000001.SZ'", query)
                duplicate_id_reads += 1
                if duplicate_id_reads == 1:
                    return pd.DataFrame({"id": [10, 11]})
                return pd.DataFrame({"id": []})
            raise AssertionError(query)

        params = SimpleNamespace(
            str_date="20250501",
            end_date="20260812",
            db_engine=Engine(),
            deal_duplicate_strict_date_scope=True,
            deal_duplicate_scope_filters={"ts_code": "000001.SZ"},
        )

        with mock.patch.object(duplicate_data, "have_table", return_value=True):
            with mock.patch.object(
                duplicate_data.pd, "read_sql_query", side_effect=read_sql
            ):
                with mock.patch.object(duplicate_data, "logging") as logger:
                    duplicate_data.deal_duplicate_in_hq_lost(
                        params,
                        "hq_stk_cyq_chips",
                        "trade_date, ts_code, price",
                    )

        delete_statements = [sql for sql in executed if sql.startswith("delete")]
        self.assertEqual(
            delete_statements,
            ["delete from `hq_stk_cyq_chips` where id in (10, 11)"],
        )
        self.assertNotIn("not in", "\n".join(executed).lower())
        info_text = "\n".join(str(call.args[0]) for call in logger.info.call_args_list)
        warning_text = "\n".join(
            str(call.args[0]) for call in logger.warning.call_args_list
        )
        self.assertIn("找到重复数据 2 行", warning_text)
        self.assertIn("已删除 2/2 行", info_text)


if __name__ == "__main__":
    unittest.main()
