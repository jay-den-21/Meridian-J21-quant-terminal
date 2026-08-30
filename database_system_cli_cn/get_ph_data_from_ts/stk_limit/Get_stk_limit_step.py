"""
Created on 2024年12月12日

@author: Jayden21 <jayden0721@163.com>

连板天梯
接口：limit_step
描述：获取每天连板个数晋级的股票，可以分析出每天连续涨停进阶个数，判断强势热度
限量：单次最大2000行数据，可根据股票代码或者日期循环提取全部
积分：8000积分以上每分钟500次，每天总量不限制，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期（格式：YYYYMMDD，下同）
ts_code	str	N	股票代码
start_date	str	N	开始日期
end_date	str	N	结束日期
nums	str	N	连板次数，支持多个输入，例如nums='2,3'


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	代码
name	str	Y	名称
trade_date	str	Y	交易日期
nums	str	Y	连板次数


接口用法


pro = ts.pro_api()

df = pro.limit_step(trade_date='20241125')
数据样例

    ts_code        name trade_date nums
0   000833.SZ  粤桂股份   20241125   11
1   002611.SZ  东方精工   20241125    8
2   600800.SH  渤海化学   20241125    7
3   000801.SZ  四川九洲   20241125    6
4   600889.SH  南京化纤   20241125    6
5   000615.SZ  ST美谷   20241125    5
6   001229.SZ  魅视科技   20241125    5
7   002095.SZ   生意宝   20241125    5
8   002403.SZ   爱仕达   20241125    5
9   600470.SH  六国化工   20241125    5
10  603015.SH  弘讯科技   20241125    5
11  603527.SH  众源新材   20241125    5

"""
from basis import *


class get_stk_limit_step(ts2db_by_date_template):
    table_name = 'hq_stk_limit_step'  # 保存到数据库的库名
    table_name_cn = '连板天梯'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.limit_step  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 2000  # 官方文档单次最大返回量
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
                                     'nums': DECIMAL(25, 4),
                                     })
    def ts2db_clean_data(self):
        pass


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20240101', end_date=init_currentDate())
    get_stk_limit_step(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
