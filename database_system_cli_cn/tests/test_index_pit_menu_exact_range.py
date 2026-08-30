from __future__ import annotations

from datetime import date
import unittest

from fdp_cn.menu import TEXT, _index_pit_request


class IndexPitMenuExactRangeTests(unittest.TestCase):
    def test_style_defaults_to_recent_six_complete_months(self):
        answers = iter(("style", "", "", "", ""))

        request = _index_pit_request(lambda prompt: next(answers), TEXT["zh"])

        self.assertEqual(request.phase, "style")
        self.assertEqual(request.months, 6)
        self.assertIsNone(request.date_from)
        self.assertIsNone(request.date_to)

    def test_general_accepts_exact_complete_month_date_range(self):
        answers = iter(
            ("general", "250", "2", "2021-08-01", "2026-01-31", "000300.SH")
        )

        request = _index_pit_request(lambda prompt: next(answers), TEXT["zh"])

        self.assertEqual(request.phase, "general")
        self.assertEqual(request.date_from, date(2021, 8, 1))
        self.assertEqual(request.date_to, date(2026, 1, 31))
        self.assertIsNone(request.months)
        self.assertEqual(request.codes, ("000300.SH",))
        self.assertEqual(request.max_api_calls, 250)

    def test_exact_range_requires_both_dates(self):
        answers = iter(("style", "", "2", "2021-08-01", ""))

        with self.assertRaisesRegex(ValueError, "起止日期必须同时填写"):
            _index_pit_request(lambda prompt: next(answers), TEXT["zh"])

    def test_exact_range_rejects_empty_dates(self):
        answers = iter(("style", "", "exact", "", ""))

        with self.assertRaisesRegex(ValueError, "精确范围必须同时填写"):
            _index_pit_request(lambda prompt: next(answers), TEXT["zh"])

    def test_all_keeps_recent_month_mode_and_does_not_ask_range_mode(self):
        prompts: list[str] = []
        answers = iter(("all", "", "", "", "12", ""))

        def answer(prompt: str) -> str:
            prompts.append(prompt)
            return next(answers)

        request = _index_pit_request(answer, TEXT["en"])

        self.assertEqual(request.phase, "all")
        self.assertEqual(request.months, 12)
        self.assertNotIn(TEXT["en"]["weight_range_mode"], prompts)
        self.assertIn("all supports recent N months only", prompts[4])


if __name__ == "__main__":
    unittest.main()
