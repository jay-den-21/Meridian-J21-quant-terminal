"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>

资产负债表
接口：balancesheet，可以通过数据工具调试和查看数据。
描述：获取上市公司资产负债表
积分：用户需要至少2000积分才可以调取，具体请参阅积分获取办法

提示：当前接口只能按单只股票获取其历史数据，如果需要获取某一季度全部上市公司数据，请使用balancesheet_vip接口（参数一致），需积攒5000积分。

输入参数

名称	类型	必选	描述
ts_code	str	Y	股票代码
ann_date	str	N	公告日期(YYYYMMDD格式，下同)
start_date	str	N	公告开始日期
end_date	str	N	公告结束日期
period	str	N	报告期(每个季度最后一天的日期，比如20171231表示年报)
report_type	str	N	报告类型：见下方详细说明
comp_type	str	N	公司类型：1一般工商业 2银行 3保险 4证券
end_type	str	N	报告期编号 （1~4表示季度，e.g. 4表示年报）
输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS股票代码
ann_date	str	Y	公告日期
f_ann_date	str	Y	实际公告日期
end_date	str	Y	报告期
report_type	str	Y	报表类型
comp_type	str	Y	公司类型(1一般工商业2银行3保险4证券)
end_type	str	Y	报告期类型
total_share	float	Y	期末总股本
cap_rese	float	Y	资本公积金
undistr_porfit	float	Y	未分配利润
surplus_rese	float	Y	盈余公积金
special_rese	float	Y	专项储备
money_cap	float	Y	货币资金
trad_asset	float	Y	交易性金融资产
notes_receiv	float	Y	应收票据
accounts_receiv	float	Y	应收账款
oth_receiv	float	Y	其他应收款
prepayment	float	Y	预付款项
div_receiv	float	Y	应收股利
int_receiv	float	Y	应收利息
inventories	float	Y	存货
amor_exp	float	Y	长期待摊费用
nca_within_1y	float	Y	一年内到期的非流动资产
sett_rsrv	float	Y	结算备付金
loanto_oth_bank_fi	float	Y	拆出资金
premium_receiv	float	Y	应收保费
reinsur_receiv	float	Y	应收分保账款
reinsur_res_receiv	float	Y	应收分保合同准备金
pur_resale_fa	float	Y	买入返售金融资产
oth_cur_assets	float	Y	其他流动资产
total_cur_assets	float	Y	流动资产合计
fa_avail_for_sale	float	Y	可供出售金融资产
htm_invest	float	Y	持有至到期投资
lt_eqt_invest	float	Y	长期股权投资
invest_real_estate	float	Y	投资性房地产
time_deposits	float	Y	定期存款
oth_assets	float	Y	其他资产
lt_rec	float	Y	长期应收款
fix_assets	float	Y	固定资产
cip	float	Y	在建工程
const_materials	float	Y	工程物资
fixed_assets_disp	float	Y	固定资产清理
produc_bio_assets	float	Y	生产性生物资产
oil_and_gas_assets	float	Y	油气资产
intan_assets	float	Y	无形资产
r_and_d	float	Y	研发支出
goodwill	float	Y	商誉
lt_amor_exp	float	Y	长期待摊费用
defer_tax_assets	float	Y	递延所得税资产
decr_in_disbur	float	Y	发放贷款及垫款
oth_nca	float	Y	其他非流动资产
total_nca	float	Y	非流动资产合计
cash_reser_cb	float	Y	现金及存放中央银行款项
depos_in_oth_bfi	float	Y	存放同业和其它金融机构款项
prec_metals	float	Y	贵金属
deriv_assets	float	Y	衍生金融资产
rr_reins_une_prem	float	Y	应收分保未到期责任准备金
rr_reins_outstd_cla	float	Y	应收分保未决赔款准备金
rr_reins_lins_liab	float	Y	应收分保寿险责任准备金
rr_reins_lthins_liab	float	Y	应收分保长期健康险责任准备金
refund_depos	float	Y	存出保证金
ph_pledge_loans	float	Y	保户质押贷款
refund_cap_depos	float	Y	存出资本保证金
indep_acct_assets	float	Y	独立账户资产
client_depos	float	Y	其中：客户资金存款
client_prov	float	Y	其中：客户备付金
transac_seat_fee	float	Y	其中:交易席位费
invest_as_receiv	float	Y	应收款项类投资
total_assets	float	Y	资产总计
lt_borr	float	Y	长期借款
st_borr	float	Y	短期借款
cb_borr	float	Y	向中央银行借款
depos_ib_deposits	float	Y	吸收存款及同业存放
loan_oth_bank	float	Y	拆入资金
trading_fl	float	Y	交易性金融负债
notes_payable	float	Y	应付票据
acct_payable	float	Y	应付账款
adv_receipts	float	Y	预收款项
sold_for_repur_fa	float	Y	卖出回购金融资产款
comm_payable	float	Y	应付手续费及佣金
payroll_payable	float	Y	应付职工薪酬
taxes_payable	float	Y	应交税费
int_payable	float	Y	应付利息
div_payable	float	Y	应付股利
oth_payable	float	Y	其他应付款
acc_exp	float	Y	预提费用
deferred_inc	float	Y	递延收益
st_bonds_payable	float	Y	应付短期债券
payable_to_reinsurer	float	Y	应付分保账款
rsrv_insur_cont	float	Y	保险合同准备金
acting_trading_sec	float	Y	代理买卖证券款
acting_uw_sec	float	Y	代理承销证券款
non_cur_liab_due_1y	float	Y	一年内到期的非流动负债
oth_cur_liab	float	Y	其他流动负债
total_cur_liab	float	Y	流动负债合计
bond_payable	float	Y	应付债券
lt_payable	float	Y	长期应付款
specific_payables	float	Y	专项应付款
estimated_liab	float	Y	预计负债
defer_tax_liab	float	Y	递延所得税负债
defer_inc_non_cur_liab	float	Y	递延收益-非流动负债
oth_ncl	float	Y	其他非流动负债
total_ncl	float	Y	非流动负债合计
depos_oth_bfi	float	Y	同业和其它金融机构存放款项
deriv_liab	float	Y	衍生金融负债
depos	float	Y	吸收存款
agency_bus_liab	float	Y	代理业务负债
oth_liab	float	Y	其他负债
prem_receiv_adva	float	Y	预收保费
depos_received	float	Y	存入保证金
ph_invest	float	Y	保户储金及投资款
reser_une_prem	float	Y	未到期责任准备金
reser_outstd_claims	float	Y	未决赔款准备金
reser_lins_liab	float	Y	寿险责任准备金
reser_lthins_liab	float	Y	长期健康险责任准备金
indept_acc_liab	float	Y	独立账户负债
pledge_borr	float	Y	其中:质押借款
indem_payable	float	Y	应付赔付款
policy_div_payable	float	Y	应付保单红利
total_liab	float	Y	负债合计
treasury_share	float	Y	减:库存股
ordin_risk_reser	float	Y	一般风险准备
forex_differ	float	Y	外币报表折算差额
invest_loss_unconf	float	Y	未确认的投资损失
minority_int	float	Y	少数股东权益
total_hldr_eqy_exc_min_int	float	Y	股东权益合计(不含少数股东权益)
total_hldr_eqy_inc_min_int	float	Y	股东权益合计(含少数股东权益)
total_liab_hldr_eqy	float	Y	负债及股东权益总计
lt_payroll_payable	float	Y	长期应付职工薪酬
oth_comp_income	float	Y	其他综合收益
oth_eqt_tools	float	Y	其他权益工具
oth_eqt_tools_p_shr	float	Y	其他权益工具(优先股)
lending_funds	float	Y	融出资金
acc_receivable	float	Y	应收款项
st_fin_payable	float	Y	应付短期融资款
payables	float	Y	应付款项
hfs_assets	float	Y	持有待售的资产
hfs_sales	float	Y	持有待售的负债
cost_fin_assets	float	Y	以摊余成本计量的金融资产
fair_value_fin_assets	float	Y	以公允价值计量且其变动计入其他综合收益的金融资产
cip_total	float	Y	在建工程(合计)(元)
oth_pay_total	float	Y	其他应付款(合计)(元)
long_pay_total	float	Y	长期应付款(合计)(元)
debt_invest	float	Y	债权投资(元)
oth_debt_invest	float	Y	其他债权投资(元)
oth_eq_invest	float	N	其他权益工具投资(元)
oth_illiq_fin_assets	float	N	其他非流动金融资产(元)
oth_eq_ppbond	float	N	其他权益工具:永续债(元)
receiv_financing	float	N	应收款项融资
use_right_assets	float	N	使用权资产
lease_liab	float	N	租赁负债
contract_assets	float	Y	合同资产
contract_liab	float	Y	合同负债
accounts_receiv_bill	float	Y	应收票据及应收账款
accounts_pay	float	Y	应付票据及应付账款
oth_rcv_total	float	Y	其他应收款(合计)（元）
fix_assets_total	float	Y	固定资产(合计)(元)
update_flag	str	Y	更新标识
接口使用说明


