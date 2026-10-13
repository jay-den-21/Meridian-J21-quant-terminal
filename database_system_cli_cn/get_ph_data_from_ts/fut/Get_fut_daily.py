"""
Created on 2021年12月5日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

期货日线行情
接口：fut_daily，可以通过数据工具调试和查看数据。
描述：期货日线行情数据
限量：单次最大2000条，总量不限制
积分：用户需要至少2000积分才可以调取，未来可能调整积分，请尽量多的积累积分。具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期
ts_code	str	N	合约代码
exchange	str	N	交易所代码
start_date	str	N	开始日期
end_date	str	N	结束日期
输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS合约代码
trade_date	str	Y	交易日期
pre_close	float	Y	昨收盘价
pre_settle	float	Y	昨结算价
open	float	Y	开盘价
high	float	Y	最高价
low	float	Y	最低价
close	float	Y	收盘价
settle	float	Y	结算价
change1	float	Y	涨跌1 收盘价-昨结算价
change2	float	Y	涨跌2 结算价-昨结算价
vol	float	Y	成交量(手)
amount	float	Y	成交金额(万元)
oi	float	Y	持仓量(手)
oi_chg	float	Y	持仓量变化
delv_settle	float	N	交割结算价

"""
from basis import *


class get_fut_daily(ts2db_by_date_template):
    table_name = 'hq_fut_daily'  # 保存到数据库的库名
    table_name_cn = '期货日线行情'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.fut_daily  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 2000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE,
                                     'pre_close': DECIMAL(25, 4),
                                     'pre_settle': DECIMAL(25, 4),
                                     'open': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'close': DECIMAL(25, 4),
                                     'settle': DECIMAL(25, 4),
                                     'change1': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'oi': DECIMAL(25, 4),
                                     'oi_chg': DECIMAL(25, 4),
                                     'delv_settle': DECIMAL(25, 4), })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20240101', end_date=init_currentDate())
    get_fut_daily(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
