"""
Created on 2021年12月5日

@author: Jayden21 <jayden0721@163.com>

外汇日线行情
接口：fx_daily
描述：获取外汇日线行情
限量：单次最大提取1000行记录，可多次提取，总量不限制
积分：用户需要至少2000积分才可以调取，但有流量控制，5000积分以上频次相对较高，积分越多权限越大，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	TS代码
trade_date	str	N	交易日期（GMT，日期是格林尼治时间，比北京时间晚一天）
start_date	str	N	开始日期（GMT）
end_date	str	N	结束日期（GMT）
exchange	str	N	交易商，目前只有FXCM


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	外汇代码
trade_date	str	Y	交易日期
bid_open	float	Y	买入开盘价
bid_close	float	Y	买入收盘价
bid_high	float	Y	买入最高价
bid_low	float	Y	买入最低价
ask_open	float	Y	卖出开盘价
ask_close	float	Y	卖出收盘价
ask_high	float	Y	卖出最高价
ask_low	float	Y	卖出最低价
tick_qty	int	Y	报价笔数
exchange	str	N	交易商


接口示例


pro = ts.pro_api()


#获取美元人民币交易对的日线行情
df = pro.fx_daily(ts_code='USDCNH.FXCM', start_date='20190101', end_date='20190524')
"""
from basis import *


class get_fx_daily(ts2db_by_period_template):
    table_name = 'hq_fx_daily'  # 保存到数据库的库名
    table_name_cn = '外汇日线行情'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.fx_daily  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 1000  # 官方文档单次最大返回量
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
                                     'bid_open': DECIMAL(25, 4),
                                     'bid_close': DECIMAL(25, 4),
                                     'bid_high': DECIMAL(25, 4),
                                     'bid_low': DECIMAL(25, 4),
                                     'ask_open': DECIMAL(25, 4),
                                     'ask_close': DECIMAL(25, 4),
                                     'ask_high': DECIMAL(25, 4),
                                     'ask_low': DECIMAL(25, 4),
                                     'tick_qty': DECIMAL(25, 4),
                                     'exchange': NVARCHAR(100)
                                     })

    def ts2db_get_data(self):
        return self.params.ts_api(
            ts_code=self.params.code,
            start_date=self.params.str_date,
            end_date=self.params.end_date,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_fx_daily(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
