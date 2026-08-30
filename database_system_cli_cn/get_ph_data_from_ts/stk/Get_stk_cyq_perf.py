"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>

每日筹码及胜率
接口：cyq_perf
描述：获取A股每日筹码平均成本和胜率情况，每天17~18点左右更新，数据从2005年开始
来源：Tushare社区
限量：单次最大6000条，可以分页或者循环提取
积分：120积分可以试用查看数据，5000积分每天20000次，10000积分每天200000次，15000积分每天不限总量



输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码
trade_date	str	N	交易日期（YYYYMMDD）
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	股票代码
trade_date	str	Y	交易日期
his_low	float	Y	历史最低价
his_high	float	Y	历史最高价
cost_5pct	float	Y	5分位成本
cost_15pct	float	Y	15分位成本
cost_50pct	float	Y	50分位成本
cost_85pct	float	Y	85分位成本
cost_95pct	float	Y	95分位成本
weight_avg	float	Y	加权平均成本
winner_rate	float	Y	胜率


接口用法


pro = ts.pro_api()

df = pro.cyq_perf(ts_code='600000.SH', start_date='20220101', end_date='20220429')


数据样例

      ts_code trade_date his_low his_high cost_5pct cost_95pct weight_avg winner_rate
0   600000.SH   20220429    0.72    12.16      8.18      11.34       9.76        3.52
1   600000.SH   20220428    0.72    12.16      8.24      11.34       9.76        3.08
2   600000.SH   20220427    0.72    12.16      8.30      11.34       9.76        1.71
3   600000.SH   20220426    0.72    12.16      8.34      11.34       9.76        2.02
4   600000.SH   20220425    0.72    12.16      8.36      11.34       9.77        1.44
..        ...        ...     ...      ...       ...        ...        ...         ...
72  600000.SH   20220110    0.72    12.16      8.60      11.36       9.89        7.62
73  600000.SH   20220107    0.72    12.16      8.60      11.36       9.89        7.59
74  600000.SH   20220106    0.72    12.16      8.60      11.36       9.89        3.92
75  600000.SH   20220105    0.72    12.16      8.60      11.36       9.89        5.65
76  600000.SH   20220104    0.72    12.16      8.60      11.36       9.89        3.93

"""
from basis import *


class get_stk_cyq_perf(ts2db_by_date_template):
    table_name = 'hq_stk_cyq_perf'  # 保存到数据库的库名
    table_name_cn = '每日筹码及胜率'  # 接口名称

    def ts2db_init(self):
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        self.params.ts_api = self.params.ts_pro.cyq_perf  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 6000  # 官方文档单次最大返回量
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
                                     'his_low': DECIMAL(25, 4),
                                     'his_high': DECIMAL(25, 4),
                                     'cost_5pct': DECIMAL(25, 4),
                                     'cost_15pct': DECIMAL(25, 4),
                                     'cost_50pct': DECIMAL(25, 4),
                                     'cost_85pct': DECIMAL(25, 4),
                                     'cost_95pct': DECIMAL(25, 4),
                                     'weight_avg': DECIMAL(25, 4),
                                     'winner_rate': DECIMAL(25, 4)
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250120', end_date=init_currentDate())
    get_stk_cyq_perf(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
