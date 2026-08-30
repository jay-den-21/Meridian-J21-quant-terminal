"""
Created on 2021年12月5日

@author: Jayden21 <jayden0721@163.com>

每日成交持仓排名
接口：fut_holding
描述：获取每日成交持仓排名数据
限量：单次最大2000，总量不限制
积分：用户需要至少600积分才可以调取，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期 （trade_date/symbol至少输入一个参数）
symbol	str	N	合约或产品代码
start_date	str	N	开始日期(YYYYMMDD格式，下同)
end_date	str	N	结束日期
exchange	str	N	交易所代码
输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
symbol	str	Y	合约代码或类型
broker	str	Y	期货公司会员简称
vol	int	Y	成交量
vol_chg	int	Y	成交量变化
long_hld	int	Y	持买仓量
long_chg	int	Y	持买仓量变化
short_hld	int	Y	持卖仓量
short_chg	int	Y	持卖仓量变化
exchange	str	N	交易所
接口示例


pro = ts.pro_api()

df = pro.fut_holding(trade_date='20181113', symbol='C', exchange='DCE')
数据示例

     trade_date symbol  broker       vol    vol_chg  long_hld    long_chg  \
0    20181113      C    东证期货   37161.0   -6435.0   15432.0    1837.0
1    20181113      C    中信建投   12293.0   -1737.0       NaN       NaN
2    20181113      C    中信期货   31284.0   -4508.0   31672.0     102.0
3    20181113      C    中粮期货   12331.0   -5430.0   45350.0    3705.0
4    20181113      C    中融汇信       NaN       NaN       NaN       NaN
5    20181113      C    中金期货       NaN       NaN   18321.0    1491.0
6    20181113      C    五矿经易       NaN       NaN   17828.0    1729.0
7    20181113      C    倍特期货       NaN       NaN   15271.0     123.0
8    20181113      C    光大期货   72795.0  -29668.0   36988.0     752.0
9    20181113      C    兴证期货   21058.0   -4901.0   24372.0   -8720.0
10   20181113      C    北京首创       NaN       NaN       NaN       NaN
11   20181113      C    华安期货   12550.0    -919.0       NaN       NaN
12   20181113      C    华泰期货   16339.0    4783.0   30374.0    -806.0
13   20181113      C    国富期货       NaN       NaN       NaN       NaN
14   20181113      C    国投安信   49251.0  -43610.0   84537.0    4253.0
15   20181113      C    国泰君安   13095.0   -3810.0   16019.0      88.0
16   20181113      C    天风期货       NaN       NaN       NaN       NaN
17   20181113      C    安粮期货       NaN       NaN   15294.0    1651.0
18   20181113      C    山西三立       NaN       NaN   14686.0     457.0
19   20181113      C    广发期货   15539.0  -10927.0       NaN       NaN
20   20181113      C    广州金控   11303.0    1810.0       NaN       NaN

    short_hld  short_chg
0     14281.0     -384.0
1         NaN        NaN
2     15634.0    -6336.0
3     70184.0    -2658.0
4     12279.0      467.0
5         NaN        NaN
6         NaN        NaN
7         NaN        NaN
8     42506.0     -279.0
9         NaN        NaN
10    11456.0    -4974.0
11        NaN        NaN
12        NaN        NaN
13    10935.0      288.0
14   105797.0     7326.0
15    15811.0    -1489.0
16    33336.0      567.0
17        NaN        NaN
18        NaN        NaN
19        NaN        NaN
20        NaN        NaN

"""
from basis import *


class get_fut_holding(ts2db_by_date_template):
    table_name = 'hq_fut_holding'  # 保存到数据库的库名
    table_name_cn = '期货每日成交持仓排名'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.fut_holding  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 2000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['broker'], ['trade_date'], ['trade_date', 'broker', 'symbol', 'exchange']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, broker, symbol, exchange'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'symbol': NVARCHAR(50),
                                     'broker': NVARCHAR(200),
                                     'vol': DECIMAL(25, 4),
                                     'vol_chg': DECIMAL(25, 4),
                                     'long_hld': DECIMAL(25, 4),
                                     'long_chg': DECIMAL(25, 4),
                                     'short_hld': DECIMAL(25, 4),
                                     'short_chg': DECIMAL(25, 4),
                                     'exchange': NVARCHAR(20),
                                     })

    # 抓取数据函数, 实现单次证券的抓取逻辑即可
    
    def ts2db_get_data(self):
        return self.params.ts_api(**{
            "trade_date": self.params.idate,
            "symbol": "",
            "start_date": "",
            "end_date": "",
            "exchange": "",
            "limit": self.params.one_time_rows_limit,
            "offset": self.params.offset
        }, fields=[
            "trade_date",
            "symbol",
            "broker",
            "vol",
            "vol_chg",
            "long_hld",
            "long_chg",
            "short_hld",
            "short_chg",
            "exchange"
        ])


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250101', end_date=init_currentDate())
    # params = _params(str_date='20220127', end_date='20220128')
    get_fut_holding(params).run()
    pass
    # end_str = input("加载完毕，请复核是否正确执行！")
    """
    select trade_date,count(*) from hq_fut_holding group by trade_date order by trade_date desc
    """
