"""
Created on 2022年3月7日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

实时盘口TICK快照
接口：realtime_quote


输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码，需按tushare股票和指数标准代码输入，比如：000001.SZ表示平安银行，000001.SH表示上证指数
src	str	N	数据源 （sina-新浪 dc-东方财富，默认sina）

src数据源说明：
src源	说明	描述
sina	新浪财经	支持多个多个股票同时输入，举例：ts_code='600000.SH,000001.SZ'），一次最多不能超过50个股票
dc	东方财富	只支持单个股票提取


输出参数

名称	类型	描述
name	str	股票名称
ts_code	str	股票代码
date	str	交易日期
time	str	交易时间
open	float	开盘价
pre_close	float	昨收价
price	float	现价
high	float	今日最高价
low	float	今日最低价
bid	float	竞买价，即“买一”报价（元）
ask	float	竞卖价，即“卖一”报价（元）
volume	int	成交量（src=sina时是股，src=dc时是手）
amount	float	成交金额（元 CNY）
b1_v	float	委买一（量，单位：手，下同）
b1_p	float	委买一（价，单位：元，下同）
b2_v	float	委买二（量）
b2_p	float	委买二（价）
b3_v	float	委买三（量）
b3_p	float	委买三（价）
b4_v	float	委买四（量）
b4_p	float	委买四（价）
b5_v	float	委买五（量）
b5_p	float	委买五（价）
a1_v	float	委卖一（量，单位：手，下同）
a1_p	float	委卖一（价，单位：元，下同）
a2_v	float	委卖二（量）
a2_p	float	委卖二（价）
a3_v	float	委卖三（量）
a3_p	float	委卖三（价）
a4_v	float	委卖四（量）
a4_p	float	委卖四（价）
a5_v	float	委卖五（量）
a5_p	float	委卖五（价）
"""
from basis import *


class RealtimeCodeListRequiredError(ValueError):
    """Raised when a real-time endpoint has no caller-supplied codes."""


