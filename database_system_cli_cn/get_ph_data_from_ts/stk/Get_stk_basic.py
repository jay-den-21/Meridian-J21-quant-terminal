"""
Created on 2021年7月17日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

股票列表
接口：stock_basic
限量：每次最多返回6000行数据。
"""
from basis import *


class get_stk_basic(ts2db_by_limit_template):
    # 定义该类的属性，这里只用定义两个框架用到的属性，定义后，框架会自动将改属性放入params参数包中
    table_name = 'hq_stk_basic'  # 定义表名
    table_name_cn = '股票基本信息'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        # self.params.auto_detect__break_point_type = 0
        self.params.ts_api = self.params.ts_pro.stock_basic  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 6000  # 官方文档单次最大返回量
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # db_tools(self.params).truncate_table()
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'idx': NVARCHAR(20),
                                     'ts_code': NVARCHAR(20),
                                     'symbol': NVARCHAR(20),
                                     'name': NVARCHAR(50),
                                     'area': NVARCHAR(50),
                                     'industry': NVARCHAR(50),
                                     'market': NVARCHAR(20),
                                     'list_date': DATE})


if __name__ == '__main__':
    get_stk_basic().run()
