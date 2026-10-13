"""Public-clone planning must not load private runtime configuration."""

import unittest
from unittest.mock import patch

from fdp_cn.tushare.index_pit import IndexPitJob, IndexPitRequest


class PublicBootstrapTests(unittest.TestCase):
    def test_basic_dry_run_never_constructs_runtime(self):
        with patch(
            "fdp_cn.tushare.index_pit.TushareJobRuntime.from_env",
            side_effect=AssertionError("private runtime requested"),
        ):
            result = IndexPitJob().run(IndexPitRequest(phase="basic"))
        self.assertEqual(result.status, "dry_run")

    def test_execute_still_requires_explicit_runtime_configuration(self):
        with patch(
            "fdp_cn.tushare.index_pit.TushareJobRuntime.from_env",
            side_effect=ValueError("private configuration is missing"),
        ):
            with self.assertRaisesRegex(ValueError, "private configuration"):
                IndexPitJob().run(IndexPitRequest(phase="basic", execute=True))
