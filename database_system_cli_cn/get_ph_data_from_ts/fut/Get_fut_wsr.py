"""
Created on 2021年12月5日

@author: Jayden21 <jayden0721@163.com>

仓单日报
接口：fut_wsr
描述：获取仓单日报数据，了解各仓库/厂库的仓单变化
限量：单次最大1000，总量不限制
积分：用户需要至少600积分才可以调取，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期
symbol	str	N	产品代码
start_date	str	N	开始日期(YYYYMMDD格式，下同)
end_date	str	N	结束日期
exchange	str	N	交易所代码
输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
symbol	str	Y	产品代码
fut_name	str	Y	产品名称
warehouse	str	Y	仓库名称
wh_id	str	N	仓库编号
pre_vol	int	Y	昨日仓单量
vol	int	Y	今日仓单量
vol_chg	int	Y	增减量
area	str	N	地区
year	str	N	年度
grade	str	N	等级
brand	str	N	品牌
place	str	N	产地
pd	int	N	升贴水
is_ct	str	N	是否折算仓单
unit	str	Y	单位
exchange	str	N	交易所
接口示例


pro = ts.pro_api('your token')

df = pro.fut_wsr(trade_date='20181113', symbol='ZN')
数据示例

     trade_date symbol fut_name    warehouse  pre_vol   vol  vol_chg unit
0    20181113     ZN        锌      上海裕强     4960  4960        0    吨
1    20181113     ZN        锌      上港物流      702   702        0    吨
2    20181113     ZN        锌    上港物流苏州        0     0        0    吨
3    20181113     ZN        锌      中储吴淞        0     0        0    吨
4    20181113     ZN        锌      中储大场        0     0        0    吨
5    20181113     ZN        锌      中储晟世        0     0        0    吨
6    20181113     ZN        锌      中金圣源      428   353      -75    吨
7    20181113     ZN        锌      全胜物流     2882  2882        0    吨
8    20181113     ZN        锌      南储仓储       25    25        0    吨
9    20181113     ZN        锌      同盛松江        0     0        0    吨
10   20181113     ZN        锌    国储837处        0     0        0    吨
11   20181113     ZN        锌      国储天威        0     0        0    吨
12   20181113     ZN        锌    国能物流常州      200   200        0    吨
13   20181113     ZN        锌   外运华东张华浜        0     0        0    吨
14   20181113     ZN        锌     宁波九龙仓        0     0        0    吨
15   20181113     ZN        锌  广储830三水西        0     0        0    吨
16   20181113     ZN        锌      康运萧山        0     0        0    吨
17   20181113     ZN        锌      无锡国联        0     0        0    吨
18   20181113     ZN        锌      期晟公司      449   226     -223    吨
19   20181113     ZN        锌      浙江康运       25    25        0    吨
20   20181113     ZN        锌     百金汇物流        0     0        0    吨
21   20181113     ZN        锌      裕强闵行        0     0        0    吨

"""
from basis import *


class get_fut_wsr(ts2db_by_date_template):
    table_name = 'hq_fut_wsr'  # 保存到数据库的库名
    table_name_cn = '期货仓单日报'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.fut_wsr  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 1000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['symbol'], ['trade_date', 'symbol'],
                                  ['trade_date'],
                                  ['trade_date', 'symbol', 'fut_name', 'warehouse']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = (
            'trade_date, symbol, fut_name, warehouse'
        )

    def ts2db_clean_data(self):
        key_columns = ['trade_date', 'symbol', 'warehouse']
        if 'fut_name' in self.df.columns:
            key_columns.insert(2, 'fut_name')
        duplicate_rows = self.df.loc[
            self.df.duplicated(subset=key_columns, keep=False)
        ]
        unique_duplicate_rows = duplicate_rows.drop_duplicates()
        if unique_duplicate_rows.duplicated(
            subset=key_columns, keep=False
        ).any():
            raise ValueError(
                'fut_wsr returned conflicting payloads for a declared key'
            )
        self.df.drop_duplicates(
            subset=key_columns, keep='first', inplace=True
        )

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'symbol': NVARCHAR(50),
                                     'fut_name': NVARCHAR(50),
                                     'warehouse': NVARCHAR(50),
                                     'wh_id': NVARCHAR(50),
                                     'pre_vol': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'vol_chg': DECIMAL(25, 4),
                                     'area': NVARCHAR(20),
                                     'year': NVARCHAR(20),
                                     'grade': NVARCHAR(20),
                                     'brand': NVARCHAR(20),
                                     'place': NVARCHAR(20),
                                     'pd': DECIMAL(25, 4),
                                     'is_ct': NVARCHAR(20),
                                     'unit': NVARCHAR(20),
                                     'exchange': NVARCHAR(20)
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_fut_wsr(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
