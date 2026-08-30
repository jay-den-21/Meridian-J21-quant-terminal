"""
Created on 2024年12月12日

@author: Jayden21 <jayden0721@163.com>

涨跌停列表（新）
接口：limit_list_d
描述：获取沪深A股每日涨跌停、炸板数据情况，数据从2020年开始
限量：单次最大可以获取2500条数据，可通过日期或者股票循环提取
积分：120积分可查看数据，5000积分每分钟可以请求200次，8000积分以上每分钟500次，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期
ts_code	str	N	股票代码
limit_type	str	N	涨跌停类型（U涨停D跌停Z炸板）
exchange	str	N	交易所（SH上交所SZ深交所BJ北交所）
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
ts_code	str	Y	股票代码
industry	str	Y	所属行业
name	str	Y	股票名称
close	float	Y	收盘价
pct_chg	float	Y	涨跌幅
amount	float	Y	成交额
limit_amount	float	Y	板上成交金额(涨停无此数据)
float_mv	float	Y	流通市值
total_mv	float	Y	总市值
turnover_ratio	float	Y	换手率
fd_amount	float	Y	封单金额
first_time	str	Y	首次封板时间（跌停无此数据）
last_time	str	Y	最后封板时间
open_times	int	Y	炸板次数(跌停为开板次数)
up_stat	str	Y	涨停统计（N/T T天有N次涨停）
limit_times	int	Y	连板数
stk_limit	str	Y	D跌停U涨停Z炸板


接口用法


pro = ts.pro_api()

df = pro.limit_list_d(trade_date='20220615', limit_type='U', fields='ts_code,trade_date,industry,name,close,pct_chg,open_times,up_stat,limit_times')
数据样例

     trade_date ts_code      industry   name  close pct_chg  open_times up_stat  limit_times
0    20220615  000017.SZ     交运设备   深中华A   3.65    9.94           0     1/1            1
1    20220615  000025.SZ     汽车服务  特  力Ａ  29.54   10.02           5   12/23            1
2    20220615  000498.SZ     工程建设   山东路桥  10.41   10.04           3     1/1            1
3    20220615  000502.SZ     房地产服    绿景退   0.69    9.52           2     3/3            3
4    20220615  000532.SZ     综合行业   华金资本  12.69    9.97           0     1/1            1
..        ...        ...      ...    ...    ...     ...         ...     ...          ...
56   20220615  603633.SH     消费电子   徕木股份  14.58   10.04           3     2/4            1
57   20220615  603668.SH     农牧饲渔   天马科技  18.22   10.02           0     2/2            2
58   20220615  603918.SH     互联网服   金桥信息   9.49    9.97           6     1/1            1
59   20220615  603963.SH       中药   大理药业  14.78    9.97           1     1/1            1
60   20220615  605068.SH     汽车零部   明新旭腾  29.03   10.00           1     2/2            2

"""
from basis import *


class get_stk_limit_list_d(ts2db_by_date_template):
    table_name = 'hq_stk_limit_list_d'  # 保存到数据库的库名
    table_name_cn = '股票每日涨跌停列表（新）'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.limit_list_d  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 2500  # 官方文档单次最大返回量
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
                                     'industry': NVARCHAR(200),
                                     'name': NVARCHAR(50),
                                     'close': DECIMAL(25, 4),
                                     'pct_chg': DECIMAL(25, 4),
                                     'pre_close': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'limit_amount': DECIMAL(25, 4),
                                     'float_mv': DECIMAL(25, 4),
                                     'total_mv': DECIMAL(25, 4),
                                     'turnover_ratio': DECIMAL(25, 4),
                                     'fd_amount': DECIMAL(25, 4),
                                     'first_time': TIME,
                                     'last_time': TIME,
                                     'open_time': TIME,
                                     'up_stat': NVARCHAR(20),
                                     'limit_times': DECIMAL(25, 4),
                                     'limit_l': NVARCHAR(2),
                                     })


    def ts2db_clean_data(self):
        self.df.rename(columns={'limit': 'limit_l'}, inplace=True)


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20240501', end_date='20240510')
    get_stk_limit_list_d(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
