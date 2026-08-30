"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>

美股行情
接口：us_daily
描述：获取美股行情（未复权），包括全部股票全历史行情，以及重要的市场和估值指标
限量：单次最大6000行数据，可根据日期参数循环提取，开通正式权限后也可支持分页提取全部历史
要求：120积分可以试用查看数据，开通正式权限请在QQ群联系群主或积分管理员。



输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码（e.g. AAPL）
trade_date	str	N	交易日期（YYYYMMDD）
start_date	str	N	开始日期（YYYYMMDD）
end_date	str	N	结束日期（YYYYMMDD）


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	股票代码
trade_date	str	Y	交易日期
close	float	Y	收盘价
open	float	Y	开盘价
high	float	Y	最高价
low	float	Y	最低价
pre_close	float	Y	昨收价
change	float	N	涨跌额
pct_change	float	Y	涨跌幅
vol	float	Y	成交量
amount	float	Y	成交额
vwap	float	Y	平均价
turnover_ratio	float	N	换手率
total_mv	float	N	总市值
pe	float	N	PE
pb	float	N	PB
接口示例


pro = ts.pro_api()

#获取单一股票行情
df = pro.us_daily(ts_code='AAPL', start_date='20190101', end_date='20190904')

#获取某一日所有股票
df = pro.us_daily(trade_date='20190904')


数据示例

    ts_code trade_date   close    open    high     low pre_close pct_change       vol              amount    vwap
0      AAPL   20190904  209.19  208.39  209.48  207.32    205.70       1.70  19216821   4008342529.970000  208.59
1      AAPL   20190903  205.70  206.43  206.98  204.22    208.74      -1.46  20059575   4120106317.760000  205.39
2      AAPL   20190830  208.74  210.16  210.45  207.20    209.01      -0.13  21162563   4410472824.780000  208.41
3      AAPL   20190829  209.01  208.50  209.32  206.66    205.53       1.69  21007653   4380322743.230000  208.51
4      AAPL   20190828  205.53  204.10  205.72  203.32    204.16       0.67  15957633   3269889907.950000  204.91
..      ...        ...     ...     ...     ...     ...       ...        ...       ...                 ...     ...
165    AAPL   20190108  150.75  149.56  151.82  148.52    147.93       1.91  41025313   6159076907.780000  150.13
166    AAPL   20190107  147.93  148.70  148.83  145.90    148.26      -0.22  54777766   8071925608.900000  147.36
167    AAPL   20190104  148.26  144.53  148.55  143.80    142.19       4.27  58607071   8605786116.450000  146.84
168    AAPL   20190103  142.19  143.98  145.72  142.00    157.92      -9.96  91312188  13108586866.810000  143.56
169    AAPL   20190102  157.92  154.89  158.85  154.23    157.74       0.11  37039739   5814198206.330000  156.97
"""
from basis import *


class get_us_daily(ts2db_by_date_template):
    table_name = 'hq_us_daily'  # 保存到数据库的库名
    table_name_cn = '美股行情'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.us_daily  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 6000  # 官方文档单次最大返回量
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        self.params.market = 'US'  # 告诉框架该接口为港股接口，将使用港股工作日历
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
                                     'close': DECIMAL(25, 4),
                                     'open': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'pre_close': DECIMAL(25, 4),
                                     'change': DECIMAL(25, 4),
                                     'pct_chg': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'vwap': DECIMAL(25, 4),
                                     'turnover_ratio': DECIMAL(25, 4),
                                     'total_mv': DECIMAL(25, 4),
                                     'pe': DECIMAL(25, 4),
                                     'pb': DECIMAL(25, 4),
                                     })

    def ts2db_get_data(self):
        df = self.params.ts_api(**{
            "ts_code": "",
            "trade_date": self.params.idate,
            "start_date": "",
            "end_date": "",
            "offset": self.params.offset,
            "limit": self.params.one_time_rows_limit
        }, fields=[
            "ts_code",
            "trade_date",
            "close",
            "open",
            "high",
            "low",
            "pre_close",
            "pct_change",
            "vol",
            "amount",
            "vwap",
            "change",
            "turnover_ratio",
            "total_mv",
            "pe",
            "pb"
        ])

        return df

    def ts2db_clean_data(self):
        if 'pct_change' in self.df.columns:
            if 'pct_chg' in self.df.columns:
                raise ValueError(
                    "US daily data contains both 'pct_change' and 'pct_chg'"
                )
            self.df.rename(columns={'pct_change': 'pct_chg'}, inplace=True)

if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20000101', end_date=init_currentDate())
    get_us_daily(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
