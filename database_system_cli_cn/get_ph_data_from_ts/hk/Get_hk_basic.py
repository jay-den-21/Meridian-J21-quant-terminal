"""
Created on 2022年3月26日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

港股列表
接口：hk_basic
描述：获取港股列表信息
数量：单次可提取全部在交易的港股列表数据
积分：用户需要至少2000积分才可以调取，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	TS代码
list_status	str	N	上市状态 L上市 D退市 P暂停上市 ，默认L


输出参数

名称	类型	默认显示	描述
ts_code	str	Y
name	str	Y	股票简称
fullname	str	Y	公司全称
enname	str	Y	英文名称
cn_spell	str	Y	拼音
market	str	Y	市场类别
list_status	str	Y	上市状态
list_date	str	Y	上市日期
delist_date	str	Y	退市日期
trade_unit	float	Y	交易单位
isin	str	Y	ISIN代码
curr_type	str	Y	货币代码


接口示例


pro = ts.pro_api()

#获取全部可交易股票基础信息
df = pro.hk_basic()

#获取全部退市股票基础信息
df = pro.hk_basic(list_status='D')


数据示例

       ts_code             name  ...          isin curr_type
0     00001.HK               长和  ...  KYG217651051       HKD
1     00002.HK             中电控股  ...  HK0002007356       HKD
2     00003.HK           香港中华煤气  ...  HK0003000038       HKD
3     00004.HK            九龙仓集团  ...  HK0004000045       HKD
4     00005.HK             汇丰控股  ...  GB0005405286       HKD
5     00006.HK             电能实业  ...  HK0006000050       HKD
6     00007.HK           香港金融集团  ...  BMG4613K1099       HKD
7     00008.HK             电讯盈科  ...  HK0008011667       HKD
8     00009.HK             九号运通  ...  BMG6547Y1057       HKD
9     00010.HK             恒隆集团  ...  HK0010000088       HKD
10    00011.HK             恒生银行  ...  HK0011000095       HKD
11    00012.HK             恒基地产  ...  HK0012000102       HKD
12    00014.HK             希慎兴业  ...  HK0014000126       HKD
13    00015.HK             盈信控股  ...  BMG932121434       HKD
14    00016.HK            新鸿基地产  ...  HK0016000132       HKD
15    00017.HK            新世界发展  ...  HK0017000149       HKD
16    00018.HK           东方报业集团  ...  HK0018000155       HKD
17    00019.HK          太古股份公司A  ...  HK0019000162       HKD
18    00020.HK              会德丰  ...  HK0020000177       HKD
19    00021.HK          大中华地产控股  ...  HK0000132420       HKD
20    00022.HK             茂盛控股  ...  BMG6051D1175       HKD
"""
from basis import *


class get_hk_basic(ts2db_by_limit_template):
    table_name = 'hq_hk_basic'  # 保存到数据库的库名
    table_name_cn = '港股基本信息'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.hk_basic  # 告诉框架本接口对应的tushare的接口函数
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
                                     'cn_spell': NVARCHAR(100),
                                     'market': NVARCHAR(20),
                                     'list_status': NVARCHAR(5),
                                     'list_date': DATE,
                                     'delist_date': DATE,
                                     'trade_unit': DECIMAL(25, 4),
                                     'isin': NVARCHAR(20),
                                     'curr_type': NVARCHAR(3)})


class get_hk_basic_d(ts2db_by_limit_template):
    table_name = 'hq_hk_basic'  # 保存到数据库的库名
    table_name_cn = '港股基本信息_d'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        # self.params.ts_api = self.params.ts_pro.hk_basic  # 告诉框架本接口对应的tushare的接口函数
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # # db_tools(self.params).truncate_table()  # 删除当前表
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
                                     'cn_spell': NVARCHAR(100),
                                     'market': NVARCHAR(20),
                                     'list_status': NVARCHAR(5),
                                     'list_date': DATE,
                                     'delist_date': DATE,
                                     'trade_unit': DECIMAL(25, 4),
                                     'isin': NVARCHAR(20),
                                     'curr_type': NVARCHAR(3)})

    
    def ts2db_get_data(self):
        return self.params.ts_pro.hk_basic(list_status='D',
                                           limit=self.params.one_time_rows_limit,
                                           offset=self.params.offset)


def get_hk_basic_run():
    get_hk_basic().run()
    get_hk_basic_d().run()


if __name__ == '__main__':
    get_hk_basic_run()
