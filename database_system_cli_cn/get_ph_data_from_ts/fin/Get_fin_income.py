"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

利润表
接口：income_vip，可以通过数据工具调试和查看数据。
描述：获取上市公司财务利润表数据
积分：用户需要至少5000积分才可以调取，具体请参阅积分获取办法

提示：本接口按单只股票代码获取历史数据；income_vip 与 income 参数一致，
也支持按报告期获取某一季度全部上市公司数据。

输入参数

名称	类型	必选	描述
ts_code	str	Y	股票代码
ann_date	str	N	公告日期（YYYYMMDD格式，下同）
f_ann_date	str	N	实际公告日期
start_date	str	N	报告期开始日期
end_date	str	N	报告期结束日期
period	str	N	报告期
report_type	str	N	报告类型
comp_type	str	N	公司类型（1一般工商业2银行3保险4证券）
end_type	str	N	报告期编码（1~4表示季度，e.g. 4表示年报）
输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS代码
ann_date	str	Y	公告日期
f_ann_date	str	Y	实际公告日期
end_date	str	Y	报告期
report_type	str	Y	报告类型 见底部表
comp_type	str	Y	公司类型(1一般工商业2银行3保险4证券)
end_type	str	Y	报告期类型
basic_eps	float	Y	基本每股收益
diluted_eps	float	Y	稀释每股收益
total_revenue	float	Y	营业总收入
revenue	float	Y	营业收入
int_income	float	Y	利息收入
prem_earned	float	Y	已赚保费
comm_income	float	Y	手续费及佣金收入
n_commis_income	float	Y	手续费及佣金净收入
n_oth_income	float	Y	其他经营净收益
n_oth_b_income	float	Y	加:其他业务净收益
prem_income	float	Y	保险业务收入
out_prem	float	Y	减:分出保费
une_prem_reser	float	Y	提取未到期责任准备金
reins_income	float	Y	其中:分保费收入
n_sec_tb_income	float	Y	代理买卖证券业务净收入
n_sec_uw_income	float	Y	证券承销业务净收入
n_asset_mg_income	float	Y	受托客户资产管理业务净收入
oth_b_income	float	Y	其他业务收入
fv_value_chg_gain	float	Y	加:公允价值变动净收益
invest_income	float	Y	加:投资净收益
ass_invest_income	float	Y	其中:对联营企业和合营企业的投资收益
forex_gain	float	Y	加:汇兑净收益
total_cogs	float	Y	营业总成本
oper_cost	float	Y	减:营业成本
int_exp	float	Y	减:利息支出
comm_exp	float	Y	减:手续费及佣金支出
biz_tax_surchg	float	Y	减:营业税金及附加
sell_exp	float	Y	减:销售费用
admin_exp	float	Y	减:管理费用
fin_exp	float	Y	减:财务费用
assets_impair_loss	float	Y	减:资产减值损失
prem_refund	float	Y	退保金
compens_payout	float	Y	赔付总支出
reser_insur_liab	float	Y	提取保险责任准备金
div_payt	float	Y	保户红利支出
reins_exp	float	Y	分保费用
oper_exp	float	Y	营业支出
compens_payout_refu	float	Y	减:摊回赔付支出
insur_reser_refu	float	Y	减:摊回保险责任准备金
reins_cost_refund	float	Y	减:摊回分保费用
other_bus_cost	float	Y	其他业务成本
operate_profit	float	Y	营业利润
non_oper_income	float	Y	加:营业外收入
non_oper_exp	float	Y	减:营业外支出
nca_disploss	float	Y	其中:减:非流动资产处置净损失
total_profit	float	Y	利润总额
income_tax	float	Y	所得税费用
n_income	float	Y	净利润(含少数股东损益)
n_income_attr_p	float	Y	净利润(不含少数股东损益)
minority_gain	float	Y	少数股东损益
oth_compr_income	float	Y	其他综合收益
t_compr_income	float	Y	综合收益总额
compr_inc_attr_p	float	Y	归属于母公司(或股东)的综合收益总额
compr_inc_attr_m_s	float	Y	归属于少数股东的综合收益总额
ebit	float	Y	息税前利润
ebitda	float	Y	息税折旧摊销前利润
insurance_exp	float	Y	保险业务支出
undist_profit	float	Y	年初未分配利润
distable_profit	float	Y	可分配利润
rd_exp	float	Y	研发费用
fin_exp_int_exp	float	Y	财务费用:利息费用
fin_exp_int_inc	float	Y	财务费用:利息收入
transfer_surplus_rese	float	Y	盈余公积转入
transfer_housing_imprest	float	Y	住房周转金转入
transfer_oth	float	Y	其他转入
adj_lossgain	float	Y	调整以前年度损益
withdra_legal_surplus	float	Y	提取法定盈余公积
withdra_legal_pubfund	float	Y	提取法定公益金
withdra_biz_devfund	float	Y	提取企业发展基金
withdra_rese_fund	float	Y	提取储备基金
withdra_oth_ersu	float	Y	提取任意盈余公积金
workers_welfare	float	Y	职工奖金福利
distr_profit_shrhder	float	Y	可供股东分配的利润
prfshare_payable_dvd	float	Y	应付优先股股利
comshare_payable_dvd	float	Y	应付普通股股利
capit_comstock_div	float	Y	转作股本的普通股股利
net_after_nr_lp_correct	float	N	扣除非经常性损益后的净利润（更正前）
credit_impa_loss	float	N	信用减值损失
net_expo_hedging_benefits	float	N	净敞口套期收益
oth_impair_loss_assets	float	N	其他资产减值损失
total_opcost	float	N	营业总成本（二）
amodcost_fin_assets	float	N	以摊余成本计量的金融资产终止确认收益
oth_income	float	N	其他收益
asset_disp_income	float	N	资产处置收益
continued_net_profit	float	N	持续经营净利润
end_net_profit	float	N	终止经营净利润
update_flag	str	Y	更新标识
接口使用说明


