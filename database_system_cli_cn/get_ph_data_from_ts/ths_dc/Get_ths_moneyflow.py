"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

个股资金流向（THS）
接口：moneyflow_ths
描述：获取同花顺个股资金流向数据，每日盘后更新
限量：单次最大6000，可根据日期或股票代码循环提取数据
积分：用户需要至少5000积分才可以调取，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码
trade_date	str	N	交易日期（YYYYMMDD格式，下同）
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
ts_code	str	Y	股票代码
name	str	Y	股票名称
pct_change	float	Y	涨跌幅
latest	float	Y	最新价
net_amount	float	Y	资金净流入(万元)
net_d5_amount	float	Y	5日主力净额(万元)
buy_lg_amount	float	Y	今日大单净流入额(万元)
buy_lg_amount_rate	float	Y	今日大单净流入占比(%)
buy_md_amount	float	Y	今日中单净流入额(万元)
buy_md_amount_rate	float	Y	今日中单净流入占比(%)
buy_sm_amount	float	Y	今日小单净流入额(万元)
buy_sm_amount_rate	float	Y	今日小单净流入占比(%)


接口示例


pro = ts.pro_api()

#获取单日全部股票数据
df = pro.moneyflow_ths(trade_date='20241011')

#获取单个股票数据
df = pro.moneyflow_ths(ts_code='002149.SZ', start_date='20241001', end_date='20241011')

    trade_date ts_code  name  pct_change  ...  buy_md_amount  buy_md_amount_rate  buy_sm_amount  buy_sm_amount_rate
0   20241011  002149.SZ  西部材料        2.47  ...         -589.0                5.43         -191.0                1.76
1   20241010  002149.SZ  西部材料        1.22  ...        -2732.0               15.38        -1031.0                5.81
2   20241009  002149.SZ  西部材料        7.00  ...        -1941.0                9.25        -2079.0                9.90
3   20241008  002149.SZ  西部材料        5.17  ...        -2985.0                7.93        -2507.0                6.66
"""
from basis import *


class get_ths_moneyflow(ts2db_by_period_template):
    table_name = 'hq_ths_moneyflow'  # 保存到数据库的库名
    table_name_cn = '同花顺个股资金流向'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.moneyflow_ths  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 6000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE,
                                     'buy_sm_vol': DECIMAL(25, 4),
                                     'buy_sm_amount': DECIMAL(25, 4),
                                     'sell_sm_vol': DECIMAL(25, 4),
                                     'sell_sm_amount': DECIMAL(25, 4),
                                     'buy_md_vol': DECIMAL(25, 4),
                                     'buy_md_amount': DECIMAL(25, 4),
                                     'sell_md_vol': DECIMAL(25, 4),
                                     'sell_md_amount': DECIMAL(25, 4),
                                     'buy_lg_vol': DECIMAL(25, 4),
                                     'buy_lg_amount': DECIMAL(25, 4),
                                     'sell_lg_vol': DECIMAL(25, 4),
                                     'sell_lg_amount': DECIMAL(25, 4),
                                     'buy_elg_vol': DECIMAL(25, 4),
                                     'buy_elg_amount': DECIMAL(25, 4),
                                     'sell_elg_vol': DECIMAL(25, 4),
                                     'sell_elg_amount': DECIMAL(25, 4),
                                     'net_mf_vol': DECIMAL(25, 4),
                                     'net_mf_amount': DECIMAL(25, 4)})


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20241001', end_date=init_currentDate())
    get_ths_moneyflow(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
