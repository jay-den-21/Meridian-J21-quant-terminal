"""
Created on 2022年3月26日

@author: Jayden21 <jayden0721@163.com>

美股列表
接口：us_basic
描述：获取美股列表信息
限量：单次最大6000，可分页提取
积分：120积分可以试用，5000积分有正式权限



输入参数

名称	类型	必选	描述	示例
ts_code	str	N	股票代码	AAPL（苹果）
classify	str	N	股票分类	ADR/GDR/EQ
offset	str	N	开始行数	1：第一行
stk_limit	str	N	每页最大行数	500：每页500行


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	美股代码
name	str	Y	中文名称
enname	str	N	英文名称
classify	str	Y	分类ADR/GDR/EQ
list_date	str	Y	上市日期
delist_date	str	Y	退市日期


接口示例


pro = ts.pro_api()

#获取默认美国股票基础信息，单次6000行
df = pro.us_basic()



数据示例

     ts_code  name classify list_date delist_date
0       ONCY  None      EQT  20011005        None
1       SCCO  None      EQT  19950124        None
2      KAOCF  None      EQT  19740319        None
3      BOIRF  None      EQT  19880628        None
4      SDXOF  None      EQT  19830304        None
...      ...   ...      ...       ...         ...
5995   ESESQ  None      EQT  20031014        None
5996    TRKX  None      EQT  20000718        None
5997   ELAMF  None      EQT  19960320        None
5998    CZNB  None      EQT  20120724        None
5999   CRRSQ  None      EQT  20010619        None

"""
import datetime

from basis import *


class get_us_basic(ts2db_by_limit_template):
    table_name = 'hq_us_basic'  # 保存到数据库的库名
    table_name_cn = '美股基本信息'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.us_basic  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 6000  # 官方文档单次最大返回量
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
                                     'name': NVARCHAR(250),
                                     'fullname': NVARCHAR(500),
                                     'enname': NVARCHAR(500),
                                     'list_status': NVARCHAR(5),
                                     'list_date': DATE,
                                     'delist_date': DATE,
                                     })

    def ts2db_clean_data(self):
        usable_code = (
            self.df['ts_code'].notna()
            & self.df['ts_code'].astype(str).str.strip().ne('')
        )
        self.df = self.df.loc[usable_code].copy()
        self.df['delist_date'] = datetime.datetime(9999, 12, 31)  # ts 这一列有问题，直接清掉

if __name__ == '__main__':
    get_us_basic().run()
