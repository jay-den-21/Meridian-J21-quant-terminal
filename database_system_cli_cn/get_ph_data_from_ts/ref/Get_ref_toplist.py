"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

龙虎榜每日明细
接口：top_list
描述：龙虎榜每日交易明细
数据历史： 2005年至今
限量：单次最大10000
积分：用户需要至少300积分才可以调取，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
trade_date	str	Y	交易日期
ts_code	str	N	股票代码
输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
ts_code	str	Y	TS代码
name	str	Y	名称
close	float	Y	收盘价
pct_change	float	Y	涨跌幅
turnover_rate	float	Y	换手率
amount	float	Y	总成交额
l_sell	float	Y	龙虎榜卖出额
l_buy	float	Y	龙虎榜买入额
l_amount	float	Y	龙虎榜成交额
net_amount	float	Y	龙虎榜净买入额
net_rate	float	Y	龙虎榜净买额占比
amount_rate	float	Y	龙虎榜成交额占比
float_values	float	Y	当日流通市值
reason	str	Y	上榜理由

"""
from basis import *


class get_ref_toplist(ts2db_by_date_template):
    table_name = 'hq_ref_toplist'  # 保存到数据库的库名
    table_name_cn = '龙虎榜每日明细'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.top_list  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 10000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'],
                                  ['trade_date', 'ts_code'],
                                  ['trade_date', 'ts_code', 'reason']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code, reason'

    def ts2db_clean_data(self):
        key_columns = ['trade_date', 'ts_code', 'reason']
        duplicate_rows = self.df.loc[
            self.df.duplicated(subset=key_columns, keep=False)
        ]
        unique_duplicate_rows = duplicate_rows.drop_duplicates()
        if unique_duplicate_rows.duplicated(
            subset=key_columns, keep=False
        ).any():
            raise ValueError(
                'top_list returned conflicting payloads for a declared key'
            )
        self.df.drop_duplicates(inplace=True, ignore_index=True)

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'ts_code': NVARCHAR(20),
                                     'name': NVARCHAR(255),
                                     'close': DECIMAL(25, 4),
                                     'pct_change': DECIMAL(17, 6),
                                     'turnover_rate': DECIMAL(17, 6),
                                     'amount': DECIMAL(25, 4),
                                     'l_sell': DECIMAL(25, 4),
                                     'l_buy': DECIMAL(25, 4),
                                     'l_amount': DECIMAL(25, 4),
                                     'net_amount': DECIMAL(25, 4),
                                     'net_rate': DECIMAL(17, 6),
                                     'amount_rate': DECIMAL(17, 6),
                                     'float_values': DECIMAL(25, 4),
                                     'reason': NVARCHAR(255), })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20240101', end_date=init_currentDate())
    get_ref_toplist(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
