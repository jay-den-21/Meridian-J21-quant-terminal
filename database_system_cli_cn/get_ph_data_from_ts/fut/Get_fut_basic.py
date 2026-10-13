"""
Created on 2022年3月27日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

期货合约信息表
接口：fut_basic
描述：获取期货合约列表数据
限量：单次最大10000
积分：用户需要至少200积分才可以调取，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
exchange	str	Y	交易所代码 CFFEX-中金所 DCE-大商所 CZCE-郑商所 SHFE-上期所 INE-上海国际能源交易中心
fut_type	str	N	合约类型 (1 普通合约 2主力与连续合约 默认取全部)
输出参数

名称	类型	默认显示	描述
ts_code	str	Y	合约代码
symbol	str	Y	交易标识
exchange	str	Y	交易市场
name	str	Y	中文简称
fut_code	str	Y	合约产品代码
multiplier	float	Y	合约乘数
trade_unit	str	Y	交易计量单位
per_unit	float	Y	交易单位(每手)
quote_unit	str	Y	报价单位
quote_unit_desc	str	Y	最小报价单位说明
d_mode_desc	str	Y	交割方式说明
list_date	str	Y	上市日期
delist_date	str	Y	最后交易日期
d_month	str	Y	交割月份
last_ddate	str	Y	最后交割日
trade_time_desc	str	N	交易时间说明
接口示例


pro = ts.pro_api('your token')

df = pro.fut_basic(exchange='DCE', fut_type='1', fields='ts_code,symbol,name,list_date,delist_date')
数据示例

        ts_code  symbol      name   list_date    delist_date
0      P0805.DCE   P0805   棕榈油0805  20071029    20080516
1      P0806.DCE   P0806   棕榈油0806  20071029    20080616
2      P0807.DCE   P0807   棕榈油0807  20071029    20080714
3      P0808.DCE   P0808   棕榈油0808  20071029    20080814
4      P0811.DCE   P0811   棕榈油0811  20071115    20081114
5      P0812.DCE   P0812   棕榈油0812  20071217    20081212
6      P0901.DCE   P0901   棕榈油0901  20080116    20090116
7      P0903.DCE   P0903   棕榈油0903  20080317    20090313
8      P0906.DCE   P0906   棕榈油0906  20080617    20090612
9      P0908.DCE   P0908   棕榈油0908  20080815    20090814
10     P0911.DCE   P0911   棕榈油0911  20081117    20091113
11     P1001.DCE   P1001   棕榈油1001  20090119    20100115
12     P1002.DCE   P1002   棕榈油1002  20090216    20100212
13     P1003.DCE   P1003   棕榈油1003  20090316    20100312
14     P1004.DCE   P1004   棕榈油1004  20090416    20100415
15     Y0607.DCE   Y0607    豆油0607  20060109    20060714
16     Y0611.DCE   Y0611    豆油0611  20060118    20061114
17     Y0612.DCE   Y0612    豆油0612  20060315    20061214
18     Y0701.DCE   Y0701    豆油0701  20060315    20070117
19     Y0708.DCE   Y0708    豆油0708  20060815    20070814
20     Y0709.DCE   Y0709    豆油0709  20060915    20070914
"""
from basis import *


class get_fut_basic(ts2db_by_limit_template):
    table_name = 'hq_fut_basic'  # 保存到数据库的库名
    table_name_cn = '期货合约信息表'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.auto_detect__break_point_type = 0
        self.params.ts_api = self.params.ts_pro.fut_basic  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 10000  # 官方文档单次最大返回量
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # db_tools(self.params).drop_table()  # 删除当前表
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'symbol': NVARCHAR(20),
                                     'exchange': NVARCHAR(20),
                                     'name': NVARCHAR(200),
                                     'fut_code': NVARCHAR(20),
                                     'multiplier': DECIMAL(25, 4),
                                     'trade_unit': NVARCHAR(20),
                                     'per_unit': DECIMAL(25, 4),
                                     'quote_unit': NVARCHAR(50),
                                     'quote_unit_desc': NVARCHAR(50),
                                     'd_mode_desc': NVARCHAR(50),
                                     'list_date': DATE,
                                     'delist_date': DATE,
                                     'd_month': NVARCHAR(20),
                                     'last_ddate': DATE})

    def ts2db_get_data(self):
        return self.params.ts_api(
            exchange=self.params.exchange,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    def _run(self):
        missing = object()
        previous_exchange = getattr(self.params, 'exchange', missing)
        result = 0
        try:
            for exchange in ('DCE', 'CFFEX', 'CZCE', 'SHFE', 'INE', 'GFEX'):
                self.params.exchange = exchange
                result, _ = self._run_paginated()
            return result
        finally:
            if previous_exchange is missing:
                delattr(self.params, 'exchange')
            else:
                self.params.exchange = previous_exchange


if __name__ == '__main__':
    get_fut_basic().run()
