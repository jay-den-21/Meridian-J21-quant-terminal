#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！
"""
__author__ = "Jayden21 <jayden0721@163.com>"

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from basis import *


from basis import params
from get_ph_data_from_ts.alt.Get_alt_stk_factor import get_alt_stk_factor
from get_ph_data_from_ts.cb.Get_cb_5min import get_cb_5min
from get_ph_data_from_ts.fin.Get_fin_cashflow_vip import get_fin_cashflow_vip_run
from get_ph_data_from_ts.fin.Get_fin_income_all_vip import get_fin_income_all_vip_run
# from get_ph_data_from_ts.cb.Get_cb_5min import get_cb_5min
from get_ph_data_from_ts.cb.Get_cb_daily_basic import get_cb_daily_basic
from get_ph_data_from_ts.fin.Get_fin_balancesheet_vip import get_fin_balancesheet_vip_run
from get_ph_data_from_ts.fin.Get_fin_income_daily import get_fin_income_daily
from get_ph_data_from_ts.fund.Get_fund_1min import get_fund_1min
from get_ph_data_from_ts.fund.Get_fund_adj import get_fund_adj_factor
from get_ph_data_from_ts.fund.Get_fund_portfolio import get_fund_portfolio
from get_ph_data_from_ts.fut.Get_fut_1min import get_fut_1min
from get_ph_data_from_ts.fut.Get_fut_holding import get_fut_holding
from get_ph_data_from_ts.fut.Get_fut_wsr import get_fut_wsr
from get_ph_data_from_ts.fx.Get_fx_daily import get_fx_daily
from get_ph_data_from_ts.fx.Get_fx_obasic import get_fx_obasic
from get_ph_data_from_ts.hk.Get_hk_ccass_hold_detail import get_hk_ccass_hold_detail_run
from get_ph_data_from_ts.idx.Get_idx_1min import get_idx_1min
from get_ph_data_from_ts.idx.Get_idx_daily_basic import get_idx_daily_basic
from get_ph_data_from_ts.idx.Get_idx_sw_classify import get_idx_sw_classify
from get_ph_data_from_ts.idx.Get_idx_sw_member import get_idx_sw_member
from get_ph_data_from_ts.idx.Get_idx_sw_member_all import get_idx_sw_member_all
from get_ph_data_from_ts.macro.Get_macro_cn_cpi import get_macro_cn_cpi
from get_ph_data_from_ts.opt.Get_opt_1min import get_opt_1min
from get_ph_data_from_ts.opt.Get_opt_basic import get_opt_basic
from get_ph_data_from_ts.opt.Get_opt_daily import get_opt_daily
from get_ph_data_from_ts.stk.Get_stk_1min import get_stk_1min
from get_ph_data_from_ts.stk.Get_stk_bak_daily import get_stk_bak_daily
from get_ph_data_from_ts.stk.Get_stk_basic_all import get_stk_basic_all
from get_ph_data_from_ts.stk.Get_stk_cyq_chips import get_stk_cyq_chips
from get_ph_data_from_ts.stk.Get_stk_cyq_perf import get_stk_cyq_perf
from get_ph_data_from_ts.stk_limit.Get_stk_kpl_concept import get_stk_kpl_concept
from get_ph_data_from_ts.stk_limit.Get_stk_kpl_concept_cons import get_stk_kpl_concept_cons
from get_ph_data_from_ts.stk_limit.Get_stk_kpl_list import get_stk_kpl_list
from get_ph_data_from_ts.stk_limit.Get_stk_limit_cpt_list import get_stk_limit_cpt_list
from get_ph_data_from_ts.ths_dc.Get_ths_member import get_ths_member
from get_ph_data_from_ts.ths_dc.Get_ths_member_all import get_ths_member_all
from get_ph_data_from_ts.us.Get_us_basic import get_us_basic
from get_ph_data_from_ts.us.Get_us_daily import get_us_daily

from get_ph_data_from_ts.cb.Get_cb_basic import get_cb_basic
from get_ph_data_from_ts.fund.Get_fund_basic import get_fund_basic
from get_ph_data_from_ts.fut.Get_fut_basic import get_fut_basic
from get_ph_data_from_ts.hk.Get_hk_basic import get_hk_basic
from get_ph_data_from_ts.hk.Get_hk_tradeCal import get_hk_tradeCal
from get_ph_data_from_ts.idx.Get_idx_basic import get_idx_basic
from get_ph_data_from_ts.stk.Get_stk_basic import get_stk_basic
from get_ph_data_from_ts.ths_dc.Get_ths_index import get_ths_index
from get_ph_data_from_ts.Get_tradeCal import get_tradeCal

from get_ph_data_from_ts.stk.Get_stk_daily import get_stk_daily
from get_ph_data_from_ts.idx.Get_idx_daily import get_idx_daily
from get_ph_data_from_ts.stk.Get_stk_adj_factor import get_stk_adj_factor
from get_ph_data_from_ts.alt.Get_alt_cctv_news import get_alt_cctv_news
from get_ph_data_from_ts.alt.Get_alt_eco_cal import get_alt_eco_cal
from get_ph_data_from_ts.cb.Get_cb_1min import get_cb_1min
from get_ph_data_from_ts.cb.Get_cb_daily import get_cb_daily
from get_ph_data_from_ts.fund.Get_fund_daily import get_fund_daily
from get_ph_data_from_ts.fund.Get_fund_share import get_fund_share
from get_ph_data_from_ts.fut.Get_fut_daily import get_fut_daily
from get_ph_data_from_ts.fut.Get_fut_mapping import get_fut_mapping
from get_ph_data_from_ts.hk.Get_hk_daily import get_hk_daily
from get_ph_data_from_ts.macro.Get_macro_cn_gdp import get_macro_cn_gdp
from get_ph_data_from_ts.ref.Get_ref_topinst import get_ref_topinst
from get_ph_data_from_ts.ref.Get_ref_toplist import get_ref_toplist
from get_ph_data_from_ts.stk.Get_stk_daily_basic import get_stk_daily_basic
from get_ph_data_from_ts.stk_limit.Get_stk_limit_list import get_stk_limit_list
from get_ph_data_from_ts.stk_limit.Get_stk_limit_list_d import get_stk_limit_list_d
from get_ph_data_from_ts.stk.Get_stk_moneyflow import get_stk_moneyflow
from get_ph_data_from_ts.ths_dc.Get_ths_daily import get_ths_daily
from get_ph_data_from_ts.us.Get_us_tradecal import get_us_tradeCal


# 权限标记（2026-08-12，按 10000 积分账号实测与接口权限分类）：
# 1. 【单独开通】表示达到 10000 积分也不会自动获得，必须另行开通对应权限。
# 2. 带上述标记的调用默认保持注释；确认官方权限已经开通后再手工取消注释。
# 3. 当前项目没有“必须高于 10000 普通积分”才可用的接口；15000 积分只会取消
#    cyq_chips/cyq_perf 的特色数据每日总量限制，不改变它们在 10000 积分档可调用的事实。
#
# 达到 10000 积分仍需单独开通的 17 个 catalog 接口（2026-08-30 官方权限表复核）：
# alt.alt_cctv_news；cb.cb_1min、cb.cb_5min；fund.fund_1min；
# fut.fut_1min、fut.fut_5min；hk.hk_daily、hk.hk_daily_adj；idx.idx_1min；
# opt.opt_1min；stk.stk_1min、stk.stk_5min、stk.stk_15min、stk.stk_30min、
# stk.stk_60min；us.us_daily、us.us_daily_adj。


def _run_interface(interface_name, action, failures):
    """运行一个接口；普通异常记录完整堆栈后继续下一个接口。"""
    try:
        action()
    except Exception:
        failures.append(interface_name)
        logging.exception(
            f"串行抓取：接口 {interface_name} 执行失败，"
            "已记录完整 traceback，继续执行下一个接口。"
        )
        return False
    return True


def _finish_interface_group(group_name, failures):
    """记录一组串行任务的最终结果，并返回失败接口名。"""
    if failures:
        logging.error(
            f"{group_name}执行完毕：{len(failures)} 个接口失败，"
            f"其他接口已继续执行。失败接口：{', '.join(failures)}"
        )
    else:
        logging.success(f"{group_name}执行完毕：所有已启用接口均执行成功。")
    return failures


# 加载维度表（表全加的接口）
def get_data_by_reload_all():
    """
    需要抓取的接口打开，不需要抓取的接口注释掉即可，盘后今日数据和历史数据抓取均使用该列表
    :return:
    """
    failures = []
    # 加载日期表，加载一次后可注释掉，不用每次都加
    _run_interface("get_tradeCal", lambda: get_tradeCal().run(), failures)  # 加载a股工作日表
    _run_interface("get_hk_tradeCal", lambda: get_hk_tradeCal().run(), failures)  # 加载港股工作日表
    _run_interface("get_us_tradeCal", lambda: get_us_tradeCal().run(), failures)  # 美股交易日历
    # 各品种基础信息------------------------------------------------
    _run_interface("get_stk_basic", lambda: get_stk_basic().run(), failures)  # 证券信息
    _run_interface("get_cb_basic", lambda: get_cb_basic().run(), failures)  # 可转债基本信息
    _run_interface("get_fund_basic", lambda: get_fund_basic().run(), failures)  # 公募基金列表
    _run_interface("get_fut_basic", lambda: get_fut_basic().run(), failures)  # 期货合约信息表
    _run_interface("get_hk_basic", lambda: get_hk_basic().run(), failures)  # 港股列表
    _run_interface("get_idx_basic", lambda: get_idx_basic().run(), failures)  # 指数基本信息
    _run_interface("get_ths_index", lambda: get_ths_index().run(), failures)  # 顺序不能乱
    _run_interface("get_opt_basic", lambda: get_opt_basic().run(), failures)  # 期权合约信息
    _run_interface("get_us_basic", lambda: get_us_basic().run(), failures)  # 美股基本信息
    return _finish_interface_group("全量维度表组", failures)


# 加载按日抓取的接口
def get_data_by_date(params):
    failures = []
    # 转债--------------------------------------------------------
    _run_interface("get_cb_daily", lambda: get_cb_daily(params).run(), failures)  # 可转债日线行情
    # _run_interface("get_cb_daily_basic", lambda: get_cb_daily_basic(params).run(), failures)  # 转债每日指标

    # 股票--------------------------------------------------------
    _run_interface("get_stk_adj_factor", lambda: get_stk_adj_factor(params).run(), failures)  # 股票复权因子
    # _run_interface("get_stk_bak_daily", lambda: get_stk_bak_daily(params).run(), failures)  # 备用行情
    _run_interface("get_stk_basic_all", lambda: get_stk_basic_all().run(), failures)  # 股票基本信息(全量含退市）
    # _run_interface("get_stk_cyq_chips", lambda: get_stk_cyq_chips(params).run(), failures)  # 每日筹码分布
    # _run_interface("get_stk_cyq_perf", lambda: get_stk_cyq_perf(params).run(), failures)  # 每日筹码及胜率
    _run_interface("get_stk_daily", lambda: get_stk_daily(params).run(), failures)  # 日线行情
    _run_interface("get_stk_daily_basic", lambda: get_stk_daily_basic(params).run(), failures)  # 行情扩展

    _run_interface("get_stk_moneyflow", lambda: get_stk_moneyflow(params).run(), failures)  # 股票个股资金流向

    # 打板专题
    # _run_interface("get_stk_kpl_concept", lambda: get_stk_kpl_concept(params).run(), failures)  # 开盘啦题材库
    # _run_interface("get_stk_kpl_concept_cons", lambda: get_stk_kpl_concept_cons(params).run(), failures)  # 开盘啦题材成分
    # _run_interface("get_stk_kpl_list", lambda: get_stk_kpl_list(params).run(), failures)  # 开盘啦榜单数据
    # _run_interface("get_stk_limit_cpt_list", lambda: get_stk_limit_cpt_list(params).run(), failures)  # 每日涨跌停价格
    # _run_interface("get_stk_limit_list", lambda: get_stk_limit_list(params).run(), failures)  # 2024年以前涨跌停
    # _run_interface("get_stk_limit_list_d", lambda: get_stk_limit_list_d(params).run(), failures)  # 新涨跌停列表

    # 基金--------------------------------------------------------
    _run_interface("get_fund_daily", lambda: get_fund_daily(params).run(), failures)  # 场内基金日线行情
    # _run_interface("get_fund_adj_factor", lambda: get_fund_adj_factor(params).run(), failures)  # 基金复权因子
    # _run_interface("get_fund_portfolio", lambda: get_fund_portfolio(params).run(), failures)  # 公募基金持仓
    _run_interface("get_fund_share", lambda: get_fund_share(params).run(), failures)  # 基金规模数据

    # 期货--------------------------------------------------------
    # _run_interface("get_fut_daily", lambda: get_fut_daily(params).run(), failures)  # 期货日线行情
    # _run_interface("get_fut_holding", lambda: get_fut_holding(params).run(), failures)  # 期货成交持仓排名
    # _run_interface("get_fut_mapping", lambda: get_fut_mapping().run(), failures)  # 期货主力与连续合约
    # _run_interface("get_fut_wsr", lambda: get_fut_wsr(params).run(), failures)  # 期货仓单日报

    # 期权--------------------------------------------------------
    # _run_interface("get_opt_daily", lambda: get_opt_daily(params).run(), failures)  # 期权日线行情

    # 港股--------------------------------------------------------
    # _run_interface("get_hk_daily", lambda: get_hk_daily(params).run(), failures)  # 【单独开通：港股日线权限】
    # _run_interface("get_hk_ccass_hold_detail_run", lambda: get_hk_ccass_hold_detail_run(params), failures)  # CCASS持股明细

    # 美股--------------------------------------------------------
    # _run_interface("get_us_daily", lambda: get_us_daily(params).run(), failures)  # 【单独开通：美股日线正式权限】

    # 外汇--------------------------------------------------------
    # _run_interface("get_fx_daily", lambda: get_fx_daily(params).run(), failures)  # 外汇日线行情
    # _run_interface("get_fx_obasic", lambda: get_fx_obasic().run(), failures)  # 外汇基础信息

    # 财务数据--------------------------------------------------------
    _run_interface("get_fin_balancesheet_vip_run", lambda: get_fin_balancesheet_vip_run(params), failures)  # 资产负债表
    _run_interface("get_fin_cashflow_vip_run", lambda: get_fin_cashflow_vip_run(params), failures)  # 现金流量表

    _run_interface("get_fin_income_daily", lambda: get_fin_income_daily(params).run(), failures)  # 利润表
    # _run_interface("get_fin_income_all_vip_run", lambda: get_fin_income_all_vip_run(params), failures)  # 利润表

    # 另类数据--------------------------------------------------------
    # _run_interface("get_alt_cctv_news", lambda: get_alt_cctv_news(params).run(), failures)  # 【单独开通：新闻资讯权限】
    _run_interface("get_alt_eco_cal", lambda: get_alt_eco_cal(params).run(), failures)  # 财经日历
    # _run_interface("get_alt_stk_factor", lambda: get_alt_stk_factor(params).run(), failures)  # 股票技术因子

    # 指数--------------------------------------------------------
    _run_interface("get_idx_sw_classify", lambda: get_idx_sw_classify(params).run(), failures)  # 申万行业分类
    _run_interface("get_idx_daily", lambda: get_idx_daily(params).run(), failures)  # 指数日线行情
    _run_interface("get_idx_daily_basic", lambda: get_idx_daily_basic(params).run(), failures)  # 股票每日指标
    # _run_interface("get_idx_sw_member", lambda: get_idx_sw_member().run(), failures)  # 申万行业成分构成
    _run_interface("get_idx_sw_member_all", lambda: get_idx_sw_member_all().run(), failures)  # 申万完整成分映射


    # 同花顺--------------------------------------------------------
    _run_interface("get_ths_daily", lambda: get_ths_daily(params).run(), failures)  # 同花顺板块指数行情
    # _run_interface("get_ths_index", lambda: get_ths_index().run(), failures)  # 同花顺概念和行业指数
    # _run_interface("get_ths_member", lambda: get_ths_member(params).run(), failures)  # 同花顺概念板块成分
    # _run_interface("get_ths_member_all", lambda: get_ths_member_all(params).run(), failures)  # 同花顺概念成分

    # 市场参考--------------------------------------------------------
    # _run_interface("get_ref_topinst", lambda: get_ref_topinst(params).run(), failures)  # 龙虎榜机构明细
    # _run_interface("get_ref_toplist", lambda: get_ref_toplist(params).run(), failures)  # 龙虎榜每日明细

    # 宏观--------------------------------------------------------
    _run_interface("get_macro_cn_cpi", lambda: get_macro_cn_cpi().run(), failures)  # 居民消费价格指数
    _run_interface("get_macro_cn_gdp", lambda: get_macro_cn_gdp().run(), failures)  # 宏观GDP数据

    # 分钟数据（按需打开）------------------------------------------------------
    # 以下均为【单独开通：分钟行情权限】，10000积分不等于自动拥有；默认保持注释。
    # _run_interface("get_stk_1min", lambda: get_stk_1min(params).run(), failures)  # 【单独开通】股票 1min
    # _run_interface("get_cb_1min", lambda: get_cb_1min(params).run(), failures)  # 【单独开通】转债 1min
    # _run_interface("get_cb_5min", lambda: get_cb_5min(params).run(), failures)  # 【单独开通】转债 5min
    # _run_interface("get_fut_1min", lambda: get_fut_1min(params).run(), failures)  # 【单独开通】期货 1min
    # _run_interface("get_idx_1min", lambda: get_idx_1min(params).run(), failures)  # 【单独开通】指数 1min
    # _run_interface("get_fund_1min", lambda: get_fund_1min(params).run(), failures)  # 【单独开通】基金 1min
    # _run_interface("get_opt_1min", lambda: get_opt_1min(params).run(), failures)  # 【单独开通】期权 1min
    return _finish_interface_group("按日抓取组", failures)

