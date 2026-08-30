"""
Created on 2022年3月26日

@author: Jayden21 <jayden0721@163.com>

美股交易日历
接口：us_tradecal
描述：获取美股交易日历信息
限量：单次最大6000，可根据日期阶段获取



输入参数

名称	类型	必选	描述	示例
start_date	str	N	开始日期	20200101
end_date	str	N	结束日期	20200701
is_open	str	N	是否交易	0：休市 、1：交易


输出参数

名称	类型	默认显示	描述
cal_date	str	Y	日历日期
is_open	int	Y	是否交易 '0'休市 '1'交易
pretrade_date	str	Y	上一个交易日


接口示例


pro = ts.pro_api()

df = pro.us_tradecal(start_date='20200101', end_date='20200701')



数据示例

     cal_date  is_open pretrade_date
0    20200701        1      20200630
1    20200630        1      20200629
2    20200629        1      20200626
3    20200628        0      20200625
4    20200627        0      20200625
..        ...      ...           ...
178  20200105        0      20200102
179  20200104        0      20200102
180  20200103        1      20200102
181  20200102        1      20191231
182  20200101        0      20191230
"""
from basis import *


class get_us_tradeCal(ts2db_by_limit_template):
    table_name = 'hq_us_trade_cal'  # 保存到数据库的库名
    table_name_cn = '美股交易日历'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.us_tradecal  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 6000  # 官方文档单次最大返回量
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['cal_date']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'cal_date'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'cal_date': DATE,
                                     'is_open': NVARCHAR(1),
                                     'pretrade_date': DATE})


if __name__ == '__main__':
    get_us_tradeCal().run()
