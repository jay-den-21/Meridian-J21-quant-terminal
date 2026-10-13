"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

利润表批量数据
接口：income_vip，可以通过数据工具调试和查看数据。
描述：获取上市公司利润表批量数据，可按证券代码和日期范围提取。
权限：用户需要至少5000积分才可以调取，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
ts_code	str	Y	TS股票代码,e.g. 600001.SH/000001.SZ
ann_date	str	N	公告日期
start_date	str	N	报告期开始日期
end_date	str	N	报告期结束日期
period	str	N	报告期(每个季度最后一天的日期,比如20171231表示年报)
输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS代码
ann_date	str	Y	公告日期
end_date	str	Y	报告期
eps	float	Y	基本每股收益
dt_eps	float	Y	稀释每股收益
total_revenue_ps	float	Y	每股营业总收入
revenue_ps	float	Y	每股营业收入
capital_rese_ps	float	Y	每股资本公积
surplus_rese_ps	float	Y	每股盈余公积
undist_profit_ps	float	Y	每股未分配利润
extra_item	float	Y	非经常性损益
profit_dedt	float	Y	扣除非经常性损益后的净利润（扣非净利润）
gross_margin	float	Y	毛利
current_ratio	float	Y	流动比率
quick_ratio	float	Y	速动比率
cash_ratio	float	Y	保守速动比率
invturn_days	float	N	存货周转天数
arturn_days	float	N	应收账款周转天数
inv_turn	float	N	存货周转率
ar_turn	float	Y	应收账款周转率
ca_turn	float	Y	流动资产周转率
fa_turn	float	Y	固定资产周转率
assets_turn	float	Y	总资产周转率
op_income	float	Y	经营活动净收益
valuechange_income	float	N	价值变动净收益
interst_income	float	N	利息费用
daa	float	N	折旧与摊销
ebit	float	Y	息税前利润
ebitda	float	Y	息税折旧摊销前利润
fcff	float	Y	企业自由现金流量
fcfe	float	Y	股权自由现金流量
current_exint	float	Y	无息流动负债
noncurrent_exint	float	Y	无息非流动负债
interestdebt	float	Y	带息债务
netdebt	float	Y	净债务
tangible_asset	float	Y	有形资产
working_capital	float	Y	营运资金
networking_capital	float	Y	营运流动资本
invest_capital	float	Y	全部投入资本
retained_earnings	float	Y	留存收益
diluted2_eps	float	Y	期末摊薄每股收益
bps	float	Y	每股净资产
ocfps	float	Y	每股经营活动产生的现金流量净额
retainedps	float	Y	每股留存收益
cfps	float	Y	每股现金流量净额
ebit_ps	float	Y	每股息税前利润
fcff_ps	float	Y	每股企业自由现金流量
fcfe_ps	float	Y	每股股东自由现金流量
netprofit_margin	float	Y	销售净利率
grossprofit_margin	float	Y	销售毛利率
cogs_of_sales	float	Y	销售成本率
expense_of_sales	float	Y	销售期间费用率
profit_to_gr	float	Y	净利润/营业总收入
saleexp_to_gr	float	Y	销售费用/营业总收入
adminexp_of_gr	float	Y	管理费用/营业总收入
finaexp_of_gr	float	Y	财务费用/营业总收入
impai_ttm	float	Y	资产减值损失/营业总收入
gc_of_gr	float	Y	营业总成本/营业总收入
op_of_gr	float	Y	营业利润/营业总收入
ebit_of_gr	float	Y	息税前利润/营业总收入
roe	float	Y	净资产收益率
roe_waa	float	Y	加权平均净资产收益率
roe_dt	float	Y	净资产收益率(扣除非经常损益)
roa	float	Y	总资产报酬率
npta	float	Y	总资产净利润
roic	float	Y	投入资本回报率
roe_yearly	float	Y	年化净资产收益率
roa2_yearly	float	Y	年化总资产报酬率
roe_avg	float	N	平均净资产收益率(增发条件)
opincome_of_ebt	float	N	经营活动净收益/利润总额
investincome_of_ebt	float	N	价值变动净收益/利润总额
n_op_profit_of_ebt	float	N	营业外收支净额/利润总额
tax_to_ebt	float	N	所得税/利润总额
dtprofit_to_profit	float	N	扣除非经常损益后的净利润/净利润
salescash_to_or	float	N	销售商品提供劳务收到的现金/营业收入
ocf_to_or	float	N	经营活动产生的现金流量净额/营业收入
ocf_to_opincome	float	N	经营活动产生的现金流量净额/经营活动净收益
capitalized_to_da	float	N	资本支出/折旧和摊销
debt_to_assets	float	Y	资产负债率
assets_to_eqt	float	Y	权益乘数
dp_assets_to_eqt	float	Y	权益乘数(杜邦分析)
ca_to_assets	float	Y	流动资产/总资产
nca_to_assets	float	Y	非流动资产/总资产
tbassets_to_totalassets	float	Y	有形资产/总资产
int_to_talcap	float	Y	带息债务/全部投入资本
eqt_to_talcapital	float	Y	归属于母公司的股东权益/全部投入资本
currentdebt_to_debt	float	Y	流动负债/负债合计
longdeb_to_debt	float	Y	非流动负债/负债合计
ocf_to_shortdebt	float	Y	经营活动产生的现金流量净额/流动负债
debt_to_eqt	float	Y	产权比率
eqt_to_debt	float	Y	归属于母公司的股东权益/负债合计
eqt_to_interestdebt	float	Y	归属于母公司的股东权益/带息债务
tangibleasset_to_debt	float	Y	有形资产/负债合计
tangasset_to_intdebt	float	Y	有形资产/带息债务
tangibleasset_to_netdebt	float	Y	有形资产/净债务
ocf_to_debt	float	Y	经营活动产生的现金流量净额/负债合计
ocf_to_interestdebt	float	N	经营活动产生的现金流量净额/带息债务
ocf_to_netdebt	float	N	经营活动产生的现金流量净额/净债务
ebit_to_interest	float	N	已获利息倍数(EBIT/利息费用)
longdebt_to_workingcapital	float	N	长期债务与营运资金比率
ebitda_to_debt	float	N	息税折旧摊销前利润/负债合计
turn_days	float	Y	营业周期
roa_yearly	float	Y	年化总资产净利率
roa_dp	float	Y	总资产净利率(杜邦分析)
fixed_assets	float	Y	固定资产合计
profit_prefin_exp	float	N	扣除财务费用前营业利润
non_op_profit	float	N	非营业利润
op_to_ebt	float	N	营业利润／利润总额
nop_to_ebt	float	N	非营业利润／利润总额
ocf_to_profit	float	N	经营活动产生的现金流量净额／营业利润
cash_to_liqdebt	float	N	货币资金／流动负债
cash_to_liqdebt_withinterest	float	N	货币资金／带息流动负债
op_to_liqdebt	float	N	营业利润／流动负债
op_to_debt	float	N	营业利润／负债合计
roic_yearly	float	N	年化投入资本回报率
total_fa_trun	float	N	固定资产合计周转率
profit_to_op	float	Y	利润总额／营业收入
q_opincome	float	N	经营活动单季度净收益
q_investincome	float	N	价值变动单季度净收益
q_dtprofit	float	N	扣除非经常损益后的单季度净利润
q_eps	float	N	每股收益(单季度)
q_netprofit_margin	float	N	销售净利率(单季度)
q_gsprofit_margin	float	N	销售毛利率(单季度)
q_exp_to_sales	float	N	销售期间费用率(单季度)
q_profit_to_gr	float	N	净利润／营业总收入(单季度)
q_saleexp_to_gr	float	Y	销售费用／营业总收入 (单季度)
q_adminexp_to_gr	float	N	管理费用／营业总收入 (单季度)
q_finaexp_to_gr	float	N	财务费用／营业总收入 (单季度)
q_impair_to_gr_ttm	float	N	资产减值损失／营业总收入(单季度)
q_gc_to_gr	float	Y	营业总成本／营业总收入 (单季度)
q_op_to_gr	float	N	营业利润／营业总收入(单季度)
q_roe	float	Y	净资产收益率(单季度)
q_dt_roe	float	Y	净资产单季度收益率(扣除非经常损益)
q_npta	float	Y	总资产净利润(单季度)
q_opincome_to_ebt	float	N	经营活动净收益／利润总额(单季度)
q_investincome_to_ebt	float	N	价值变动净收益／利润总额(单季度)
q_dtprofit_to_profit	float	N	扣除非经常损益后的净利润／净利润(单季度)
q_salescash_to_or	float	N	销售商品提供劳务收到的现金／营业收入(单季度)
q_ocf_to_sales	float	Y	经营活动产生的现金流量净额／营业收入(单季度)
q_ocf_to_or	float	N	经营活动产生的现金流量净额／经营活动净收益(单季度)
basic_eps_yoy	float	Y	基本每股收益同比增长率(%)
dt_eps_yoy	float	Y	稀释每股收益同比增长率(%)
cfps_yoy	float	Y	每股经营活动产生的现金流量净额同比增长率(%)
op_yoy	float	Y	营业利润同比增长率(%)
ebt_yoy	float	Y	利润总额同比增长率(%)
netprofit_yoy	float	Y	归属母公司股东的净利润同比增长率(%)
dt_netprofit_yoy	float	Y	归属母公司股东的净利润-扣除非经常损益同比增长率(%)
ocf_yoy	float	Y	经营活动产生的现金流量净额同比增长率(%)
roe_yoy	float	Y	净资产收益率(摊薄)同比增长率(%)
bps_yoy	float	Y	每股净资产相对年初增长率(%)
assets_yoy	float	Y	资产总计相对年初增长率(%)
eqt_yoy	float	Y	归属母公司的股东权益相对年初增长率(%)
tr_yoy	float	Y	营业总收入同比增长率(%)
or_yoy	float	Y	营业收入同比增长率(%)
q_gr_yoy	float	N	营业总收入同比增长率(%)(单季度)
q_gr_qoq	float	N	营业总收入环比增长率(%)(单季度)
q_sales_yoy	float	Y	营业收入同比增长率(%)(单季度)
q_sales_qoq	float	N	营业收入环比增长率(%)(单季度)
q_op_yoy	float	N	营业利润同比增长率(%)(单季度)
q_op_qoq	float	Y	营业利润环比增长率(%)(单季度)
q_profit_yoy	float	N	净利润同比增长率(%)(单季度)
q_profit_qoq	float	N	净利润环比增长率(%)(单季度)
q_netprofit_yoy	float	N	归属母公司股东的净利润同比增长率(%)(单季度)
q_netprofit_qoq	float	N	归属母公司股东的净利润环比增长率(%)(单季度)
equity_yoy	float	Y	净资产同比增长率
rd_exp	float	N	研发费用
update_flag	str	N	更新标识
"""
from basis import *


class get_fin_income_daily(ts2db_by_period_and_codelist_template):
    table_name = 'hq_fin_income'  # 保存到数据库的库名
    table_name_cn = '财务利润表指标数据'  # 接口名称

    def ts2db_init(self):
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_stk_basic')  # 必须初始化，需要遍历的列表
        self.params.how_many_codes_onetime = 200  # 一次调用最多获取多少个代码对应的数据
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ann_date'],
                                  ['ts_code', 'ann_date', 'update_flag'],
                                  ['ts_code', 'ann_date', 'end_date', 'update_flag']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code, ann_date,end_date, update_flag'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'ann_date': DATE,
                                     'f_ann_date': DATE,
                                     'end_date': DATE,
                                     'report_type': NVARCHAR(1),
                                     'comp_type': NVARCHAR(1),
                                     'end_type': NVARCHAR(1),
                                     'basic_eps': DECIMAL(25, 4),
                                     'diluted_eps': DECIMAL(25, 4),
                                     'total_revenue': DECIMAL(25, 4),
                                     'revenue': DECIMAL(25, 4),
                                     'int_income': DECIMAL(25, 4),
                                     'prem_earned': DECIMAL(25, 4),
                                     'comm_income': DECIMAL(25, 4),
                                     'n_commis_income': DECIMAL(25, 4),
                                     'n_oth_income': DECIMAL(25, 4),
                                     'n_oth_b_income': DECIMAL(25, 4),
                                     'prem_income': DECIMAL(25, 4),
                                     'out_prem': DECIMAL(25, 4),
                                     'une_prem_reser': DECIMAL(25, 4),
                                     'reins_income': DECIMAL(25, 4),
                                     'n_sec_tb_income': DECIMAL(25, 4),
                                     'n_sec_uw_income': DECIMAL(25, 4),
                                     'n_asset_mg_income': DECIMAL(25, 4),
                                     'oth_b_income': DECIMAL(25, 4),
                                     'fv_value_chg_gain': DECIMAL(25, 4),
                                     'invest_income': DECIMAL(25, 4),
                                     'ass_invest_income': DECIMAL(25, 4),
                                     'forex_gain': DECIMAL(25, 4),
                                     'total_cogs': DECIMAL(25, 4),
                                     'oper_cost': DECIMAL(25, 4),
                                     'int_exp': DECIMAL(25, 4),
                                     'comm_exp': DECIMAL(25, 4),
                                     'biz_tax_surchg': DECIMAL(25, 4),
                                     'sell_exp': DECIMAL(25, 4),
                                     'admin_exp': DECIMAL(25, 4),
                                     'fin_exp': DECIMAL(25, 4),
                                     'assets_impair_loss': DECIMAL(25, 4),
                                     'prem_refund': DECIMAL(25, 4),
                                     'compens_payout': DECIMAL(25, 4),
                                     'reser_insur_liab': DECIMAL(25, 4),
                                     'div_payt': DECIMAL(25, 4),
                                     'reins_exp': DECIMAL(25, 4),
                                     'oper_exp': DECIMAL(25, 4),
                                     'compens_payout_refu': DECIMAL(25, 4),
                                     'insur_reser_refu': DECIMAL(25, 4),
                                     'reins_cost_refund': DECIMAL(25, 4),
                                     'other_bus_cost': DECIMAL(25, 4),
                                     'operate_profit': DECIMAL(25, 4),
                                     'non_oper_income': DECIMAL(25, 4),
                                     'non_oper_exp': DECIMAL(25, 4),
                                     'nca_disploss': DECIMAL(25, 4),
                                     'total_profit': DECIMAL(25, 4),
                                     'income_tax': DECIMAL(25, 4),
                                     'n_income': DECIMAL(25, 4),
                                     'n_income_attr_p': DECIMAL(25, 4),
                                     'minority_gain': DECIMAL(25, 4),
                                     'oth_compr_income': DECIMAL(25, 4),
                                     't_compr_income': DECIMAL(25, 4),
                                     'compr_inc_attr_p': DECIMAL(25, 4),
                                     'compr_inc_attr_m_s': DECIMAL(25, 4),
                                     'ebit': DECIMAL(25, 4),
                                     'ebitda': DECIMAL(25, 4),
                                     'insurance_exp': DECIMAL(25, 4),
                                     'undist_profit': DECIMAL(25, 4),
                                     'distable_profit': DECIMAL(25, 4),
                                     'rd_exp': DECIMAL(25, 4),
                                     'fin_exp_int_exp': DECIMAL(25, 4),
                                     'fin_exp_int_inc': DECIMAL(25, 4),
                                     'transfer_surplus_rese': DECIMAL(25, 4),
                                     'transfer_housing_imprest': DECIMAL(25, 4),
                                     'transfer_oth': DECIMAL(25, 4),
                                     'adj_lossgain': DECIMAL(25, 4),
                                     'withdra_legal_surplus': DECIMAL(25, 4),
                                     'withdra_legal_pubfund': DECIMAL(25, 4),
                                     'withdra_biz_devfund': DECIMAL(25, 4),
                                     'withdra_rese_fund': DECIMAL(25, 4),
                                     'withdra_oth_ersu': DECIMAL(25, 4),
                                     'workers_welfare': DECIMAL(25, 4),
                                     'distr_profit_shrhder': DECIMAL(25, 4),
                                     'prfshare_payable_dvd': DECIMAL(25, 4),
                                     'comshare_payable_dvd': DECIMAL(25, 4),
                                     'capit_comstock_div': DECIMAL(25, 4),
                                     'continued_net_profit': DECIMAL(25, 4),
                                     # 'net_after_nr_lp_correct': DECIMAL(25, 4),
                                     'update_flag': NVARCHAR(1)})

    # 抓取数据函数, 实现单次证券的抓取逻辑即可
    
    def ts2db_get_data(self):
        return self.params.ts_pro.income_vip(**{
            "ts_code": self.params.code,
            "ann_date": "",
            "start_date": self.params.str_date,
            "end_date": self.params.end_date,
            "period": "",
            "update_flag": "",
            "limit": self.params.one_time_rows_limit,
            "offset": self.params.offset
        }, fields=[
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "end_type",
            "basic_eps",
            "diluted_eps",
            "total_revenue",
            "revenue",
            "int_income",
            "prem_earned",
            "comm_income",
            "n_commis_income",
            "n_oth_income",
            "n_oth_b_income",
            "prem_income",
            "out_prem",
            "une_prem_reser",
            "reins_income",
            "n_sec_tb_income",
            "n_sec_uw_income",
            "n_asset_mg_income",
            "oth_b_income",
            "fv_value_chg_gain",
            "invest_income",
            "ass_invest_income",
            "forex_gain",
            "total_cogs",
            "oper_cost",
            "int_exp",
            "comm_exp",
            "biz_tax_surchg",
            "sell_exp",
            "admin_exp",
            "fin_exp",
            "assets_impair_loss",
            "prem_refund",
            "compens_payout",
            "reser_insur_liab",
            "div_payt",
            "reins_exp",
            "oper_exp",
            "compens_payout_refu",
            "insur_reser_refu",
            "reins_cost_refund",
            "other_bus_cost",
            "operate_profit",
            "non_oper_income",
            "non_oper_exp",
            "nca_disploss",
            "total_profit",
            "income_tax",
            "n_income",
            "n_income_attr_p",
            "minority_gain",
            "oth_compr_income",
            "t_compr_income",
            "compr_inc_attr_p",
            "compr_inc_attr_m_s",
            "ebit",
            "ebitda",
            "insurance_exp",
            "undist_profit",
            "distable_profit",
            "rd_exp",
            "fin_exp_int_exp",
            "fin_exp_int_inc",
            "transfer_surplus_rese",
            "transfer_housing_imprest",
            "transfer_oth",
            "adj_lossgain",
            "withdra_legal_surplus",
            "withdra_legal_pubfund",
            "withdra_biz_devfund",
            "withdra_rese_fund",
            "withdra_oth_ersu",
            "workers_welfare",
            "distr_profit_shrhder",
            "prfshare_payable_dvd",
            "comshare_payable_dvd",
            "capit_comstock_div",
            "continued_net_profit",
            "update_flag",
            # "net_after_nr_lp_correct",
            # "oth_income",
            # "asset_disp_income",
            # "end_net_profit",
            # "credit_impa_loss",
            # "net_expo_hedging_benefits",
            # "oth_impair_loss_assets",
            # "total_opcost",
            # "amodcost_fin_assets",
        ])


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_fin_income_daily(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
