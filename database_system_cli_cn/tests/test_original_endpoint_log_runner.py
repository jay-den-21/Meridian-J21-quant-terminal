from __future__ import annotations

from pathlib import Path
import unittest

from tools.verification import original_endpoint_log_runner as runner


class OriginalEndpointLogRunnerTest(unittest.TestCase):
    def test_redacts_common_secret_shapes(self) -> None:
        raw = (
            "mysql+pymysql://user:password@example/db "
            '"api_key": "abc123" Authorization: Bearer xyz987 '
            "https://host/path?token=query-secret"
        )

        redacted = runner._redact(raw)

        for secret in ("password", "abc123", "xyz987", "query-secret"):
            self.assertNotIn(secret, redacted)
        self.assertGreaterEqual(redacted.count("***"), 4)

    def test_child_environment_drops_credential_variables(self) -> None:
        environment = runner._child_environment(
            Path("/original"),
            {
                "PATH": "/bin",
                "LANG": "zh_CN.UTF-8",
                "TUSHARE_TOKEN": "secret-token",
                "DB_PASSWORD": "secret-password",
            },
        )

        self.assertEqual(environment["PATH"], "/bin")
        self.assertEqual(environment["PYTHONPATH"], "/original")
        self.assertNotIn("TUSHARE_TOKEN", environment)
        self.assertNotIn("DB_PASSWORD", environment)

    def test_resume_requires_warning_free_complete_result(self) -> None:
        complete = {
            "returncode": 0,
            "saw_error": False,
            "saw_warning": False,
            "final_database_snapshot": {"table_exists": True},
        }
        self.assertTrue(runner._prior_result_is_resumable(complete))

        for field, value in (
            ("returncode", 1),
            ("saw_error", True),
            ("saw_warning", True),
            ("final_database_snapshot", None),
        ):
            candidate = dict(complete)
            candidate[field] = value
            with self.subTest(field=field):
                self.assertFalse(runner._prior_result_is_resumable(candidate))


if __name__ == "__main__":
    unittest.main()
