"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>

期权合约信息
接口：opt_basic
描述：获取期权合约信息
积分：用户需要至少600积分才可以调取，但有流量控制，请自行提高积分，积分越多权限越大，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	TS期权代码
exchange	str	N	交易所代码 （包括上交所SSE等交易所）
call_put	str	N	期权类型


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS代码
exchange	str	Y	交易市场
name	str	Y	合约名称
per_unit	str	Y	合约单位
opt_code	str	Y	标准合约代码
opt_type	str	Y	合约类型
call_put	str	Y	期权类型
exercise_type	str	Y	行权方式
exercise_price	float	Y	行权价格
s_month	str	Y	结算月
maturity_date	str	Y	到期日
list_price	float	Y	挂牌基准价
list_date	str	Y	开始交易日期
delist_date	str	Y	最后交易日期
last_edate	str	Y	最后行权日期
last_ddate	str	Y	最后交割日期
quote_unit	str	Y	报价单位
min_price_chg	str	Y	最小价格波幅


接口示例


pro = ts.pro_api('your token')

df = pro.opt_basic(exchange='DCE', fields='ts_code,name,exercise_type,list_date,delist_date')


数据示例

          ts_code            name             exercise_type list_date delist_date
0    M1707-C-2400.DCE  豆粕期权1707认购2400            美式  20170605    20170607
1    M1707-P-2400.DCE  豆粕期权1707认沽2400            美式  20170605    20170607
2    M1803-P-2550.DCE  豆粕期权1803认沽2550            美式  20170407    20180207
3    M1707-C-2500.DCE  豆粕期权1707认购2500            美式  20170410    20170607
4    M1707-P-2500.DCE  豆粕期权1707认沽2500            美式  20170410    20170607
5    M1803-C-2550.DCE  豆粕期权1803认购2550            美式  20170407    20180207
6    M1808-C-3550.DCE  豆粕期权1808认购3550            美式  20180409    20180706
7    M1808-P-3550.DCE  豆粕期权1808认沽3550            美式  20180409    20180706
8    M1809-C-3550.DCE  豆粕期权1809认购3550            美式  20180409    20180807
9    M1809-P-3550.DCE  豆粕期权1809认沽3550            美式  20180409    20180807
10   M1811-C-3550.DCE  豆粕期权1811认购3550            美式  20180409    20181012
11   M1811-P-3550.DCE  豆粕期权1811认沽3550            美式  20180409    20181012
12   M1812-C-3500.DCE  豆粕期权1812认购3500            美式  20180409    20181107
13   M1812-C-3550.DCE  豆粕期权1812认购3550            美式  20180409    20181107
14   M1711-P-2450.DCE  豆粕期权1711认沽2450            美式  20170601    20171013
15   M1712-C-2450.DCE  豆粕期权1712认购2450            美式  20170601    20171107
16   M1712-P-2450.DCE  豆粕期权1712认沽2450            美式  20170601    20171107
17   M1801-C-2450.DCE  豆粕期权1801认购2450            美式  20170601    20171207
18   M1801-P-2450.DCE  豆粕期权1801认沽2450            美式  20170601    20171207
19   M1803-C-2450.DCE  豆粕期权1803认购2450            美式  20170601    20180207
20   M1803-P-2450.DCE  豆粕期权1803认沽2450            美式  20170601    20180207


"""
from basis import *


class get_opt_basic(ts2db_by_limit_template):
    table_name = 'hq_opt_basic'  # 保存到数据库的库名
    table_name_cn = '期权合约信息'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.opt_basic  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 12000
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code']]
        # -------------------------------------------定义数据整理参数-------------- ----------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'ts_code': NVARCHAR(50),
                                     'exchange': NVARCHAR(20),
                                     'name': NVARCHAR(200),
                                     'per_unit': DECIMAL(25, 4),
                                     'opt_code': NVARCHAR(50),
                                     'opt_type': NVARCHAR(20),
                                     'call_put': NVARCHAR(2),
                                     'exercise_type': NVARCHAR(20),
                                     'exercise_price': DECIMAL(25, 4),
                                     's_month': NVARCHAR(20),
                                     'maturity_date': DATE,
                                     'list_price': DECIMAL(25, 4),
                                     'list_date': DATE,
                                     'delist_date': DATE,
                                     'last_edate': DATE,
                                     'last_ddate': DATE,
                                     'quote_unit': NVARCHAR(20),
                                     'min_price_chg': DECIMAL(25, 4)})


if __name__ == '__main__':
    get_opt_basic().run()
