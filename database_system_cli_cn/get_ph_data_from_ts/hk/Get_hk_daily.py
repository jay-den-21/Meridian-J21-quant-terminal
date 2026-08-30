"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

港股行情
接口：hk_daily，可以通过数据工具调试和查看数据。
描述：获取港股每日增量和历史行情
限量：单次最大提取5000行记录，可多次提取，总量不限制
积分：用户需要至少5000积分才可以调取，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码
trade_date	str	N	交易日期
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	股票代码
trade_date	str	Y	交易日期
open	float	Y	开盘价
high	float	Y	最高价
low	float	Y	最低价
close	float	Y	收盘价
pre_close	float	Y	昨收价
change	float	Y	涨跌额
pct_chg	float	Y	涨跌幅(%)
vol	float	Y	成交量(股)
amount	float	Y	成交额(元)


接口示例


pro = ts.pro_api()

#获取单一股票行情
df = pro.hk_daily(ts_code='00001.HK', start_date='20190101', end_date='20190904')

#获取某一日所有股票
df = pro.hk_daily(trade_date='20190904')


数据示例

      ts_code trade_date   open  ...  pct_chg         vol        amount
0    00001.HK   20190904  66.90  ...     3.45   8212577.0  5.619534e+08
1    00001.HK   20190903  66.40  ...    -0.52   3905632.0  2.598397e+08
2    00001.HK   20190902  67.50  ...    -0.71   6547427.0  4.397896e+08
3    00001.HK   20190830  69.60  ...    -0.73   7731576.0  5.299299e+08
4    00001.HK   20190829  69.05  ...     0.36   7902900.0  5.428812e+08
5    00001.HK   20190828  69.05  ...    -1.08   8973397.0  6.183098e+08
6    00001.HK   20190827  70.50  ...     0.00   6286907.0  4.359607e+08
7    00001.HK   20190826  69.40  ...    -1.91   8054636.0  5.554714e+08
8    00001.HK   20190823  70.45  ...    -0.42   5449506.0  3.863469e+08
9    00001.HK   20190822  71.50  ...    -0.49   5299641.0  3.750118e+08
10   00001.HK   20190821  70.00  ...     1.71   7045145.0  5.019940e+08
11   00001.HK   20190820  70.60  ...     0.21   7844342.0  5.522724e+08
12   00001.HK   20190819  68.30  ...     3.02  10498548.0  7.332229e+08
13   00001.HK   20190816  66.30  ...     2.03   8311992.0  5.599711e+08
14   00001.HK   20190815  64.40  ...     2.23   9695771.0  6.378087e+08
15   00001.HK   20190814  66.25  ...    -1.29  10816336.0  7.058398e+08
16   00001.HK   20190813  67.00  ...    -2.58  12104207.0  8.037089e+08
17   00001.HK   20190812  67.35  ...    -0.37   5775321.0  3.921880e+08
18   00001.HK   20190809  67.65  ...    -0.15   5996124.0  4.078781e+08
19   00001.HK   20190808  67.65  ...     0.52   8208977.0  5.587438e+08
20   00001.HK   20190807  68.20  ...    -1.31   8215702.0  5.567659e+08
"""
from basis import *


class get_hk_daily(ts2db_by_date_template):
    table_name = 'hq_hk_daily'  # 保存到数据库的库名
    table_name_cn = '港股行情'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.hk_daily  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 5000  # 官方文档单次最大返回量
        self.params.market = 'HK'  # 告诉框架该接口为港股接口，将使用港股工作日历
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
                                     'open': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'close': DECIMAL(25, 4),
                                     'change': DECIMAL(25, 4),
                                     'pct_chg': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4)})


if __name__ == '__main__':
    # 初始化
    params = _params(str_date=init_currentDate(), end_date=init_currentDate())
    get_hk_daily(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
