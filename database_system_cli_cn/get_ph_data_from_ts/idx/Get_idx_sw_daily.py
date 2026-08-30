"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

申万行业日线行情
接口：sw_daily
描述：获取申万行业日线行情（默认是申万2021版行情）
限量：单次最大4000行数据，可通过指数代码和日期参数循环提取，5000积分可调取

输入参数

名称	类型	必选	描述
ts_code	str	N	行业代码
trade_date	str	N	交易日期
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	指数代码
trade_date	str	Y	交易日期
name	str	Y	指数名称
open	float	Y	开盘点位
low	float	Y	最低点位
high	float	Y	最高点位
close	float	Y	收盘点位
change	float	Y	涨跌点位
pct_change	float	Y	涨跌幅
vol	float	Y	成交量（万股）
amount	float	Y	成交额（万元）
pe	float	Y	市盈率
pb	float	Y	市净率
float_mv	float	Y	流通市值（万元）
total_mv	float	Y	总市值（万元）


接口示例


pro = ts.pro_api('your token')

#获取20230705当日所有申万行业指数的ts_code,name,open,close,vol,pe,pb数据
df = pro.sw_daily(trade_date='20230705', fields='ts_code,name,open,close,vol,pe,pb')


数据示例

        ts_code      name      open     close         vol      pe    pb
0    801001.SI      申万50   2972.86   2946.53   275984.00   13.99  1.91
1    801002.SI      申万中小   6963.37   6896.69  1540720.00   21.19  2.47
2    801003.SI      申万Ａ指   3793.91   3769.63  6294567.00   16.56  1.78
3    801005.SI      申万创业   2841.32   2815.48  1220719.00   35.90  3.72
4    801010.SI      农林牧渔   2986.75   2946.60    83532.00   28.32  2.66
..         ...       ...       ...       ...         ...     ...   ...
434  859811.SI      生活用纸   1438.09   1418.16     2542.00   23.25  2.32
435  859821.SI  化妆品制造及其他   2674.85   2674.57     2069.00   40.63  2.33
436  859822.SI     品牌化妆品  12094.45  11877.03     2809.00   44.55  5.52
437  859852.SI      培训教育    780.30    770.10    20889.00  106.12  5.73
438  859951.SI     电视广播Ⅲ   1121.00   1122.06    24413.00   51.46  1.05
"""
from basis import *


class get_idx_sw_daily(ts2db_by_date_template):
    table_name = 'hq_idx_sw_daily'  # 保存到数据库的库名
    table_name_cn = '申万行业日线行情'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.sw_daily  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 4000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['trade_date'], ['ts_code'], ['ts_code', 'trade_date']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE,
                                     'name': NVARCHAR(200),
                                     'open': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'close': DECIMAL(25, 4),
                                     'change': DECIMAL(25, 4),
                                     'pct_change': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'pe': DECIMAL(25, 4),
                                     'pb': DECIMAL(25, 4),
                                     'float_mv': DECIMAL(25, 4),
                                     'total_mv': DECIMAL(25, 4),
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20240101', end_date=init_currentDate())
    get_idx_sw_daily(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
