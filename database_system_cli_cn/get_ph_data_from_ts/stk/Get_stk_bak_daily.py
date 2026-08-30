"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

备用行情
接口：bak_daily
描述：获取备用行情，包括特定的行情指标
限量：单次最大7000行数据，可以根据日期参数循环获取，正式权限需要5000积分。

输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码
trade_date	str	N	交易日期
start_date	str	N	开始日期
end_date	str	N	结束日期
offset	str	N	开始行数
stk_limit	str	N	最大行数
输出参数

名称	类型	默认显示	描述
ts_code	str	Y	股票代码
trade_date	str	Y	交易日期
name	str	Y	股票名称
pct_change	float	Y	涨跌幅
close	float	Y	收盘价
change	float	Y	涨跌额
open	float	Y	开盘价
high	float	Y	最高价
low	float	Y	最低价
pre_close	float	Y	昨收价
vol_ratio	float	Y	量比
turn_over	float	Y	换手率
swing	float	Y	振幅
vol	float	Y	成交量
amount	float	Y	成交额
selling	float	Y	内盘（主动卖，手）
buying	float	Y	外盘（主动买， 手）
total_share	float	Y	总股本(亿)
float_share	float	Y	流通股本(亿)
pe	float	Y	市盈(动)
industry	str	Y	所属行业
area	str	Y	所属地域
float_mv	float	Y	流通市值
total_mv	float	Y	总市值
avg_price	float	Y	平均价
strength	float	Y	强弱度(%)
activity	float	Y	活跃度(%)
avg_turnover	float	Y	笔换手
attack	float	Y	攻击波(%)
interval_3	float	Y	近3月涨幅
interval_6	float	Y	近6月涨幅
"""
from basis import *


class get_stk_bak_daily(ts2db_by_period_template):
    table_name = 'hq_stk_bak_daily'  # 保存到数据库的库名
    table_name_cn = '备用行情'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.bak_daily  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 7000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'name': NVARCHAR(50),
                                     'industry': NVARCHAR(200),
                                     'area': NVARCHAR(50),
                                     'interval_3': DECIMAL(25, 4),
                                     'interval_6': DECIMAL(25, 4),
                                     'trade_date': DATE,
                                     'pre_close': DECIMAL(25, 4),
                                     'open': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'close': DECIMAL(25, 4),
                                     'change': DECIMAL(25, 4),
                                     'pct_chg': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'bond_value': DECIMAL(25, 4),
                                     'bond_over_rate': DECIMAL(25, 4),
                                     'cb_value': DECIMAL(25, 4),
                                     'cb_over_rate': DECIMAL(25, 4)
                                     })

    # 抓取数据函数, 实现单次证券的抓取逻辑即可
    
    def ts2db_get_data(self):
        return self.params.ts_api(**{
            "trade_date": "",
            "start_date": self.params.str_date,
            "end_date": self.params.end_date,
            "limit": self.params.one_time_rows_limit,
            "offset": self.params.offset
        }, fields=[
            "ts_code",
            "trade_date",
            "name",
            "pct_change",
            "close",
            "change",
            "open",
            "high",
            "low",
            "pre_close",
            "vol_ratio",
            "turn_over",
            "swing",
            "vol",
            "amount",
            "selling",
            "buying",
            "total_share",
            "float_share",
            "pe",
            "industry",
            "area",
            "float_mv",
            "total_mv",
            "avg_price",
            "strength",
            "activity",
            "avg_turnover",
            "attack",
            "interval_3",
            "interval_6"
        ])


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_stk_bak_daily(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
