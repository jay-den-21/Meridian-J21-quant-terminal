"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>

基金复权因子
接口：fund_fund_adj
描述：获取基金复权因子，用于计算基金复权行情
限量：单次最大提取2000行记录，可循环提取，数据总量不限制
积分：用户积600积分可调取，超过5000积分以上频次相对较高。具体请参阅积分获取办法



复权行情实现参考：

后复权 = 当日最新价 × 当日复权因子
前复权 = 当日复权价 ÷ 最新复权因子



输入参数

名称	类型	必选	描述
ts_code	str	N	TS基金代码（支持多只基金输入）
trade_date	str	N	交易日期（格式：yyyymmdd，下同）
start_date	str	N	开始日期
end_date	str	N	结束日期
offset	str	N	开始行数
stk_limit	str	N	最大行数


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	ts基金代码
trade_date	str	Y	交易日期
adj_factor	float	Y	复权因子
接口使用


pro = ts.pro_api()

df = pro.fund_fund_adj(ts_code='513100.SH', start_date='20190101', end_date='20190926')


数据示例

     ts_code    trade_date  adj_factor
0    513100.SH   20190926         1.0
1    513100.SH   20190925         1.0
2    513100.SH   20190924         1.0
3    513100.SH   20190923         1.0
4    513100.SH   20190920         1.0
5    513100.SH   20190919         1.0
6    513100.SH   20190918         1.0
7    513100.SH   20190917         1.0
8    513100.SH   20190916         1.0
9    513100.SH   20190912         1.0
10   513100.SH   20190911         1.0
11   513100.SH   20190910         1.0
12   513100.SH   20190909         1.0
13   513100.SH   20190906         1.0
14   513100.SH   20190905         1.0
15   513100.SH   20190904         1.0
16   513100.SH   20190903         1.0
17   513100.SH   20190902         1.0
18   513100.SH   20190830         1.0
19   513100.SH   20190829         1.0
20   513100.SH   20190828         1.0

"""
from basis import *


class get_fund_adj_factor(ts2db_by_period_template):
    table_name = 'hq_fund_adj_factor'  # 保存到数据库的库名
    table_name_cn = '基金复权因子'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.fund_adj  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 2000  # 官方文档单次最大返回量
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        # -------------------------------------------定义数据库索引--------------------------------------------------------
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
                                     'start_date': DATE,
                                     'end_date': DATE,
                                     'offset': NVARCHAR(20),
                                     'stk_limit': NVARCHAR(20),
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20240101', end_date=init_currentDate())
    get_fund_adj_factor(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
