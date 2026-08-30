"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>

每日涨跌停价格
接口：stk_limit
描述：获取全市场（包含A/B股和基金）每日涨跌停价格，包括涨停价格，跌停价格等，每个交易日8点40左右更新当日股票涨跌停价格。
限量：单次最多提取5800条记录，可循环调取，总量不限制
积分：用户积600积分可调取，单位分钟有流控，积分越高流量越大，请自行提高积分，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码
trade_date	str	N	交易日期
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
ts_code	str	Y	TS股票代码
pre_close	float	N	昨日收盘价
up_limit	float	Y	涨停价
down_limit	float	Y	跌停价

"""
from basis import *


class get_stk_limit(ts2db_by_date_template):
    table_name = 'hq_stk_limit'  # 保存到数据库的库名
    table_name_cn = '每日涨跌停价格'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.stk_limit  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 5800  # 官方文档单次最大返回量
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
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
                                     'pre_close': DECIMAL(25, 4),
                                     'up_limit': DECIMAL(25, 4),
                                     'down_limit': DECIMAL(25, 4)
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250101', end_date=init_currentDate())
    get_stk_limit(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
    """
    SELECT trade_date, count(*) FROM hq_stk_limit hcd group by trade_date order by trade_date DESC  
    """