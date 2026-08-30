"""
Created on 2025年6月10日

@author: Jayden21 <jayden0721@163.com>

通达信板块信息
接口：tdx_index
描述：获取通达信板块基础信息，包括概念板块、行业、风格、地域等
限量：单次最大1000条数据，可根据日期参数循环提取
权限：用户积累6000积分可调取，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	板块代码：xxxxxx.TDX
trade_date	str	N	交易日期(格式：YYYYMMDD）
idx_type	str	N	板块类型：概念板块、行业板块、风格板块、地区板块


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	板块代码
trade_date	str	Y	交易日期
name	str	Y	板块名称
idx_type	str	Y	板块类型
idx_count	int	Y	成分个数
total_share	float	Y	总股本(亿)
float_share	float	Y	流通股(亿)
total_mv	float	Y	总市值(亿)
float_mv	float	Y	流通市值(亿)
"""
from basis import *


class get_stk_tdx_index(ts2db_by_date_template):
    table_name = 'hq_stk_tdx_index'  # 保存到数据库的库名
    table_name_cn = '通达信板块信息'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.tdx_index  # 告诉框架本接口对应的tushare的接口函数
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        self.params.one_time_rows_limit = 1000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'ts_code': NVARCHAR(20),
                                     'name': NVARCHAR(50),
                                     'idx_type': NVARCHAR(20),
                                     'idx_count': DECIMAL(25, 4),
                                     'total_share': DECIMAL(25, 4),
                                     'float_share': DECIMAL(25, 4),
                                     'total_mv': DECIMAL(25, 4),
                                     'float_mv': DECIMAL(25, 4)
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250328', end_date=init_currentDate())
    get_stk_tdx_index(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
