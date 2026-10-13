"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

大盘指数每日指标
接口：index_dailybasic，可以通过数据工具调试和查看数据。
描述：目前只提供上证综指，深证成指，上证50，中证500，中小板指，创业板指的每日指标数据
数据来源：Tushare社区统计计算
数据历史：从2004年1月开始提供
数据权限：用户需要至少400积分才可以调取，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期 （格式：YYYYMMDD，比如20181018，下同）
ts_code	str	N	TS代码
start_date	str	N	开始日期
end_date	str	N	结束日期
注：trade_date，ts_code 至少要输入一个参数，单次限量3000条（即，单一指数单次可提取超过12年历史），总量不限制。

输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS代码
trade_date	str	Y	交易日期
total_mv	float	Y	当日总市值（元）
float_mv	float	Y	当日流通市值（元）
total_share	float	Y	当日总股本（股）
float_share	float	Y	当日流通股本（股）
free_share	float	Y	当日自由流通股本（股）
turnover_rate	float	Y	换手率
turnover_rate_f	float	Y	换手率(基于自由流通股本)
pe	float	Y	市盈率
pe_ttm	float	Y	市盈率TTM
pb	float	Y	市净率

"""
from basis import *


class get_idx_daily_basic(ts2db_by_date_template):
    table_name = 'hq_idx_daily_basic'  # 保存到数据库的库名
    table_name_cn = '股票每日指标'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.index_dailybasic  # 告诉框架本接口对应的tushare的接口函数
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
                                     'trade_date': NVARCHAR(20),
                                     'total_mv': DECIMAL(25, 4),
                                     'float_mv': DECIMAL(25, 4),
                                     'total_share': DECIMAL(25, 4),
                                     'float_share': DECIMAL(25, 4),
                                     'free_share': DECIMAL(25, 4),
                                     'turnover_rate': DECIMAL(25, 4),
                                     'turnover_rate_f': DECIMAL(25, 4),
                                     'pe': DECIMAL(25, 4),
                                     'pe_ttm': DECIMAL(25, 4),
                                     'pb': DECIMAL(25, 4)})


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_idx_daily_basic(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