pro = ts.pro_api()

df = pro.income_vip(ts_code='600000.SH', start_date='20180101', end_date='20180730', fields='ts_code,ann_date,f_ann_date,
end_date,report_type,comp_type,basic_eps,diluted_eps')
获取某一季度全部股票数据


df = pro.income_vip(period='20181231',fields='ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,basic_eps,
diluted_eps')
数据样例

     ts_code  ann_date f_ann_date  end_date report_type comp_type  basic_eps  diluted_eps  \
0  600000.SH  20180428   20180428  20180331           1         2       0.46         0.46
1  600000.SH  20180428   20180428  20180331           1         2       0.46         0.46
2  600000.SH  20180428   20180428  20171231           1         2       1.84         1.84
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
11	调整前合并报表	调整之前合并报表原数据
12	母公司调整前报表	母公司报表发生变更前保留的原数据

"""
from basis import *


# 该处使用了模板类的设计模式，接口只用继承行为相同的模板类，即可获取模板类的抓取能力；
# 这里的接口类只用实现自己的存入数据库函数write_db即可，当然必要的参数初始化也需要
# 自己扩展接口时，可以参照一个现成的，抓取行为一样的接口进行改写，改写代码也就上面的两个函数
# 使用时，只需要实例化改接口类后，调用run()方法即可
class get_fin_income(ts2db_by_codelist_template):
    table_name = 'hq_fin_income'  # 保存到数据库的库名
    table_name_cn = '利润表'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.income_vip  # 告诉框架本接口对应的tushare的接口函数
        self.params.report_type = getattr(self.params, 'report_type', '')
        self.params.one_time_rows_limit = 9000
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_stk_basic')  # 必须初始化，需要遍历的列表
        self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据
        # 框架会使用basis.params.py中的默认参数，以下需要对每个接口单独配置行为参数，可以打开以下参数，进行设置
        # self.params.one_time_rows_limit = 5000  # 该接口限制每次调用，最大获取数据量
        # self.params.times_limit = 800  # 该接口限制,每分钟最多调用次数
        # self.params.sleep_time = 61  # 一分钟内到了最多调用次数上线后，休眠多少秒
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        # 自动维护数据库表的索引，提高数据访问性能，一般能提高至少一个数量级；
        # 可根据查询数据的需要自定义一些索引，提高查询性能（只要在这里定义了，框架会自动帮你维护索引）
        # 这里一个列表即一个索引，需建立多个索引则配置多个列表，比如：self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # 注意：至少把下面去重的键值，建立一个索引
        self.params.db_indexes = [['ts_code'],
                                  ['ann_date', 'ts_code'],
                                  ['ts_code', 'ann_date', 'f_ann_date', 'end_date', 'update_flag']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        # 数据整理函数，定义后框架会自动调用，以进行数据整理
        # 数据整理是根据抓取数据的时间段进行整理的，如需指定特定时间段进行整理，请使用“单独运行数据整理.py”程序
        # 数据去重，配置好该数据接口的唯一键字组合后，框架会以此进行去重处理
        self.params.deal_data__duplicate_data_key = 'ts_code, ann_date, report_type, update_flag, end_type, comp_type, basic_eps,total_revenue,total_cogs'

    def ts2db_get_data(self):
        return self.params.ts_api(**{
            "ts_code": self.params.code,
            "ann_date": "",
            "start_date": self.params.str_date,
            "end_date": self.params.end_date,
            "period": "",
            "report_type": self.params.report_type,
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
            # "oth_income",
            # "asset_disp_income",
            "end_net_profit",
            "credit_impa_loss",
            "net_expo_hedging_benefits",
            "oth_impair_loss_assets",
            "total_opcost",
            "amodcost_fin_assets"
        ])

    # 每只证券抓取后，实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'ann_date': DATE,
                                     'f_ann_date': DATE,
                                     'end_date': DATE,
                                     'report_type': NVARCHAR(20),
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
                                     'update_flag': NVARCHAR(1)})


def get_fin_income_run(params):
    for report_type_i in range(1, 13):
        params.report_type = report_type_i
        logging.info(f"开始抓取 report_type类型为：{report_type_i} 的利润表数据！")
        get_fin_income(params).run()


if __name__ == '__main__':
    get_fin_income_run(_params())

    # end_str = input("加载完毕，请复核是否正确执行！")