pro = ts.pro_api()

df = pro.balancesheet(ts_code='600000.SH', start_date='20180101', end_date='20180730', fields='ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,cap_rese')
获取某一季度全部股票数据

df2 = pro.balancesheet_vip(period='20181231',fields='ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,cap_rese')
数据样例

         ts_code  ann_date f_ann_date  end_date report_type comp_type  \
0  600000.SH  20180830   20180830  20180630           1         2
1  600000.SH  20180428   20180428  20180331           1         2

             cap_rese
0  8.176000e+10
1  8.176000e+10
主要报表类型说明

代码	类型	说明
1	合并报表	上市公司最新报表（默认）
2	单季合并	单一季度的合并报表
3	调整单季合并表	调整后的单季合并报表（如果有）
4	调整合并报表	本年度公布上年同期的财务报表数据，报告期为上年度
5	调整前合并报表	数据发生变更，将原数据进行保留，即调整前的原数据
6	母公司报表	该公司母公司的财务报表数据
7	母公司单季表	母公司的单季度表
8	母公司调整单季表	母公司调整后的单季表
9	母公司调整表	该公司母公司的本年度公布上年同期的财务报表数据
10	母公司调整前报表	母公司调整之前的原始财务报表数据
11	母公司调整前合并报表	母公司调整之前合并报表原数据
12	母公司调整前报表	母公司报表发生变更前保留的原数据
"""
from basis import *


class get_fin_balancesheet_vip(ts2db_by_date_template):
    table_name = 'hq_fin_balancesheet'  # 保存到数据库的库名
    table_name_cn = '资产负债表'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.balancesheet_vip  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 7000
        self.params.report_type = getattr(self.params, 'report_type', '')
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        # self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_stk_basic')  # 必须初始化，需要遍历的列表
        self.params.how_many_codes_onetime = 7000  # 一次调用最多获取多少个代码对应的数据
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'],
                                  ['end_date'],
                                  ['end_date', 'ts_code', 'report_type',
                                   'update_flag']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'end_date, ts_code, report_type, update_flag'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        # df = df.loc[df['percent'] > 5]
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'ann_date': DATE,
                                     'f_ann_date': DATE,
                                     'end_date': DATE,
                                     'report_type': NVARCHAR(2),
                                     'comp_type': NVARCHAR(1),
                                     'end_type': NVARCHAR(1),
                                     'total_share': DECIMAL(25, 4),
                                     'cap_rese': DECIMAL(25, 4),
                                     'undistr_porfit': DECIMAL(25, 4),
                                     'surplus_rese': DECIMAL(25, 4),
                                     'special_rese': DECIMAL(25, 4),
                                     'money_cap': DECIMAL(25, 4),
                                     'trad_asset': DECIMAL(25, 4),
                                     'notes_receiv': DECIMAL(25, 4),
                                     'accounts_receiv': DECIMAL(25, 4),
                                     'oth_receiv': DECIMAL(25, 4),
                                     'prepayment': DECIMAL(25, 4),
                                     'div_receiv': DECIMAL(25, 4),
                                     'int_receiv': DECIMAL(25, 4),
                                     'inventories': DECIMAL(25, 4),
                                     'amor_exp': DECIMAL(25, 4),
                                     'nca_within_1y': DECIMAL(25, 4),
                                     'sett_rsrv': DECIMAL(25, 4),
                                     'loanto_oth_bank_fi': DECIMAL(25, 4),
                                     'premium_receiv': DECIMAL(25, 4),
                                     'reinsur_receiv': DECIMAL(25, 4),
                                     'reinsur_res_receiv': DECIMAL(25, 4),
                                     'pur_resale_fa': DECIMAL(25, 4),
                                     'oth_cur_assets': DECIMAL(25, 4),
                                     'total_cur_assets': DECIMAL(25, 4),
                                     'fa_avail_for_sale': DECIMAL(25, 4),
                                     'htm_invest': DECIMAL(25, 4),
                                     'lt_eqt_invest': DECIMAL(25, 4),
                                     'invest_real_estate': DECIMAL(25, 4),
                                     'time_deposits': DECIMAL(25, 4),
                                     'oth_assets': DECIMAL(25, 4),
                                     'lt_rec': DECIMAL(25, 4),
                                     'fix_assets': DECIMAL(25, 4),
                                     'cip': DECIMAL(25, 4),
                                     'const_materials': DECIMAL(25, 4),
                                     'fixed_assets_disp': DECIMAL(25, 4),
                                     'produc_bio_assets': DECIMAL(25, 4),
                                     'oil_and_gas_assets': DECIMAL(25, 4),
                                     'intan_assets': DECIMAL(25, 4),
                                     'r_and_d': DECIMAL(25, 4),
                                     'goodwill': DECIMAL(25, 4),
                                     'lt_amor_exp': DECIMAL(25, 4),
                                     'defer_tax_assets': DECIMAL(25, 4),
                                     'decr_in_disbur': DECIMAL(25, 4),
                                     'oth_nca': DECIMAL(25, 4),
                                     'total_nca': DECIMAL(25, 4),
                                     'cash_reser_cb': DECIMAL(25, 4),
                                     'depos_in_oth_bfi': DECIMAL(25, 4),
                                     'prec_metals': DECIMAL(25, 4),
                                     'deriv_assets': DECIMAL(25, 4),
                                     'rr_reins_une_prem': DECIMAL(25, 4),
                                     'rr_reins_outstd_cla': DECIMAL(25, 4),
                                     'rr_reins_lins_liab': DECIMAL(25, 4),
                                     'rr_reins_lthins_liab': DECIMAL(25, 4),
                                     'refund_depos': DECIMAL(25, 4),
                                     'ph_pledge_loans': DECIMAL(25, 4),
                                     'refund_cap_depos': DECIMAL(25, 4),
                                     'indep_acct_assets': DECIMAL(25, 4),
                                     'client_depos': DECIMAL(25, 4),
                                     'client_prov': DECIMAL(25, 4),
                                     'transac_seat_fee': DECIMAL(25, 4),
                                     'invest_as_receiv': DECIMAL(25, 4),
                                     'total_assets': DECIMAL(25, 4),
                                     'lt_borr': DECIMAL(25, 4),
                                     'st_borr': DECIMAL(25, 4),
                                     'cb_borr': DECIMAL(25, 4),
                                     'depos_ib_deposits': DECIMAL(25, 4),
                                     'loan_oth_bank': DECIMAL(25, 4),
                                     'trading_fl': DECIMAL(25, 4),
                                     'notes_payable': DECIMAL(25, 4),
                                     'acct_payable': DECIMAL(25, 4),
                                     'adv_receipts': DECIMAL(25, 4),
                                     'sold_for_repur_fa': DECIMAL(25, 4),
                                     'comm_payable': DECIMAL(25, 4),
                                     'payroll_payable': DECIMAL(25, 4),
                                     'taxes_payable': DECIMAL(25, 4),
                                     'int_payable': DECIMAL(25, 4),
                                     'div_payable': DECIMAL(25, 4),
                                     'oth_payable': DECIMAL(25, 4),
                                     'acc_exp': DECIMAL(25, 4),
                                     'deferred_inc': DECIMAL(25, 4),
                                     'st_bonds_payable': DECIMAL(25, 4),
                                     'payable_to_reinsurer': DECIMAL(25, 4),
                                     'rsrv_insur_cont': DECIMAL(25, 4),
                                     'acting_trading_sec': DECIMAL(25, 4),
                                     'acting_uw_sec': DECIMAL(25, 4),
                                     'non_cur_liab_due_1y': DECIMAL(25, 4),
                                     'oth_cur_liab': DECIMAL(25, 4),
                                     'total_cur_liab': DECIMAL(25, 4),
                                     'bond_payable': DECIMAL(25, 4),
                                     'lt_payable': DECIMAL(25, 4),
                                     'specific_payables': DECIMAL(25, 4),
                                     'estimated_liab': DECIMAL(25, 4),
                                     'defer_tax_liab': DECIMAL(25, 4),
                                     'defer_inc_non_cur_liab': DECIMAL(25, 4),
                                     'oth_ncl': DECIMAL(25, 4),
                                     'total_ncl': DECIMAL(25, 4),
                                     'depos_oth_bfi': DECIMAL(25, 4),
                                     'deriv_liab': DECIMAL(25, 4),
                                     'depos': DECIMAL(25, 4),
                                     'agency_bus_liab': DECIMAL(25, 4),
                                     'oth_liab': DECIMAL(25, 4),
                                     'prem_receiv_adva': DECIMAL(25, 4),
                                     'depos_received': DECIMAL(25, 4),
                                     'ph_invest': DECIMAL(25, 4),
                                     'reser_une_prem': DECIMAL(25, 4),
                                     'reser_outstd_claims': DECIMAL(25, 4),
                                     'reser_lins_liab': DECIMAL(25, 4),
                                     'reser_lthins_liab': DECIMAL(25, 4),
                                     'indept_acc_liab': DECIMAL(25, 4),
                                     'pledge_borr': DECIMAL(25, 4),
                                     'indem_payable': DECIMAL(25, 4),
                                     'policy_div_payable': DECIMAL(25, 4),
                                     'total_liab': DECIMAL(25, 4),
                                     'treasury_share': DECIMAL(25, 4),
                                     'ordin_risk_reser': DECIMAL(25, 4),
                                     'forex_differ': DECIMAL(25, 4),
                                     'invest_loss_unconf': DECIMAL(25, 4),
                                     'minority_int': DECIMAL(25, 4),
                                     'total_hldr_eqy_exc_min_int': DECIMAL(25, 4),
                                     'total_hldr_eqy_inc_min_int': DECIMAL(25, 4),
                                     'total_liab_hldr_eqy': DECIMAL(25, 4),
                                     'lt_payroll_payable': DECIMAL(25, 4),
                                     'oth_comp_income': DECIMAL(25, 4),
                                     'oth_eqt_tools': DECIMAL(25, 4),
                                     'oth_eqt_tools_p_shr': DECIMAL(25, 4),
                                     'lending_funds': DECIMAL(25, 4),
                                     'acc_receivable': DECIMAL(25, 4),
                                     'st_fin_payable': DECIMAL(25, 4),
                                     'payables': DECIMAL(25, 4),
                                     'hfs_assets': DECIMAL(25, 4),
                                     'hfs_sales': DECIMAL(25, 4),
                                     'cost_fin_assets': DECIMAL(25, 4),
                                     'fair_value_fin_assets': DECIMAL(25, 4),
                                     'cip_total': DECIMAL(25, 4),
                                     'oth_pay_total': DECIMAL(25, 4),
                                     'long_pay_total': DECIMAL(25, 4),
                                     'debt_invest': DECIMAL(25, 4),
                                     'oth_debt_invest': DECIMAL(25, 4),
                                     'oth_eq_invest': DECIMAL(25, 4),
                                     'oth_illiq_fin_assets': DECIMAL(25, 4),
                                     'oth_eq_ppbond': DECIMAL(25, 4),
                                     'receiv_financing': DECIMAL(25, 4),
                                     'use_right_assets': DECIMAL(25, 4),
                                     'lease_liab': DECIMAL(25, 4),
                                     'contract_assets': DECIMAL(25, 4),
                                     'contract_liab': DECIMAL(25, 4),
                                     'accounts_receiv_bill': DECIMAL(25, 4),
                                     'accounts_pay': DECIMAL(25, 4),
                                     'oth_rcv_total': DECIMAL(25, 4),
                                     'fix_assets_total': DECIMAL(25, 4),
                                     'audit_fees': DECIMAL(25, 4),
                                     'audit_result': NVARCHAR(250),
                                     'audit_agency': NVARCHAR(250),
                                     'nac_wthin_1y': DECIMAL(25, 4),
                                     'audit_sign': NVARCHAR(250),
                                     'update_flag': NVARCHAR(1)
                                     })

    # 抓取数据函数, 实现单次证券的抓取逻辑即可
    
    def ts2db_get_data(self):
        return self.params.ts_api(**{
            "ts_code": "",
            "ann_date": "",
            "f_ann_date": "",
            "start_date": "",
            "end_date": "",
            "period": self.params.idate,
            "report_type": self.params.report_type,
            "comp_type": "",
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
            "total_share",
            "cap_rese",
            "undistr_porfit",
            "surplus_rese",
            "special_rese",
            "money_cap",
            "trad_asset",
            "notes_receiv",
            "accounts_receiv",
            "oth_receiv",
            "prepayment",
            "div_receiv",
            "int_receiv",
            "inventories",
            "amor_exp",
            "nca_within_1y",
            "sett_rsrv",
            "loanto_oth_bank_fi",
            "premium_receiv",
            "reinsur_receiv",
            "reinsur_res_receiv",
            "pur_resale_fa",
            "oth_cur_assets",
            "total_cur_assets",
            "fa_avail_for_sale",
            "htm_invest",
            "lt_eqt_invest",
            "invest_real_estate",
            "time_deposits",
            "oth_assets",
            "lt_rec",
            "fix_assets",
            "cip",
            "const_materials",
            "fixed_assets_disp",
            "produc_bio_assets",
            "oil_and_gas_assets",
            "intan_assets",
            "r_and_d",
            "goodwill",
            "lt_amor_exp",
            "defer_tax_assets",
            "decr_in_disbur",
            "oth_nca",
            "total_nca",
            "cash_reser_cb",
            "depos_in_oth_bfi",
            "prec_metals",
            "deriv_assets",
            "rr_reins_une_prem",
            "rr_reins_outstd_cla",
            "rr_reins_lins_liab",
            "rr_reins_lthins_liab",
            "refund_depos",
            "ph_pledge_loans",
            "refund_cap_depos",
            "indep_acct_assets",
            "client_depos",
            "client_prov",
            "transac_seat_fee",
            "invest_as_receiv",
            "total_assets",
            "lt_borr",
            "st_borr",
            "cb_borr",
            "depos_ib_deposits",
            "loan_oth_bank",
            "trading_fl",
            "notes_payable",
            "acct_payable",
            "adv_receipts",
            "sold_for_repur_fa",
            "comm_payable",
            "payroll_payable",
            "taxes_payable",
            "int_payable",
            "div_payable",
            "oth_payable",
            "acc_exp",
            "deferred_inc",
            "st_bonds_payable",
            "payable_to_reinsurer",
            "rsrv_insur_cont",
            "acting_trading_sec",
            "acting_uw_sec",
            "non_cur_liab_due_1y",
            "oth_cur_liab",
            "total_cur_liab",
            "bond_payable",
            "lt_payable",
            "specific_payables",
            "estimated_liab",
            "defer_tax_liab",
            "defer_inc_non_cur_liab",
            "oth_ncl",
            "total_ncl",
            "depos_oth_bfi",
            "deriv_liab",
            "depos",
            "agency_bus_liab",
            "oth_liab",
            "prem_receiv_adva",
            "depos_received",
            "ph_invest",
            "reser_une_prem",
            "reser_outstd_claims",
            "reser_lins_liab",
            "reser_lthins_liab",
            "indept_acc_liab",
            "pledge_borr",
            "indem_payable",
            "policy_div_payable",
            "total_liab",
            "treasury_share",
            "ordin_risk_reser",
            "forex_differ",
            "invest_loss_unconf",
            "minority_int",
            "total_hldr_eqy_exc_min_int",
            "total_hldr_eqy_inc_min_int",
            "total_liab_hldr_eqy",
            "lt_payroll_payable",
            "oth_comp_income",
            "oth_eqt_tools",
            "oth_eqt_tools_p_shr",
            "lending_funds",
            "acc_receivable",
            "st_fin_payable",
            "payables",
            "hfs_assets",
            "hfs_sales",
            "cost_fin_assets",
            "fair_value_fin_assets",
            "contract_assets",
            "contract_liab",
            "accounts_receiv_bill",
            "accounts_pay",
            "oth_rcv_total",
            "fix_assets_total",
            "cip_total",
            "oth_pay_total",
            "long_pay_total",
            "debt_invest",
            "oth_debt_invest",
            "update_flag"
        ])


def get_fin_balancesheet_vip_run(params):
    for report_type_i in range(1, 13):
        params.report_type = report_type_i
        logging.info(f"开始抓取 report_type类型为：{report_type_i} 的利润表数据！")
        get_fin_balancesheet_vip(params).run()


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20240101', end_date=init_currentDate())
    get_fin_balancesheet_vip_run(params)

    # end_str = input("加载完毕，请复核是否正确执行！")
