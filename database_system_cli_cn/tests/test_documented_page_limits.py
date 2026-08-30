from __future__ import annotations

import ast
from pathlib import Path
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GETTER_ROOT = PACKAGE_ROOT / "get_ph_data_from_ts"


_DOCUMENTED_LIMIT_ROWS = """
alt/Get_alt_eco_cal.py|100
alt/Get_alt_stk_factor.py|10000
cb/Get_cb_1min.py|8000
cb/Get_cb_5min.py|8000
cb/Get_cb_basic.py|2000
cb/Get_cb_daily.py|2000
fund/Get_fund_1min.py|8000
fund/Get_fund_adj.py|2000
fund/Get_fund_basic.py|15000
fund/Get_fund_daily.py|5000
fund/Get_fund_share.py|2000
fut/Get_fut_1min.py|8000
fut/Get_fut_5min.py|8000
fut/Get_fut_basic.py|10000
fut/Get_fut_daily.py|2000
fut/Get_fut_holding.py|2000
fut/Get_fut_mapping.py|2000
fut/Get_fut_wsr.py|1000
fx/Get_fx_daily.py|1000
hk/Get_hk_ccass_hold_detail.py|6000
hk/Get_hk_daily.py|5000
hk/Get_hk_daily_adj.py|6000
hk/Get_hk_tradeCal.py|2000
idx/Get_idx_1min.py|8000
idx/Get_idx_basic.py|8000
idx/Get_idx_daily.py|8000
idx/Get_idx_daily_basic.py|3000
idx/Get_idx_sw_daily.py|4000
idx/Get_idx_sw_member.py|2000
idx/Get_idx_sw_member_all.py|2000
macro/Get_macro_cn_cpi.py|5000
macro/Get_macro_cn_gdp.py|10000
opt/Get_opt_1min.py|8000
opt/Get_opt_daily.py|15000
ref/Get_ref_topinst.py|10000
ref/Get_ref_toplist.py|10000
stk/Get_stk_15min.py|8000
stk/Get_stk_1min.py|8000
stk/Get_stk_30min.py|8000
stk/Get_stk_5min.py|8000
stk/Get_stk_60min.py|8000
stk/Get_stk_bak_daily.py|7000
stk/Get_stk_basic.py|6000
stk/Get_stk_basic_all.py|6000
stk/Get_stk_cyq_chips.py|6000
stk/Get_stk_cyq_perf.py|6000
stk/Get_stk_daily.py|6000
stk/Get_stk_daily_basic.py|6000
stk/Get_stk_factor_pro.py|10000
stk/Get_stk_moneyflow.py|6000
stk_limit/Get_stk_kpl_concept.py|5000
stk_limit/Get_stk_kpl_concept_cons.py|3000
stk_limit/Get_stk_kpl_list.py|8000
stk_limit/Get_stk_limit.py|5800
stk_limit/Get_stk_limit_cpt_list.py|2000
stk_limit/Get_stk_limit_list.py|1000
stk_limit/Get_stk_limit_list_d.py|2500
stk_limit/Get_stk_limit_step.py|2000
stk_limit/Get_stk_tdx_daily.py|3000
stk_limit/Get_stk_tdx_index.py|1000
stk_limit/Get_stk_tdx_member.py|3000
ths_dc/Get_ths_daily.py|3000
ths_dc/Get_ths_daily_all.py|3000
ths_dc/Get_ths_hot.py|2000
ths_dc/Get_ths_index.py|5000
ths_dc/Get_ths_limit_list.py|4000
ths_dc/Get_ths_moneyflow.py|6000
us/Get_us_basic.py|6000
us/Get_us_daily.py|6000
us/Get_us_daily_adj.py|8000
us/Get_us_tradecal.py|6000
"""

DOCUMENTED_LIMITS = {
    path: int(value)
    for path, value in (
        line.split("|", 1)
        for line in _DOCUMENTED_LIMIT_ROWS.splitlines()
        if line
    )
}

# These physical getters have no numeric page maximum in their current
# official documentation, return the complete small result in one request,
# or are deliberately unsupported.  Their existing behavior is preserved.
NO_DOCUMENTED_NUMERIC_MAX = {
    "Get_tradeCal.py",
    "alt/Get_alt_cctv_news.py",
    "cb/Get_cb_daily_basic.py",
    "fin/Get_fin_balancesheet.py",
    "fin/Get_fin_balancesheet_vip.py",
    "fin/Get_fin_cashflow.py",
    "fin/Get_fin_cashflow_vip.py",
    "fin/Get_fin_income.py",
    "fin/Get_fin_income_all_vip.py",
    "fin/Get_fin_income_daily.py",
    "fund/Get_fund_portfolio.py",
    "fx/Get_fx_obasic.py",
    "hk/Get_hk_basic.py",
    "idx/Get_idx_sw_classify.py",
    "opt/Get_opt_basic.py",
    "stk/Get_stk_adj_factor.py",
    "ths_dc/Get_ths_member.py",
    "ths_dc/Get_ths_member_all.py",
}


def _configured_limit(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if ast.unparse(target) != "self.params.one_time_rows_limit":
            continue
        if isinstance(node.value, ast.Constant) and isinstance(
            node.value.value,
            int,
        ):
            values.append(node.value.value)
    if len(values) != 1:
        raise AssertionError(f"{path} has {len(values)} active page limits")
    return values[0]


class DocumentedPageLimitTests(unittest.TestCase):
    def test_every_physical_getter_is_classified(self):
        actual = {
            str(path.relative_to(GETTER_ROOT))
            for path in GETTER_ROOT.rglob("*.py")
        }
        self.assertEqual(
            actual,
            set(DOCUMENTED_LIMITS) | NO_DOCUMENTED_NUMERIC_MAX,
        )

    def test_every_documented_numeric_limit_is_configured_exactly(self):
        for relative_path, expected in DOCUMENTED_LIMITS.items():
            with self.subTest(getter=relative_path):
                self.assertEqual(
                    _configured_limit(GETTER_ROOT / relative_path),
                    expected,
                )

    def test_realtime_getters_are_not_row_paginated(self):
        realtime = {
            path.name
            for path in (PACKAGE_ROOT / "get_rt_data_from_ts").glob("*.py")
        }
        self.assertEqual(
            realtime,
            {
                "Get_rt_stk_quote_tick__east.py",
                "Get_rt_stk_quote_tick__sina.py",
                "Get_rt_stk_tick__east.py",
            },
        )
        for name in realtime:
            source = (
                PACKAGE_ROOT / "get_rt_data_from_ts" / name
            ).read_text(encoding="utf-8")
            self.assertNotIn("one_time_rows_limit", source)


if __name__ == "__main__":
    unittest.main()
