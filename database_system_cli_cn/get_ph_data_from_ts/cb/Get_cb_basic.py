"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

可转债基本信息
接口：cb_basic
描述：获取可转债基本信息
限量：单次最大2000，总量不限制
权限：用户需要至少2000积分才可以调取，但有流量控制，5000积分以上频次相对较高，积分越多权限越大，具体请参阅积分获取办法


输入参数

名称	类型	必选	描述
ts_code	str	N	转债代码
list_date	str	N	上市日期
exchange	str	N	上市地点


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	转债代码
bond_full_name	str	Y	转债名称
bond_short_name	str	Y	转债简称
cb_code	str	Y	转股申报代码
stk_code	str	Y	正股代码
stk_short_name	str	Y	正股简称
maturity	float	Y	发行期限（年）
par	float	Y	面值
issue_price	float	Y	发行价格
issue_size	float	Y	发行总额（元）
remain_size	float	Y	债券余额（元）
value_date	str	Y	起息日期
maturity_date	str	Y	到期日期
rate_type	str	Y	利率类型
coupon_rate	float	Y	票面利率（%）
add_rate	float	Y	补偿利率（%）
pay_per_year	int	Y	年付息次数
list_date	str	Y	上市日期
delist_date	str	Y	摘牌日
exchange	str	Y	上市地点
conv_start_date	str	Y	转股起始日
conv_end_date	str	Y	转股截止日
first_conv_price	float	Y	初始转股价
conv_price	float	Y	最新转股价
rate_clause	str	Y	利率说明
put_clause	str	N	赎回条款
maturity_put_price	str	N	到期赎回价格(含税)
call_clause	str	N	回售条款
reset_clause	str	N	特别向下修正条款
conv_clause	str	N	转股条款
guarantor	str	N	担保人
guarantee_type	str	N	担保方式
issue_rating	str	N	发行信用等级
newest_rating	str	N	最新信用等级
rating_comp	str	N	最新评级机构
"""
from basis import *


class get_cb_basic(ts2db_by_limit_template):
    table_name = 'hq_cb_basic'  # 保存到数据库的库名
    table_name_cn = '可转债基本信息'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.cb_basic  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 2000  # 官方文档单次最大返回量
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'bond_full_name': NVARCHAR(500),
                                     'bond_short_name': NVARCHAR(250),
                                     'cb_code': NVARCHAR(20),
                                     'stk_code': NVARCHAR(20),
                                     'stk_short_name': NVARCHAR(250),
                                     'maturity': DECIMAL(25, 4),
                                     'par': DECIMAL(25, 4),
                                     'issue_price': DECIMAL(25, 4),
                                     'issue_size': DECIMAL(25, 4),
                                     'remain_size': DECIMAL(25, 4),
                                     'value_date': DATE,
                                     'maturity_date': DATE,
                                     'rate_type': NVARCHAR(250),
                                     'coupon_rate': DECIMAL(25, 4),
                                     'add_rate': DECIMAL(25, 4),
                                     'pay_per_year': DECIMAL(25, 4),
                                     'list_date': DATE,
                                     'delist_date': DATE,
                                     'exchange': NVARCHAR(20),
                                     'conv_start_date': DATE,
                                     'conv_end_date': DATE,
                                     'first_conv_price': DECIMAL(25, 4),
                                     'conv_price': DECIMAL(25, 4),
                                     'rate_clause': NVARCHAR(2000)})

    def ts2db_get_data(self):
        return self.params.ts_api(**{
            "ts_code": "",
            "list_date": "",
            "exchange": "",
            "limit": self.params.one_time_rows_limit,
            "offset": self.params.offset
        }, fields=[
            "ts_code",
            "bond_full_name",
            "bond_short_name",
            "cb_code",
            "stk_code",
            "stk_short_name",
            "maturity",
            "par",
            "issue_price",
            "issue_size",
            "remain_size",
            "value_date",
            "maturity_date",
            "rate_type",
            "coupon_rate",
            "add_rate",
            "pay_per_year",
            "list_date",
            "delist_date",
            "exchange",
            "conv_start_date",
            "conv_end_date",
            "conv_stop_date",
            "first_conv_price",
            "conv_price",
            "rate_clause",
            "put_clause",
            "maturity_put_price",
            "call_clause",
            "reset_clause",
            "conv_clause",
            "guarantor",
            "guarantee_type",
            "issue_rating",
            "newest_rating",
            "rating_comp"
        ])


if __name__ == '__main__':
    get_cb_basic().run()
