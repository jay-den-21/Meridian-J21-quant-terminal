"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>

公募基金持仓数据
接口：fund_portfolio
描述：获取公募基金持仓数据，季度更新
积分：用户需要至少2000积分才可以调取，5000积分以上频次会比较高，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
ts_code	str	Y	基金代码
ann_date	str	N	公告日期（YYYYMMDD格式）
start_date	str	N	报告期开始日期（YYYYMMDD格式）
end_date	str	N	报告期结束日期（YYYYMMDD格式）
输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS基金代码
ann_date	str	Y	公告日期
end_date	str	Y	截止日期
symbol	str	Y	股票代码
mkv	float	Y	持有股票市值(元)
amount	float	Y	持有股票数量（股）
stk_mkv_ratio	float	Y	占股票市值比
stk_float_ratio	float	Y	占流通股本比例
接口示例


pro = ts.pro_api()

df = pro.fund_portfolio(ts_code='001753.OF')
数据示例

    ts_code  ann_date  end_date     symbol          mkv    amount  \
0    001753.OF  20180823  20180630  603019.SH   3130994.46   68258.0
1    001753.OF  20180718  20180630  600845.SH   3594140.00  136400.0
2    001753.OF  20180718  20180630  600596.SH   5428107.30  335690.0
3    001753.OF  20180718  20180630  600588.SH   3811672.65  155515.0
4    001753.OF  20180718  20180630  600271.SH   3770284.00  149200.0
5    001753.OF  20180823  20180630  300616.SZ     10900.00     100.0
6    001753.OF  20180718  20180630  300577.SZ   4544793.54  110257.0
7    001753.OF  20180718  20180630  300476.SZ   3783780.00  245700.0
8    001753.OF  20180823  20180630  300409.SZ   2895942.00   72200.0
9    001753.OF  20180718  20180630  300208.SZ   5768280.00  588000.0
10   001753.OF  20180823  20180630  300188.SZ   2535922.50  138575.0

     stk_mkv_ratio  stk_float_ratio
0             4.37             0.01
1             5.02             0.02
2             7.57             0.05
3             5.32             0.01
4             5.26             0.01
5             0.02             0.00
6             6.34             0.17
7             5.28             0.07
8             4.04             0.05
9             8.05             0.10
10            3.54             0.03


"""
from basis import *


class get_fund_portfolio(ts2db_by_period_and_codelist_template):
    table_name = 'hq_fund_portfolio'  # 保存到数据库的库名
    table_name_cn = '公募基金持仓数据'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.fund_portfolio  # 告诉框架本接口对应的tushare的接口函数
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_fund_basic')  # 必须初始化，需要遍历的列表
        self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['ts_code', 'ann_date', 'end_date', 'symbol']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code, ann_date, end_date, symbol'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'ann_date': DATE,
                                     'end_date': DATE,
                                     'symbol': NVARCHAR(20),
                                     'mkv': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'stk_mkv_ratio': DECIMAL(25, 4),
                                     'stk_float_ratio': DECIMAL(25, 4)
                                     })


if __name__ == '__main__':
    params = _params(str_date='20240101', end_date=init_currentDate())
    get_fund_portfolio(params).run()
