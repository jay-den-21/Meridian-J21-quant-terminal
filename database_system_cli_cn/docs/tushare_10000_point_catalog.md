# Tushare 10,000-Point CLI/Menu Inventory

Updated: 2026-08-30

## Meaning Of This Inventory

The CN catalog contains 93 endpoint variants backed by 92 physical getter
files and 88 target tables. The reviewed partition is:

| Group | Variants | Default `all` |
| --- | ---: | --- |
| standard-point endpoints available at the 10,000-point tier | 71 | yes |
| separately entitled endpoints | 17 | no |
| retired or unsupported endpoints | 2 | no |
| external realtime endpoints | 3 | no |

The groups are mutually exclusive and total 93.

`access.points_tier=10000` means J21 has classified the endpoint as available
to the reviewed 10,000-point account tier. It deliberately does not claim that
10,000 is the provider's exact minimum for every endpoint. Getter headers have
historical conflicts, so J21 does not invent a more precise minimum.

Provider `page_limit` is rows per request. It is never used as an account
points value. For example, an endpoint may request 15,000 rows per page and
still belong to the 10,000-point account inventory.

## The 71 Default Endpoints

- `calendar`: `trade_cal`
- `alt`: `alt.alt_eco_cal`, `alt.alt_stk_factor`
- `cb`: `cb.cb_basic`, `cb.cb_daily`
- `fin`: `fin.fin_balancesheet`, `fin.fin_balancesheet_vip`,
  `fin.fin_cashflow`, `fin.fin_cashflow_vip`, `fin.fin_income`,
  `fin.fin_income_all_vip`, `fin.fin_income_daily`
- `fund`: `fund.fund_adj`, `fund.fund_basic`, `fund.fund_daily`,
  `fund.fund_portfolio`, `fund.fund_share`
- `fut`: `fut.fut_basic`, `fut.fut_daily`, `fut.fut_holding`,
  `fut.fut_mapping`, `fut.fut_wsr`
- `fx`: `fx.fx_daily`, `fx.fx_obasic`
- `hk`: `hk.hk_basic`, `hk.hk_basic_d`, `hk.hk_ccass_hold_detail`,
  `hk.hk_trade_cal`
- `idx`: `idx.idx_basic`, `idx.idx_daily`, `idx.idx_daily_basic`,
  `index_classify`, `sw_daily`, `idx.idx_sw_member`,
  `idx.idx_sw_member_all`
- `macro`: `macro.macro_cn_cpi`, `macro.macro_cn_gdp`
- `opt`: `opt.opt_basic`, `opt.opt_daily`
- `ref`: `ref.ref_topinst`, `ref.ref_toplist`
- `stk`: `stk.stk_adj_factor`, `stk.stk_bak_daily`, `stock_basic`,
  `stock_basic_all`, `cyq_chips`, `stk.stk_cyq_perf`, `daily`,
  `stk.stk_daily_basic`, `stk.stk_factor_pro`, `stk.stk_moneyflow`
- `stk_limit`: `stk_limit.stk_kpl_concept`,
  `stk_limit.stk_kpl_concept_cons`, `stk_limit.stk_kpl_list`,
  `stk_limit.stk_limit`, `stk_limit.stk_limit_cpt_list`,
  `stk_limit.stk_limit_list_d`, `stk_limit.stk_limit_step`,
  `stk_limit.stk_tdx_daily`, `stk_limit.stk_tdx_index`,
  `stk_limit.stk_tdx_member`
- `ths_dc`: `ths_dc.ths_daily`, `ths_dc.ths_daily_all`, `ths_dc.ths_hot`,
  `ths_dc.ths_index`, `ths_dc.ths_limit_list`, `ths_dc.ths_member`,
  `ths_dc.ths_member_all`, `ths_dc.ths_moneyflow`
- `us`: `us.us_basic`, `us.us_tradecal`

