"""
Created on 2025年6月10日

@author: Jayden21 <jayden0721@163.com>

通达信板块行情
接口：tdx_daily
描述：获取通达信各板块行情，包括成交和估值等数据
限量：单次提取最大3000条数据，可根据板块代码和日期参数循环提取
权限：用户积累6000积分可调取，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	板块代码：xxxxxx.TDX
trade_date	str	N	交易日期，格式YYYYMMDD,下同
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	板块代码
trade_date	str	Y	交易日期
close	float	Y	收盘点位
open	float	Y	开盘点位
high	float	Y	最高点位
low	float	Y	最低点位
pre_close	float	Y	昨日收盘点
change	float	Y	涨跌点位
pct_change	float	Y	涨跌幅%
vol	float	Y	成交量
amount	float	Y	成交额, 对于期货指数，该字段存储持仓量
rise	str	Y	收盘涨速%
vol_ratio	float	Y	量比
turnover_rate	float	Y	换手%
swing	float	Y	振幅%
up_num	int	Y	上涨家数
down_num	int	Y	下跌家数
limit_up_num	int	Y	涨停家数
limit_down_num	int	Y	跌停家数
lu_days	int	Y	连涨天数
3day	float	Y	3日涨幅%
5day	float	Y	5日涨幅%
10day	float	Y	10日涨幅%
20day	float	Y	20日涨幅%
60day	float	Y	60日涨幅%
mtd	float	Y	月初至今%
ytd	float	Y	年初至今%
1year	float	Y	一年涨幅%
pe	str	Y	市盈率
pb	str	Y	市净率
float_mv	float	Y	流通市值(亿)
ab_total_mv	float	Y	AB股总市值（亿）
float_share	float	Y	流通股(亿)
total_share	float	Y	总股本(亿)
bm_buy_net	float	Y	主买净额(元)
bm_buy_ratio	float	Y	主买占比%
bm_net	float	Y	主力净额
bm_ratio	float	Y	主力占比%
"""
from basis import *


class get_stk_tdx_daily(ts2db_by_date_template):
    table_name = 'hq_stk_tdx_daily'  # 保存到数据库的库名
    table_name_cn = '通达信板块行情'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.tdx_daily  # 告诉框架本接口对应的tushare的接口函数
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        self.params.one_time_rows_limit = 3000  # 官方文档单次最大返回量
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
                                     'close': DECIMAL(25, 4),
                                     'open': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'pre_close': DECIMAL(25, 4),
                                     'change': DECIMAL(25, 4),
                                     'pct_change': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'rise': DECIMAL(25, 4),
                                     'vol_ratio': DECIMAL(25, 4),
                                     'turnover_rate': DECIMAL(25, 4),
                                     'swing': DECIMAL(25, 4),
                                     'up_num': DECIMAL(25, 4),
                                     'down_num': DECIMAL(25, 4),
                                     'limit_up_num': DECIMAL(25, 4),
                                     'limit_down_num': DECIMAL(25, 4),
                                     'lu_days': DECIMAL(25, 4),
                                     '3day': DECIMAL(25, 4),
                                     '5day': DECIMAL(25, 4),
                                     '10day': DECIMAL(25, 4),
                                     '20day': DECIMAL(25, 4),
                                     '60day': DECIMAL(25, 4),
                                     'mtd': DECIMAL(25, 4),
                                     'ytd': DECIMAL(25, 4),
                                     '1year': DECIMAL(25, 4),
                                     'pe': DECIMAL(25, 4),
                                     'pb': DECIMAL(25, 4),
                                     'float_mv': DECIMAL(25, 4),
                                     'ab_total_mv': DECIMAL(25, 4),
                                     'float_share': DECIMAL(25, 4),
                                     'total_share': DECIMAL(25, 4),
                                     'bm_buy_net': DECIMAL(25, 4),
                                     'bm_buy_ratio': DECIMAL(25, 4),
                                     'bm_net': DECIMAL(25, 4),
                                     'bm_ratio': DECIMAL(25, 4),
                                     })


    def ts2db_get_data(self):
        return self.params.ts_api(**{
            "ts_code": "",
            "trade_date": self.params.idate,
            "start_date": "",
            "end_date": "",
            "limit": self.params.one_time_rows_limit,
            "offset": self.params.offset
        }, fields=[
            "ts_code",
            "trade_date",
            "close",
            "open",
            "high",
            "low",
            "pre_close",
            "change",
            "pct_change",
            "vol",
            "amount",
            "rise",
            "vol_ratio",
            "turnover_rate",
            "swing",
            "up_num",
            "down_num",
            "limit_up_num",
            "limit_down_num",
            "lu_days",
            "3day",
            "5day",
            "10day",
            "20day",
            "60day",
            "mtd",
            "ytd",
            "1year",
            "pe",
            "pb",
            "float_mv",
            "ab_total_mv",
            "float_share",
            "total_share",
            "bm_buy_net",
            "bm_buy_ratio",
            "bm_net",
            "bm_ratio"
        ])

if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250328', end_date=init_currentDate())
    get_stk_tdx_daily(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
