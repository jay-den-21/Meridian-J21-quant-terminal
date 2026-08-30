"""
Created on 2024年12月12日

@author: Jayden21 <jayden0721@163.com>

同花顺热榜
接口：ths_hot
描述：获取同花顺App热榜数据，包括热股、概念板块、ETF、可转债、港美股等等，每日盘中提取4次，收盘后4次，最晚22点提取一次。
限量：单次最大2000条，可根据日期等参数循环获取全部数据
积分：用户积5000积分可调取使用，积分获取办法请参阅积分获取办法



输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期
ts_code	str	N	TS代码
market	str	N	热榜类型(热股、ETF、可转债、行业板块、概念板块、期货、港股、热基、美股)
is_new	str	N	是否最新（默认Y，如果为N则为盘中和盘后阶段采集，具体时间可参考rank_time字段）


输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
data_type	str	Y	数据类型
ts_code	str	Y	股票代码
ts_name	str	Y	股票名称
rank	int	Y	排行
pct_change	float	Y	涨跌幅%
current_price	float	Y	当前价格
concept	str	Y	标签
rank_reason	str	Y	上榜解读
hot	float	Y	热度值
rank_time	str	Y	排行榜获取时间


接口示例


#获取查询月份券商金股
df = pro.ths_hot(trade_date='20240315', market='热股', fields='ts_code,ts_name,hot,concept')


数据示例

        ts_code ts_name       hot                  concept
0   300750.SZ    宁德时代  214462.0    ["钠离子电池", "同花顺漂亮100"]
1   603580.SH    艾艾精工  185431.0     ["人民币贬值受益", "台湾概念股"]
2   002085.SZ    万丰奥威  180332.0  ["飞行汽车(eVTOL)", "低空经济"]
3   600733.SH    北汽蓝谷  156000.0        ["一体化压铸", "华为汽车"]
4   603259.SH    药明康德  154360.0         ["CRO概念", "创新药"]
..        ...     ...       ...                      ...
95  300735.SZ    光弘科技   28528.0        ["智能穿戴", "EDR概念"]
96  002632.SZ    道明光学   28101.0       ["AI手机", "消费电子概念"]
97  601086.SH    国芳集团   28006.0          ["新零售", "网络直播"]
98  002406.SZ    远东传动   28003.0        ["工业互联网", "智能制造"]
99  600160.SH    巨化股份   27979.0      ["PVDF概念", "氟化工概念"]
"""
from basis import *


class get_ths_hot(ts2db_by_date_template):
    table_name = 'hq_ths_hot'  # 保存到数据库的库名
    table_name_cn = '同花顺热榜'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.ths_hot  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 2000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code'], ['trade_date', 'ts_code', 'market']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code, market, is_new'

    def ts2db_get_data(self):
        return self.params.ts_api(
            trade_date=self.params.idate,
            is_new='Y',
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'ts_code': NVARCHAR(20),
                                     'market': NVARCHAR(20),
                                     'is_new': NVARCHAR(2),
                                     })

    def ts2db_clean_data(self):
        self.df.trade_date = pd.to_datetime(self.df.trade_date)
        if 'market' not in self.df.columns:
            self.df['market'] = self.df['data_type']
        if 'is_new' not in self.df.columns:
            self.df['is_new'] = 'Y'


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20080101', end_date=init_currentDate())
    get_ths_hot(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
