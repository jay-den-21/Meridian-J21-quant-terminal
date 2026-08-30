from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from tools.verification import aggregate_original_endpoint_logs as aggregate


def _snapshot(table: str, *, rows: int | None, exists: bool = True) -> dict:
    return {
        "database": "fixture",
        "database_bytes": 4096,
        "table": table,
        "table_exists": exists,
        "table_rows_estimate": rows,
        "table_bytes": 1024 if exists else None,
    }


def _result(
    report_dir: Path,
    *,
    endpoint: str,
    table: str,
    log_name: str,
    warning: bool,
    error: bool = False,
) -> dict:
    return {
        "name": endpoint,
        "table": table,
        "group": "short",
        "start": "20260801",
        "end": "20260812",
        "sample_code": None,
        "returncode": 0,
        "saw_warning": warning,
        "saw_error": error,
        "duration_seconds": 1.25,
        "log": str(report_dir / "logs" / log_name),
        "final_database_snapshot": _snapshot(table, rows=5),
    }


class AggregateOriginalEndpointLogsTest(unittest.TestCase):
    def _report(self, root: Path) -> Path:
        report = root / "report"
        (report / "results").mkdir(parents=True)
        (report / "logs").mkdir()
        return report

    def test_aggregates_completed_and_log_only_entries_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = self._report(Path(temporary))
            completed_log_name = "001_get_fixture.log"
            completed_log = report / "logs" / completed_log_name
            completed_log.write_text(
                "\n".join(
                    (
                        "RUNNER_DB_BEFORE="
                        + json.dumps(_snapshot("hq_fixture", rows=0)),
                        "RUNNER_ENDPOINT="
                        + json.dumps(
                            {
                                "name": "get_fixture",
                                "table": "hq_fixture",
                                "group": "short",
                                "start": "20260801",
                                "end": "20260812",
                                "sample_code": None,
                            }
                        ),
                        "| INFO | 对应的接口已调用 1次，抓取条数 2 清洗后 2 最终入库 2",
                        "| INFO | 对应的接口已调用 1次，抓取条数 3 清洗后 3 最终入库 3",
                        "| INFO | 本次总共抓取数据 5 条，清洗后 5 最终入库 5！",
                        "| WARNING | 找到重复数据 2 行，共 2 条！",
                        "| SUCCESS | 删除 2 行重复数据（预期 2 行）！",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            result = _result(
                report,
                endpoint="get_fixture",
                table="hq_fixture",
                log_name=completed_log_name,
                warning=True,
            )
            (report / "results" / "get_fixture.json").write_text(
                json.dumps(result),
                encoding="utf-8",
            )

            incomplete_log = report / "logs" / "002_get_active.log"
            incomplete_log.write_text(
                "\n".join(
                    (
                        "RUNNER_DB_BEFORE="
                        + json.dumps(_snapshot("hq_active", rows=0)),
                        "RUNNER_ENDPOINT="
                        + json.dumps(
                            {
                                "name": "get_active",
                                "table": "hq_active",
                                "group": "short",
                                "start": "20260801",
                                "end": "20260812",
                                "sample_code": None,
                            }
                        ),
                        "| INFO | 对应的接口已调用 7次，抓取条数 4 清洗后 4 最终入库 4",
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            document = aggregate.aggregate_report(report)

            by_name = {item["endpoint"]: item for item in document["endpoints"]}
            completed = by_name["get_fixture"]
            self.assertEqual(
                completed["status"],
                "FRAMEWORK_LOG_PASS_WITH_DUPLICATE_CLEANUP",
            )
            self.assertEqual(completed["provider_calls_observed"], 2)
            self.assertEqual(completed["max_call_ordinal"], 1)
            self.assertEqual(completed["fetched_rows"], 5)
            self.assertEqual(completed["metrics_source"], "total_summary")
            self.assertEqual(completed["duplicate_rows_found"], 2)
            self.assertTrue(completed["duplicate_cleanup_complete"])

            incomplete = by_name["get_active"]
            self.assertEqual(incomplete["status"], "INCOMPLETE")
            self.assertEqual(incomplete["fetched_rows"], 4)
            self.assertEqual(incomplete["metrics_source"], "per_call_partial")
            self.assertIn("INCOMPLETE_LOG_ONLY", incomplete["anomaly_codes"])

            json_path = report / aggregate.JSON_OUTPUT_NAME
            markdown_path = report / aggregate.MARKDOWN_OUTPUT_NAME
            self.assertEqual(os.stat(json_path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(markdown_path).st_mode & 0o777, 0o600)
            self.assertEqual(
                json.loads(json_path.read_text(encoding="utf-8")),
                document,
            )
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("| endpoint | log | rc |", markdown)
            self.assertIn(
                "[logs/001_get_fixture.log](logs/001_get_fixture.log)",
                markdown,
            )
            self.assertIn(
                "[logs/002_get_active.log](logs/002_get_active.log)",
                markdown,
            )

    def test_generic_zero_row_warning_is_not_permission_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = self._report(Path(temporary))
            log_name = "001_get_empty.log"
            (report / "logs" / log_name).write_text(
                "\n".join(
                    (
                        "RUNNER_DB_BEFORE=" + json.dumps(_snapshot("hq_empty", rows=7)),
                        "RUNNER_ENDPOINT="
                        + json.dumps(
                            {
                                "name": "get_empty",
                                "table": "hq_empty",
                                "group": "short",
                                "start": "20260801",
                                "end": "20260812",
                                "sample_code": None,
                            }
                        ),
                        "| INFO | 对应的接口已调用 1次，抓取条数 0 清洗后 0 最终入库 0",
                        "| WARNING | 总抓取数据 0 条，可能是不在工作日或当前时间段没有数据，也可能当前账户对该接口没有权限！",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            result = _result(
                report,
                endpoint="get_empty",
                table="hq_empty",
                log_name=log_name,
                warning=True,
            )
            (report / "results" / "get_empty.json").write_text(
                json.dumps(result),
                encoding="utf-8",
            )

            document = aggregate.aggregate_report(report)
            item = document["endpoints"][0]
            self.assertEqual(item["status"], "EMPTY_AMBIGUOUS")
            self.assertIn("EMPTY_RESPONSE", item["anomaly_codes"])
            self.assertNotIn("PROVIDER_PERMISSION", item["anomaly_codes"])

    def test_reports_duplicate_cleanup_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = self._report(Path(temporary))
            log_name = "001_get_mismatch.log"
            (report / "logs" / log_name).write_text(
                "\n".join(
                    (
                        "RUNNER_DB_BEFORE="
                        + json.dumps(_snapshot("hq_mismatch", rows=199)),
                        "RUNNER_ENDPOINT="
                        + json.dumps(
                            {
                                "name": "get_mismatch",
                                "table": "hq_mismatch",
                                "group": "short",
                                "start": "20260801",
                                "end": "20260812",
                                "sample_code": None,
                            }
                        ),
                        "| INFO | 对应的接口已调用 1次，抓取条数 5 清洗后 5 最终入库 5",
                        "| INFO | 本次总共抓取数据 5 条，清洗后 5 最终入库 5！",
                        "| WARNING | 找到重复数据 100 行，共 199 条！",
                        "| SUCCESS | 删除 0 行重复数据（预期 199 行）！",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            result = _result(
                report,
                endpoint="get_mismatch",
                table="hq_mismatch",
                log_name=log_name,
                warning=True,
            )
            (report / "results" / "get_mismatch.json").write_text(
                json.dumps(result),
                encoding="utf-8",
            )

            document = aggregate.aggregate_report(report)
            item = document["endpoints"][0]
            self.assertEqual(item["status"], "DUPLICATE_CLEANUP_MISMATCH")
            self.assertEqual(item["duplicate_rows_found"], 199)
            self.assertEqual(item["duplicate_rows_deleted"], 0)
            self.assertEqual(item["duplicate_rows_expected"], 199)
            self.assertFalse(item["duplicate_cleanup_complete"])
            self.assertIn(
                "DUPLICATE_CLEANUP_MISMATCH",
                item["anomaly_codes"],
            )

    def test_explicit_rate_limit_is_not_mislabeled_as_code_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = self._report(Path(temporary))
            log_name = "001_get_limited.log"
            (report / "logs" / log_name).write_text(
                "\n".join(
                    (
                        "RUNNER_DB_BEFORE="
                        + json.dumps(_snapshot("hq_limited", rows=5)),
                        "RUNNER_ENDPOINT="
                        + json.dumps(
                            {
                                "name": "get_limited",
                                "table": "hq_limited",
                                "group": "short",
                                "start": "20260801",
                                "end": "20260812",
                                "sample_code": None,
                            }
                        ),
                        "| ERROR | 服务器返回错误：每小时最多访问该接口1次",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            result = _result(
                report,
                endpoint="get_limited",
                table="hq_limited",
                log_name=log_name,
                warning=False,
                error=True,
            )
            (report / "results" / "get_limited.json").write_text(
                json.dumps(result),
                encoding="utf-8",
            )

            document = aggregate.aggregate_report(report)
            item = document["endpoints"][0]
            self.assertEqual(item["status"], "EXTERNAL_RATE_LIMIT")
            self.assertIn("PROVIDER_RATE_LIMIT", item["anomaly_codes"])

    def test_retains_auxiliary_write_attempt_without_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = self._report(Path(temporary))
            aborted = report / "logs" / "000_financial_aborted.log"
            aborted.write_text(
                "\n".join(
                    (
                        "RUNNER_DB_BEFORE=" + json.dumps(_snapshot("hq_fin", rows=4)),
                        "RUNNER_ENDPOINT="
                        + json.dumps(
                            {
                                "name": "get_fin_fixture",
                                "table": "hq_fin",
                                "group": "financial",
                                "start": "20250101",
                                "end": "20260812",
                                "sample_code": None,
                            }
                        ),
                        "| INFO | 对应的接口已调用 1次，抓取条数 7000 清洗后 7000 最终入库 7000",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            supporting = report / "logs" / "000_baseline.log"
            supporting.write_text("supporting log\n", encoding="utf-8")

            document = aggregate.aggregate_report(report)

            self.assertEqual(document["completed_count"], 0)
            self.assertEqual(document["total_endpoints"], 0)
            self.assertEqual(
                document["source_counts"]["auxiliary_attempt_log_files"],
                1,
            )
            self.assertEqual(
                document["source_counts"]["unclassified_log_files"],
                1,
            )
            attempt = document["auxiliary_attempts"][0]
            self.assertEqual(attempt["endpoint"], "get_fin_fixture")
            self.assertEqual(attempt["status"], "INCOMPLETE")
            self.assertEqual(attempt["written_rows"], 7000)
            self.assertIn(
                "AUXILIARY_ATTEMPT_WITHOUT_RESULT",
                attempt["anomaly_codes"],
            )
            markdown = (report / aggregate.MARKDOWN_OUTPUT_NAME).read_text(
                encoding="utf-8"
            )
            self.assertIn("000_financial_aborted.log", markdown)


if __name__ == "__main__":
    unittest.main()
