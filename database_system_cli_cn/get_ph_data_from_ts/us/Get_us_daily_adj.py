"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>

美股复权行情
接口：us_daily_adj，可以通过数据工具调试和查看数据。
描述：获取美股复权行情，支持美股全市场股票，提供股本、市值、复权因子和成交信息等多个数据指标
限量：单次最大可以提取8000条数据，可循环获取全部，支持分页提取
要求：120积分可以试用查看数据，开通正式权限请参考权限说明文档



输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码（e.g. AAPL）
trade_date	str	N	交易日期（YYYYMMDD）
start_date	str	N	开始日期（YYYYMMDD）
end_date	str	N	结束日期（YYYYMMDD）
exchange	str	N	交易所（NAS/NYS/OTC)
offset	int	N	开始行数
limit	int	N	每页行数行数


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	股票代码
trade_date	str	Y	交易日期
close	float	Y	收盘价
open	float	Y	开盘价
high	float	Y	最高价
low	float	Y	最低价
pre_close	float	Y	昨收价
change	float	Y	涨跌额
pct_change	float	Y	涨跌幅
vol	int	Y	成交量
amount	float	Y	成交额
vwap	float	Y	平均价
adj_factor	float	Y	复权因子
turnover_ratio	float	Y	换手率
free_share	int	Y	流通股本
total_share	int	Y	总股本
free_mv	float	Y	流通市值
total_mv	float	Y	总市值
exchange	str	Y	交易所代码
"""
from basis import *


class get_us_daily_adj(ts2db_by_date_template):
    table_name = 'hq_us_daily_adj'  # 保存到数据库的库名
    table_name_cn = '美股复权行情'  # 接口名称

    def ts2db_init(self):
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        self.params.ts_api = self.params.ts_pro.us_daily_adj  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 8000  # 官方文档单次最大返回量
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
                                     'pct_change': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'vwap': DECIMAL(25, 4),
                                     'adj_factor': DECIMAL(25, 4),
                                     'turnover_ratio': DECIMAL(25, 4),
                                     'free_share': DECIMAL(25, 4),
                                     'total_share': DECIMAL(25, 4),
                                     'free_mv': DECIMAL(25, 4),
                                     'total_mv': DECIMAL(25, 4),
                                     'exchange': NVARCHAR(50),
                                     })

    def ts2db_get_data(self):
        return self.params.ts_api(trade_date=self.params.idate,
                                  exchange='NAS',
                                  limit=self.params.one_time_rows_limit,
                                  offset=self.params.offset)


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250101', end_date=init_currentDate())
    get_us_daily_adj(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
