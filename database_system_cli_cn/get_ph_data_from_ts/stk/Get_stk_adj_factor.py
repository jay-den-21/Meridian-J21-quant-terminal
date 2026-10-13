"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

复权因子
接口：adj_factor，可以通过数据工具调试和查看数据。
更新时间：早上9点30分
描述：获取股票复权因子，可提取单只股票全部历史复权因子，也可以提取单日全部股票的复权因子。

输入参数

名称	类型	必选	描述
ts_code	str	Y	股票代码
trade_date	str	N	交易日期(YYYYMMDD，下同)
start_date	str	N	开始日期
end_date	str	N	结束日期
注：日期都填YYYYMMDD格式，比如20181010

输出参数

名称	类型	描述
ts_code	str	股票代码
trade_date	str	交易日期
adj_factor	float	复权因子
"""
from basis import *


class get_stk_adj_factor(ts2db_by_date_template):
    table_name = 'hq_stk_adj_factor'  # 保存到数据库的库名
    table_name_cn = '股票复权因子'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.adj_factor  # 告诉框架本接口对应的tushare的接口函数
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE,
                                     'adj_factor': DECIMAL(25, 4)})


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_stk_adj_factor(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
    """
    select trade_date , count(*) from hq_stk_adj_factor group by trade_date  order by trade_date desc;
    """
