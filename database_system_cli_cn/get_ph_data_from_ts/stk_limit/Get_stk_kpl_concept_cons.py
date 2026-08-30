"""
Created on 2024年12月12日

@author: Jayden21 <jayden0721@163.com>

开盘啦题材成分
接口：kpl_concept_cons
描述：获取开盘啦概念题材的成分股
限量：单次最大3000条，可根据代码和日期循环获取全部数据
积分：5000积分可提取数据，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期（YYYYMMDD格式）
ts_code	str	N	题材代码（xxxxxx.KP格式）


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	题材ID
name	str	Y	题材名称
cons_name	str	Y	股票名称
cons_code	str	Y	股票代码
trade_date	str	Y	交易日期
desc	str	Y	描述
hot_num	None	Y	人气值


接口用法


pro = ts.pro_api()

df = pro.kpl_concept_cons(trade_date='20241014')


数据样例

        ts_code      name     ts_name cons_code trade_date
0     000111.KP  化债概念    信达地产  600657.SH   20241014
1     000111.KP  化债概念    银宝山新  002786.SZ   20241014
2     000111.KP  化债概念    摩恩电气  002451.SZ   20241014
3     000111.KP  化债概念    光大嘉宝  600622.SH   20241014
4     000111.KP  化债概念    海德股份  000567.SZ   20241014
...         ...   ...     ...        ...        ...
2995  000229.KP    电力    特变电工  600089.SH   20241014
2996  000229.KP    电力    中国西电  601179.SH   20241014
2997  000229.KP    电力    金盘科技  688676.SH   20241014
2998  000229.KP    电力    思源电气  002028.SZ   20241014
2999  000229.KP    电力    明阳电气  301291.SZ   20241014
"""
from basis import *


class get_stk_kpl_concept_cons(ts2db_by_date_template):
    table_name = 'hq_stk_kpl_concept_cons'  # 保存到数据库的库名
    table_name_cn = '开盘啦题材成分'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.kpl_concept_cons  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 3000  # 官方文档单次最大返回量
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        # self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_stk_kpl_concept')  # 必须初始化，需要遍历的列表
        # self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['con_code'], ['trade_date', 'con_code', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, con_code, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'ts_code': NVARCHAR(20),
                                     'name': NVARCHAR(200),
                                     'con_name': NVARCHAR(50),
                                     'con_code': NVARCHAR(50),
                                     'desc': NVARCHAR(500),
                                     'hot_num': DECIMAL(25, 4),
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250101', end_date=init_currentDate())
    get_stk_kpl_concept_cons(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
    """
    select trade_date, count(*) from hq_stk_kpl_concept_cons group by trade_date order by trade_date desc
    """