Every item is visible in CLI and Menu, individually plannable, and resolves to
an existing getter file/class. A globally unique short getter name such as
`get_fin_cashflow_vip` is also accepted as an endpoint alias.

## The 17 Separately Entitled Endpoints

- `alt`: `alt.alt_cctv_news`
- `cb`: `cb.cb_1min`, `cb.cb_5min`
- `fund`: `fund.fund_1min`
- `fut`: `fut.fut_1min`, `fut.fut_5min`
- `hk`: `hk.hk_daily`, `hk.hk_daily_adj`
- `idx`: `idx.idx_1min`
- `opt`: `opt.opt_1min`
- `stk`: `stk.stk_1min`, `stk.stk_5min`, `stk.stk_15min`,
  `stk.stk_30min`, `stk.stk_60min`
- `us`: `us.us_daily`, `us.us_daily_adj`

These remain visible and can be selected explicitly after the account has the
corresponding entitlement. They never enter the default 10,000-point `all` or
ordinary category batch.

The current official permission table separately lists historical minute
data, US daily data and news/news-broadcast data. This supersedes old getter
comments that described CCTV news as a 5,000-point endpoint.

## Retired/Unsupported And Realtime

Retired or unsupported:

- `cb.cb_daily_basic`: no supported current Tushare mapping.
- `stk_limit.stk_limit_list`: retired; use `stk_limit.stk_limit_list_d`.

External realtime:

- `realtime.rt_stk_quote_tick_east`
- `realtime.rt_stk_quote_tick_sina`
- `realtime.rt_stk_tick_east`

They remain listed for honest inventory coverage but are not provider-history
batch members.

## CLI And Menu Behavior

```bash
# Inspect all 93 variants and their access/points/page-limit fields.
poetry run j21 ingest list

# Plan the exact 71-item inventory; dry-run is the default.
poetry run j21 ingest all --from 2026-08-01 --to 2026-08-30

# Explicitly run one endpoint by stable key or unique getter alias.
poetry run j21 ingest tushare \
  --endpoint get_fin_cashflow_vip \
  --from 2025-01-01 --to 2025-12-31

poetry run j21 menu
```

CLI and Menu call the same `IngestService`. Without an explicit code list,
`cyq_chips` uses the preserved compatibility getter so it can resolve its
stock universe from `hq_stk_basic`. With explicit codes it uses the reviewed
direct Job. Candidate batch codes are applied only to code-scoped endpoints;
they are not forwarded to `trade_cal` or other incompatible endpoints. Pure
code-list getters and code-plus-date-range getters are distinct scopes, so the
Menu asks only for the inputs the selected endpoint accepts.

An endpoint-local parameter/capability failure, compatibility-process timeout,
nonzero exit, spawn failure or adapter exception is recorded and later
endpoints continue. Authentication and storage-integrity failures stop the
batch.

## Verification Evidence

Offline regressions prove:

- all 92 `Get_*.py` files are represented by the 93 variants;
- every `legacy_id`, class and target table exists by AST inspection without
  importing side-effectful getters;
- the exact 71 keys equal `IngestService.plan_all()` in catalog order;
- every one of the 71 is individually plannable;
- CLI and Menu share the same plan and access metadata;
- page limits cannot change point eligibility;
- CCTV news and both US daily variants are absent from default `all`.

The final 2026-08-30 quality gate passed 107 CN tests, `compileall`, and
`poetry check --lock`. The actual `poetry run j21 ingest all` dry-run produced
71 unique items, and the actual Menu standard-point path displayed the same 71
items before cancellation without provider or database writes.

These checks prove the execution routing and catalog contract. They do not
claim that a broad provider-consuming backfill was rerun on 2026-08-30.

## Provider Sources

- [Tushare points and independent-entitlement table](https://tushare.pro/document/1?doc_id=290)
- [Tushare API point requirements](https://tushare.pro/document/1?doc_id=108)
- [Tushare minute-data permission guide](https://tushare.pro/document/1?doc_id=234)
