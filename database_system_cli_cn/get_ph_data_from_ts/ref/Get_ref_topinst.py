"""
Created on 2021年7月20日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

龙虎榜机构明细
接口：top_inst
描述：龙虎榜机构成交明细
限量：单次最大10000
积分：用户需要至少300积分才可以调取，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
trade_date	str	Y	交易日期
ts_code	str	N	TS代码
输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
ts_code	str	Y	TS代码
exalter	str	Y	营业部名称
side	str	Y	买卖类型0：买入金额最大的前5名， 1：卖出金额最大的前5名
buy	float	Y	买入额（元）
buy_rate	float	Y	买入占总成交比例
sell	float	Y	卖出额（元）
sell_rate	float	Y	卖出占总成交比例
net_buy	float	Y	净成交额（元）
reason	str	Y	上榜理由

"""
from basis import *


class get_ref_topinst(ts2db_by_date_template):
    table_name = 'hq_ref_topinst'  # 保存到数据库的库名
    table_name_cn = '龙虎榜机构明细'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.top_inst  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 10000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'],
                                  ['trade_date', 'ts_code'],
                                  ['trade_date', 'ts_code', 'exalter', 'side', 'net_buy', 'reason']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code, exalter, side, net_buy, reason'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'ts_code': NVARCHAR(20),
                                     'exalter': NVARCHAR(255),
                                     'side': DECIMAL(1),
                                     'buy': DECIMAL(25, 4),
                                     'buy_rate': DECIMAL(25, 4),
                                     'sell': DECIMAL(25, 4),
                                     'sell_rate': DECIMAL(25, 4),
                                     'net_buy': DECIMAL(25, 4),
                                     'reason': NVARCHAR(255), })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_ref_topinst(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