class get_rt_stk_quote_tick(ts2db_rt_by_src_and_codelist_template):
    def ts2db_init(self):  # 初始化的工作都放在这里
        self.params.table_name = 'hq_rt_stk_quote_tick__east'  # 保存到数据库的库名
        self.params.ts_api = self.params.ts.realtime_quote  # 告诉框架本接口对应的tushare的接口函数
        self.params.table_name_cn = '实时_盘口TICK快照'  # 接口名称

        self.params.src = 'dc'  # 数据源 （sina-新浪 dc-东方财富，默认sina）
        self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据
        self.params.time_gap = 0.1  # 间隔多少秒抓一次数据
        self.params.rt_deal_duplicate_data = True  # 是否实时内存去重数据
        # self.params.str_time = '09:15:00'
        # self.params.end_time = '15:01:00'
        self.params.str_time = '09:15:00'
        self.params.end_time = '15:01:00'
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        codelist = getattr(self.params, 'codelist', None)
        if codelist is None or len(codelist) == 0:
            raise RealtimeCodeListRequiredError(
                'codelist must be supplied by the realtime caller'
            )
        self.params.codelist = codelist
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        # 自动维护数据库表的索引，提高数据访问性能，一般能提高至少一个数量级；
        # 可根据查询数据的需要自定义一些索引，提高查询性能（只要在这里定义了，框架会自动帮你维护索引）
        # 这里一个列表即一个索引，需建立多个索引则配置多个列表，比如：self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # 注意：至少把下面去重的键值，建立一个索引
        self.params.db_indexes = [['ts_code'],
                                  ['trade_date', 'trade_time', 'ts_code'],
                                  ['trade_date', 'trade_time', 'ts_code', 'src']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        # 数据整理函数，定义后框架会自动调用，以进行数据整理
        # 数据整理是根据抓取数据的时间段进行整理的，如需指定特定时间段进行整理，请使用“单独运行数据整理.py”程序
        # 数据去重，配置好该数据接口的唯一键字组合后，框架会以此进行去重处理
        self.params.deal_data__duplicate_data_key = 'trade_date, trade_time, ts_code, src'

    # 每只证券抓取后，实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'src': NVARCHAR(5),
                                     'trade_date': DATE,
                                     'trade_time': TIME,
                                     'name': NVARCHAR(50),
                                     'open': DECIMAL(12, 4),
                                     'pre_close': DECIMAL(12, 4),
                                     'price': DECIMAL(12, 4),
                                     'high': DECIMAL(12, 4),
                                     'low': DECIMAL(12, 4),
                                     'BID': DECIMAL(12, 4),
                                     'ASK': DECIMAL(12, 4),
                                     'volume': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'B1_V': DECIMAL(12, 4),
                                     'B1_P': DECIMAL(12, 4),
                                     'B2_V': DECIMAL(12, 4),
                                     'B2_P': DECIMAL(12, 4),
                                     'B3_V': DECIMAL(12, 4),
                                     'B3_P': DECIMAL(12, 4),
                                     'B4_V': DECIMAL(12, 4),
                                     'B4_P': DECIMAL(12, 4),
                                     'B5_V': DECIMAL(12, 4),
                                     'B5_P': DECIMAL(12, 4),
                                     'A1_V': DECIMAL(12, 4),
                                     'A1_P': DECIMAL(12, 4),
                                     'A2_V': DECIMAL(12, 4),
                                     'A2_P': DECIMAL(12, 4),
                                     'A3_V': DECIMAL(12, 4),
                                     'A3_P': DECIMAL(12, 4),
                                     'A4_V': DECIMAL(12, 4),
                                     'A4_P': DECIMAL(12, 4),
                                     'A5_V': DECIMAL(12, 4),
                                     'A5_P': DECIMAL(12, 4)})

    def ts2db_clean_data(self):
        self.df.rename(columns={'NAME': 'name',
                                'TS_CODE': 'ts_code',
                                'DATE': 'trade_date',
                                'TIME': 'trade_time',
                                'OPEN': 'open',
                                'PRE_CLOSE': 'pre_close',
                                'PRICE': 'price',
                                'HIGH': 'high',
                                'LOW': 'low',
                                'VOLUME': 'volume',
                                'AMOUNT': 'amount'
                                }, inplace=True)
        self.df['src'] = self.params.src
        key_columns = ['trade_date', 'trade_time', 'ts_code', 'src']
        raw_key_count = len(self.df[key_columns].drop_duplicates())

        def normalize_trade_time(value):
            if type(value) is not str:
                raise ValueError(
                    'realtime_quote trade time must be a string'
                )
            candidate = value[1:] if value.startswith(' ') else value
            if (
                len(value) not in {8, 9}
                or len(value) == 9 and not value.startswith(' ')
                or len(candidate) != 8
                or candidate[2] != ':'
                or candidate[5] != ':'
                or not (
                    candidate[:2]
                    + candidate[3:5]
                    + candidate[6:]
                ).isdigit()
            ):
                raise ValueError(
                    'realtime_quote trade time is not canonical'
                )
            hour, minute, second = (
                int(candidate[:2]),
                int(candidate[3:5]),
                int(candidate[6:]),
            )
            if hour > 23 or minute > 59 or second > 59:
                raise ValueError(
                    'realtime_quote trade time is outside clock bounds'
                )
            return candidate

        self.df['trade_time'] = self.df['trade_time'].map(
            normalize_trade_time
        )
        if len(self.df[key_columns].drop_duplicates()) != raw_key_count:
            raise ValueError(
                'realtime_quote trade-time normalization collides'
            )
        # 数据清洗
        self.df.replace('', '0.0', inplace=True)  # 将数据中的空值统一补全为0.0
        self.df.replace('-', '0.0', inplace=True)  # 将数据中的空值统一补全为0.0


if __name__ == '__main__':
    params = _params()
    params.codelist = pd.DataFrame({'ts_code': ['000001.SZ', '000002.SZ', '000003.SZ']})
    get_rt_stk_quote_tick(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
