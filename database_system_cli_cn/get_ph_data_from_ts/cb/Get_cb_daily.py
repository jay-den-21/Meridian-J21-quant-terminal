"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

可转债行情
接口：cb_daily
描述：获取可转债行情
限量：单次最大2000条，可多次提取，总量不限制
积分：用户需要至少2000积分才可以调取，5000积分以上频次相对较高，积分越多权限越大，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	TS代码
trade_date	str	N	交易日期(YYYYMMDD格式，下同)
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	转债代码
trade_date	str	Y	交易日期
pre_close	float	Y	昨收盘价(元)
open	float	Y	开盘价(元)
high	float	Y	最高价(元)
low	float	Y	最低价(元)
close	float	Y	收盘价(元)
change	float	Y	涨跌(元)
pct_chg	float	Y	涨跌幅(%)
vol	float	Y	成交量(手)
amount	float	Y	成交金额(万元)
bond_value	float	N	纯债价值
bond_over_rate	float	N	纯债溢价率(%)
cb_value	float	N	转股价值
cb_over_rate	float	N	转股溢价率(%)
"""
from basis import *


class get_cb_daily(ts2db_by_date_template):
    table_name = 'hq_cb_daily'  # 保存到数据库的库名
    table_name_cn = '可转债行情'  # 接口名称c

    def ts2db_init(self):
        # self.params.auto_detect__break_point_type = 0
        self.params.ts_api = self.params.ts_pro.cb_daily  # 告诉框架本接口对应的tushare的接口函数
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
            "ts_code": "",
            "trade_date": "",
            "start_date": self.params.idate,
            "end_date": self.params.idate,
            "limit": self.params.one_time_rows_limit,
            "offset": self.params.offset
        }, fields=[
            "ts_code",
            "trade_date",
            "pre_close",
            "open",
            "high",
            "low",
            "close",
            "change",
            "pct_chg",
            "vol",
            "amount",
            "bond_value",
            "bond_over_rate",
            "cb_value",
            "cb_over_rate"
        ])


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250101', end_date=init_currentDate())
    # params = _params(str_date='20241021', end_date='20241021')
#     get_cb_daily(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
    """
    SELECT trade_date, count(*) FROM hq_cb_daily hcd group by trade_date order by trade_date DESC 
    """


