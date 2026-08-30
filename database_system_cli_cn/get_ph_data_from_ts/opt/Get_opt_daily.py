"""
Created on 2021年12月5日

@author: Jayden21 <jayden0721@163.com>

期权日线行情
接口：opt_daily
描述：获取期权日线行情
限量：单次最大15000，总量不限制
积分：用户需要至少2000积分才可以调取，但有流量控制，请自行提高积分，积分越多权限越大，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	TS合约代码（输入代码或时间至少任意一个参数）
trade_date	str	N	交易日期
start_date	str	N	开始日期
end_date	str	N	结束日期
exchange	str	N	交易所


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS代码
trade_date	str	Y	交易日期
exchange	str	Y	交易市场
pre_settle	float	Y	昨结算价
pre_close	float	Y	前收盘价
open	float	Y	开盘价
high	float	Y	最高价
low	float	Y	最低价
close	float	Y	收盘价
settle	float	Y	结算价
vol	float	Y	成交量(手)
amount	float	Y	成交金额(万元)
oi	float	Y	持仓量(手)


接口示例


pro = ts.pro_api('your token')

df = pro.opt_daily(trade_date='20181212')


数据示例

        ts_code trade_date exchange  ...      vol       amount       oi
0         10001313.SH   20181212      SSE  ...  38354.0  1261.435472  98882.0
1         10001314.SH   20181212      SSE  ...  14472.0   234.933288  79980.0
2         10001315.SH   20181212      SSE  ...  10092.0    69.311776  72370.0
3         10001316.SH   20181212      SSE  ...   5434.0    16.107224  55117.0
4         10001317.SH   20181212      SSE  ...   4240.0     5.798919  61746.0
..                ...        ...      ...  ...      ...          ...      ...
753  M1911-P-2900.DCE   20181212      DCE  ...      0.0     0.000000     20.0
754  M1911-P-2950.DCE   20181212      DCE  ...      0.0     0.000000     20.0
755  M1911-P-3000.DCE   20181212      DCE  ...      0.0     0.000000     20.0
756  M1911-P-3050.DCE   20181212      DCE  ...      0.0     0.000000     20.0
757  M1911-P-3100.DCE   20181212      DCE  ...      0.0     0.000000      0.0

"""
from basis import *


class get_opt_daily(ts2db_by_date_template):
    table_name = 'hq_opt_daily'  # 保存到数据库的库名
    table_name_cn = '期权日线行情'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.opt_daily  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 15000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(50),
                                     'trade_date': DATE,
                                     'exchange': NVARCHAR(20),
                                     'pre_settle': DECIMAL(25, 4),
                                     'pre_close': DECIMAL(25, 4),
                                     'open': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'close': DECIMAL(25, 4),
                                     'settle': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'oi': DECIMAL(25, 4)
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20240101', end_date=init_currentDate())
    get_opt_daily(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
