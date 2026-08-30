"""
Created on 2024年12月12日

@author: Jayden21 <jayden0721@163.com>

最强板块统计
接口：limit_cpt_list
描述：获取每天涨停股票最多最强的概念板块，可以分析强势板块的轮动，判断资金动向
限量：单次最大2000行数据，可根据股票代码或者日期循环提取全部
积分：8000积分以上每分钟500次，每天总量不限制，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期（格式：YYYYMMDD，下同）
ts_code	str	N	板块代码
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	板块代码
name	str	Y	板块名称
trade_date	str	Y	交易日期
days	int	Y	上榜天数
up_stat	str	Y	连板高度
cons_nums	int	Y	连板家数
up_nums	str	Y	涨停家数
pct_chg	float	Y	涨跌幅%
rank	str	Y	板块热点排名


接口用法


pro = ts.pro_api()

df = pro.limit_cpt_list(trade_date='20241127')
数据样例

      ts_code    name      trade_date  days up_stat  cons_nums  up_nums pct_chg  rank
0   885728.TI    人工智能   20241127    18    9天7板         9       27  2.8608     1
1   885420.TI    电子商务   20241127     6    9天7板        11       25  1.8973     2
2   885806.TI    华为概念   20241127    34  18天14板         6       21  2.4648     3
3   885418.TI  文化传媒概念   20241127     2    9天7板         6       18  3.5207     4
4   885976.TI    数字经济   20241127     4    9天7板         6       17  2.8993     5
5   885788.TI    网络直播   20241127     6    9天7板         9       17  2.5367     6
6   886019.TI  AIGC概念   20241127     1    9天7板         5       16  4.3615     7
7   885756.TI    芯片概念   20241127     1    7天7板         7       16  2.4840     8
8   885642.TI    跨境电商   20241127     6    9天7板        10       16  2.1974     9
9   885517.TI   机器人概念   20241127    14    6天6板         7       16  2.1272    10
10  885929.TI    专精特新   20241127     8    7天7板         4       16  2.0335    11
11  885709.TI    虚拟现实   20241127     1    9天7板         4       15  3.4553    12
12  885934.TI     元宇宙   20241127     1    9天7板         4       14  3.9264    13
13  885757.TI     区块链   20241127     1  18天14板         5       14  3.1271    14
14  885413.TI      创投   20241127     3  18天14板         7       14  1.7311    15
15  885779.TI    腾讯概念   20241127     1    9天7板         4       13  3.3722    16
16  885876.TI    网红经济   20241127     1    9天7板         5       12  2.9002    17
17  885494.TI    一带一路   20241127     2    9天7板         1       12  1.3427    18
18  885950.TI   虚拟数字人   20241127     1    9天7板         3       11  4.1545    19
19  886013.TI      信创   20241127     2    9天7板         6       11  3.2298    20

"""
from basis import *


class get_stk_limit_cpt_list(ts2db_by_period_template):
    table_name = 'hq_stk_limit_cpt_list'  # 保存到数据库的库名
    table_name_cn = '最强板块统计'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.limit_cpt_list  # 告诉框架本接口对应的tushare的接口函数
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
                                     'industry': NVARCHAR(200),
                                     'name': NVARCHAR(50),
                                     'days': DECIMAL(25, 4),
                                     'up_stat': NVARCHAR(50),
                                     'cons_nums': DECIMAL(25, 4),
                                     'up_nums': DECIMAL(25, 4),
                                     'pct_chg': DECIMAL(25, 4),
                                     'rank': DECIMAL(25, 4),
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20080101', end_date=init_currentDate())
    get_stk_limit_cpt_list(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
