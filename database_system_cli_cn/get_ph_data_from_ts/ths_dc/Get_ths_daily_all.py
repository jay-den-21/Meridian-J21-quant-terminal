"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

同花顺板块指数行情
接口：ths_daily
描述：获取同花顺板块指数行情。注：数据版权归属同花顺，如做商业用途，请主动联系同花顺，如需帮助请联系微信migedata 。
限量：单次最大3000行数据（5000积分），可根据指数代码、日期参数循环提取。



输入参数

名称	类型	必选	描述
ts_code	str	N	指数代码
trade_date	str	N	交易日期（YYYYMMDD格式，下同）
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS指数代码
trade_date	str	Y	交易日
close	float	Y	收盘点位
open	float	Y	开盘点位
high	float	Y	最高点位
low	float	Y	最低点位
pre_close	float	Y	昨日收盘点
avg_price	float	Y	平均价
change	float	Y	涨跌点位
pct_change	float	Y	涨跌幅
vol	float	Y	成交量
turnover_rate	float	Y	换手率
total_mv	float	N	总市值
float_mv	float	N	流通市值


接口示例


pro = ts.pro_api()

df = pro.ths_daily(ts_code='865001.TI', start_date='20200101', end_date='20210101', fields='ts_code,trade_date,open,close,high,low,pct_change')


数据样例

       ts_code trade_date      close       open       high        low pct_change           vol
0    865001.TI   20201231  1664.7530  1660.7060  1671.2290  1649.4200     0.5646  13224.260000
1    865001.TI   20201230  1655.4070  1644.5950  1664.2290  1638.1100     0.3073  10815.800000
2    865001.TI   20201229  1650.3360  1686.1620  1686.1620  1639.0530    -1.6263  11763.170000
3    865001.TI   20201228  1677.6190  1682.5670  1689.8980  1667.2110     0.6698  11813.210000
4    865001.TI   20201224  1666.4570  1663.3270  1668.8490  1648.7920     0.6533   6571.630000
..         ...        ...        ...        ...        ...        ...        ...           ...
229  865001.TI   20200108  1315.8190  1313.4520  1323.2140  1312.7090     0.2567  33180.860000
230  865001.TI   20200107  1312.4500  1319.8580  1323.1850  1311.2390    -0.6790  20959.510000
231  865001.TI   20200106  1321.4230  1322.8090  1328.0270  1314.8890    -0.5953  21283.400000
232  865001.TI   20200103  1329.3370  1309.6150  1330.6640  1309.2810     0.6505  28610.530000
233  865001.TI   20200102  1320.7460  1342.6220  1343.1260  1308.6630    -1.1273  26149.740000

"""
from basis import *


class get_ths_daily_all(ts2db_by_period_and_codelist_template):
    table_name = 'hq_ths_daily_all'  # 保存到数据库的库名
    table_name_cn = '同花顺板块指数行情'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.ths_daily  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 3000  # 官方文档单次最大返回量
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_ths_index')  # 必须初始化，需要遍历的列表
        self.params.how_many_codes_onetime = 100  # 一次调用最多获取多少个代码对应的数据
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'],
                                  ['trade_date'],
                                  ['trade_date', 'ts_code']]
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
                                     'avg_price': DECIMAL(25, 4),
                                     'change': DECIMAL(25, 4),
                                     'pct_change': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'turnover_rate': DECIMAL(25, 4),
                                     'total_mv': DECIMAL(25, 4),
                                     'float_mv': DECIMAL(25, 4),
                                     'pe_ttm': DECIMAL(25, 4),
                                     'pb_mrq': DECIMAL(25, 4),
                                     })

    # # 抓取数据函数, 实现单次证券的抓取逻辑即可
    
    def ts2db_get_data(self):
        return self.params.ts_api(**{
            "ts_code": self.params.code,
            "start_date": self.params.str_date,
            "end_date": self.params.end_date,
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
            "avg_price",
            "change",
            "pct_change",
            "vol",
            "turnover_rate",
            "total_mv",
            "float_mv",
            "pe_ttm",
            "pb_mrq"
        ])

if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_ths_daily_all(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
