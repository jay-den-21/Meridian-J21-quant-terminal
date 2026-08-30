"""
Created on 2024年12月12日

@author: Jayden21 <jayden0721@163.com>

每日涨跌停统计
接口：limit_list，可以通过数据工具调试和查看数据。
描述：获取每日涨跌停股票统计，包括封闭时间和打开次数等数据，帮助用户快速定位近期强（弱）势股，以及研究超短线策略。
限量：单次最大1000，总量不限制
积分：用户积2000积分可调取，5000积分以上可高频使用，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期 YYYYMMDD格式，支持单个或多日期输入
ts_code	str	N	股票代码 （支持单个或多个股票输入）
limit_type	str	N	涨跌停类型：U涨停D跌停
start_date	str	N	开始日期 YYYYMMDD格式
end_date	str	N	结束日期 YYYYMMDD格式


输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
ts_code	str	Y	股票代码
name	str	Y	股票名称
close	float	Y	收盘价
pct_chg	float	Y	涨跌幅
amp	float	Y	振幅
fc_ratio	float	Y	封单金额/日成交金额
fl_ratio	float	Y	封单手数/流通股本
fd_amount	float	Y	封单金额
first_time	str	Y	首次涨停时间
last_time	str	Y	最后封板时间
open_times	int	Y	打开次数
strth	float	Y	涨跌停强度
stk_limit	str	Y	D跌停U涨停

"""
from basis import *


class get_stk_limit_list(ts2db_by_date_template):
    table_name = 'hq_stk_limit_list'  # 保存到数据库的库名
    table_name_cn = '股票每日涨跌停统计'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.limit_list  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 1000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'ts_code': NVARCHAR(20),
                                     'name': NVARCHAR(255),
                                     'open': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'close': DECIMAL(25, 4),
                                     'pre_close': DECIMAL(25, 4),
                                     'change': DECIMAL(25, 4),
                                     'pct_chg': DECIMAL(25, 4),
                                     'amp': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'fc_ratio': DECIMAL(25, 4),
                                     'fc_amount': DECIMAL(25, 4),
                                     'first_time': TIME,
                                     'last_time': TIME,
                                     'open_time': DECIMAL(25, 4),
                                     'strth': DECIMAL(25, 4),
                                     'stk_limit': NVARCHAR(2),
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20200101', end_date=init_currentDate())
    get_stk_limit_list(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
