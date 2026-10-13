"""
Created on 2022年3月26日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

中央结算系统持股明细
接口：ccass_hold_detail
描述：获取中央结算系统机构席位持股明细，数据覆盖全历史
限量：单次最大返回6000条数据，可以循环或分页提取
积分：用户积5000积分可调取



输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码 (e.g. 605009.SH)
hk_code	str	N	港交所代码 （e.g. 95009）
trade_date	str	N	交易日期
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
ts_code	str	Y	股票代号
name	str	Y	股票名称
col_participant_id	str	Y	参与者编号
col_participant_name	str	Y	机构名称
col_shareholding	str	Y	持股量(股)
col_shareholding_percent	str	Y	占已发行股份/权证/单位百分比(%)


接口用法


pro = ts.pro_api()

df = pro.ccass_hold_detail(ts_code='00960.HK', trade_date='20211101', fields='trade_date,ts_code,col_participant_id,col_participant_name,col_shareholding')
数据样例

    trade_date   ts_code col_participant_id       col_participant_name         col_shareholding
0     20211101  00960.HK             B01777         大和资本市场香港有限公司             3000
1     20211101  00960.HK             B01977             中财证券有限公司             3000
2     20211101  00960.HK             B02068             勤丰证券有限公司             3000
3     20211101  00960.HK             B01413       京华山一国际(香港)有限公司             2500
4     20211101  00960.HK             B02120           利弗莫尔证券有限公司             2500
..         ...       ...                ...                  ...              ...
164   20211101  00960.HK             B01459         奕丰证券(香港)有限公司             3000
165   20211101  00960.HK             B01508       西证(香港)证券经纪有限公司             3000
166   20211101  00960.HK             B01511             达利证券有限公司             3000
167   20211101  00960.HK             B01657         日盛嘉富证券国际有限公司             3000
168   20211101  00960.HK             B01712             华生证券有限公司             3000
"""
from basis import *


class get_hk_ccass_hold_detail(ts2db_by_date_template):
    table_name = 'hq_hk_ccass_hold_detail'  # 保存到数据库的库名
    table_name_cn = '中央结算系统持股明细'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.ccass_hold_detail  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 6000  # 官方文档单次最大返回量
        self.params.market = 'HK'  # 告诉框架该接口为港股接口，将使用港股工作日历
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        # self.params.codelist = init_data.init_codeList(self.params.db_engine, self.params.list_type)  # 必须初始化，需要遍历的列表
        # self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code, col_participant_id'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE,
                                     'name': NVARCHAR(200),
                                     'col_participant_id': NVARCHAR(50),
                                     'col_participant_name': NVARCHAR(500),
                                     'col_shareholding': NVARCHAR(50),
                                     'col_shareholding_percent': NVARCHAR(50)})


def get_hk_ccass_hold_detail_run(params):
    get_hk_ccass_hold_detail(params).run()


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20180101', end_date=init_currentDate())
    get_hk_ccass_hold_detail_run(params)

    # end_str = input("加载完毕，请复核是否正确执行！")
