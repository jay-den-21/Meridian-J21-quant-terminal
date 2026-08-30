"""
Created on 2025年6月10日

@author: Jayden21 <jayden0721@163.com>

通达信板块成分
接口：tdx_member
描述：获取通达信各板块成分股信息
限量：单次最大3000条数据，可以根据日期和板块代码循环提取
权限：用户积累6000积分可调取，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	板块代码：xxxxxx.TDX
trade_date	str	N	交易日期：格式YYYYMMDD


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	板块代码
trade_date	str	Y	交易日期
con_code	str	Y	成分股票代码
con_name	str	Y	成分股票名称
"""
from basis import *


class get_stk_tdx_member(ts2db_by_date_template):
    table_name = 'hq_stk_tdx_member'  # 保存到数据库的库名
    table_name_cn = '通达信板块成分'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.tdx_member  # 告诉框架本接口对应的tushare的接口函数
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        self.params.one_time_rows_limit = 3000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code, con_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'ts_code': NVARCHAR(20),
                                     'con_code': NVARCHAR(20),
                                     'con_name': NVARCHAR(50),
                                     'idx_type': NVARCHAR(20),
                                     'total_mv': NVARCHAR(50),
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250328', end_date=init_currentDate())
    get_stk_tdx_member(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
