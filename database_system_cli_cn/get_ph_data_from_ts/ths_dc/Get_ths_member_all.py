"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

同花顺概念板块成分
接口：ths_member
描述：获取同花顺概念板块成分列表注：数据版权归属同花顺，如做商业用途，请主动联系同花顺。
限量：用户积累5000积分可调取，可按概念板块代码循环提取所有成分



输入参数

名称	类型	必选	描述
ts_code	str	N	板块指数代码


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	指数代码
code	str	Y	股票代码
name	str	Y	股票名称
weight	float	N	权重(暂无)
in_date	str	N	纳入日期(暂无)
out_date	str	N	剔除日期(暂无)
is_new	str	N	是否最新Y是N否


接口示例


pro = ts.pro_api()

df = pro.ths_member(ts_code='885800.TI')


数据样例

  ts_code         code     name
0   885800.TI  000016.SZ  深康佳A
1   885800.TI  000049.SZ  德赛电池
2   885800.TI  002008.SZ  大族激光
3   885800.TI  002036.SZ  联创电子
4   885800.TI  002055.SZ  得润电子
..        ...        ...   ...
87  885800.TI  688127.SH  蓝特光学
88  885800.TI  688157.SH  松井股份
89  885800.TI  688286.SH  敏芯股份
90  885800.TI  688312.SH  燕麦科技
91  885800.TI  688386.SH  泛亚微透

[92 rows x 3 columns]

"""
from basis import *


class get_ths_member_all(ts2db_by_period_and_codelist_template):
    table_name = 'hq_ths_member_all'  # 保存到数据库的库名
    table_name_cn = '同花顺概念板块成分'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.ths_member  # 告诉框架本接口对应的tushare的接口函数
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_ths_index')  # 必须初始化，需要遍历的列表
        self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'],
                                  ['con_code'],
                                  ['ts_code', 'con_code'],
                                  ['in_date']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code, con_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'con_code': NVARCHAR(20),
                                     'con_name': NVARCHAR(200),
                                     'weight': DECIMAL(25, 4),
                                     'in_date': DATE,
                                     'out_date': DATE,
                                     'is_new': NVARCHAR(20)
                                })

    # 抓取数据函数, 实现单次证券的抓取逻辑即可
    
    def ts2db_get_data(self):
        return self.params.ts_api(
            ts_code=self.params.code,
            con_code="",
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
            fields=[
                "ts_code",
                "con_code",
                "con_name",
                "weight",
                "in_date",
                "out_date",
                "is_new",
            ],
        )



if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_ths_member_all(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
