"""
Created on 2022年3月7日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

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
import datetime as _datetime
import os
import sys

# 要在命令行运行，必须加上下面这两句
sys.path.append(os.path.split(os.path.abspath(os.path.dirname(__file__)))[0])  # 加载项目根目录
sys.path.append(os.path.split(os.path.split(os.path.abspath(os.path.dirname(__file__)))[0])[0])

from basis import *


class get_rt_stk_quote_tick(ts2db_rt_by_src_and_codelist_template):
    def ts2db_init(self):  # 初始化的工作都放在这里
        self.params.table_name = 'hq_rt_stk_quote_tick__sina'  # 保存到数据库的库名
        self.params.ts_api = self.params.ts.realtime_quote  # 告诉框架本接口对应的tushare的接口函数
        self.params.table_name_cn = '实时_盘口TICK快照'  # 接口名称

        self.params.src = 'sina'  # 数据源 （sina-新浪 dc-东方财富，默认sina）
        self.params.how_many_codes_onetime = 50  # 一次调用最多获取多少个代码对应的数据
        self.params.time_gap = 3  # 间隔多少秒抓一次数据
        self.params.rt_deal_duplicate_data = True  # 是否实时内存去重数据
        self.params.deal_duplicate_strict_date_scope = True
        self.params.str_time = '09:00:00'
        self.params.end_time = '15:01:00'
        self._provider_trade_dates = set()

        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # # db_tools(self.params).truncate_table()  # 删除当前表。tick数据量较大，如果不需要历史，只需要当天的数据，打开该行
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_stk_basic')  # 必须初始化，需要遍历的列表
        # self.params.codelist = pd.DataFrame({'ts_code': ['000001.SZ', '000002.SZ', '000003.SZ']})

        # -------------------------------------------定义数据库索引--------------------------------------------------------
        # 自动维护数据库表的索引，提高数据访问性能，一般能提高至少一个数量级；
        # 可根据查询数据的需要自定义一些索引，提高查询性能（只要在这里定义了，框架会自动帮你维护索引）
        # 这里一个列表即一个索引，需建立多个索引则配置多个列表，比如：self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # 注意：至少把下面去重的键值，建立一个索引
        self.params.db_indexes = [['ts_code'],
                                  ['trade_date', ],
                                  ['trade_date', 'ts_code'],
                                  ['trade_date', 'trade_time', 'ts_code', 'src']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        # 数据整理函数，定义后框架会自动调用，以进行数据整理
        # 数据整理是根据抓取数据的时间段进行整理的，如需指定特定时间段进行整理，请使用“单独运行数据整理.py”程序
        # 数据去重，配置好该数据接口的唯一键字组合后，框架会以此进行去重处理
        self.params.deal_data__duplicate_data_key = (
            'trade_date, trade_time, ts_code, src'
        )

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
        # 数据标准化
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
                                'AMOUNT': 'amount',
                                }, inplace=True)
        self.df['src'] = self.params.src
        provider_trade_dates = set()
        if len(self.df):
            if 'trade_date' not in self.df.columns:
                raise ValueError(
                    'realtime_quote provider trade_date is missing'
                )
            for value in self.df['trade_date']:
                if not isinstance(value, str):
                    raise ValueError(
                        'realtime_quote provider trade_date must be a string'
                    )
                if (
                    len(value) == 10
                    and value[4] == '-'
                    and value[7] == '-'
                    and (value[:4] + value[5:7] + value[8:]).isdigit()
                ):
                    date_format = '%Y-%m-%d'
                elif len(value) == 8 and value.isdigit():
                    date_format = '%Y%m%d'
                else:
                    raise ValueError(
                        'realtime_quote provider trade_date is not canonical'
                    )
                try:
                    parsed_date = _datetime.datetime.strptime(
                        value,
                        date_format,
                    )
                except ValueError as exc:
                    raise ValueError(
                        'realtime_quote provider trade_date is invalid'
                    ) from exc
                provider_trade_dates.add(
                    parsed_date.strftime('%Y%m%d')
                )
        # 数据清洗
        self.df.replace('', '0.0', inplace=True)  # 将数据中的空值统一补全为0.0
        self.df.replace('-', '0.0', inplace=True)  # 将数据中的空值统一补全为0.0
        self._provider_trade_dates.update(provider_trade_dates)

    def ts2db_deal_duplicate_datas(self, keys):
        if keys is None:
            return None
        provider_trade_dates = getattr(
            self,
            '_provider_trade_dates',
            None,
        )
        if provider_trade_dates is None:
            raise RuntimeError(
                'realtime_quote provider trade-date scope is not initialized'
            )
        if not provider_trade_dates:
            return None
        if not getattr(
            self.params,
            'deal_duplicate_strict_date_scope',
            False,
        ):
            raise RuntimeError(
                'realtime_quote strict date-scoped cleanup is required'
            )
        str_date = self.params.str_date
        end_date = self.params.end_date
        try:
            result = None
            for provider_trade_date in sorted(provider_trade_dates):
                self.params.str_date = provider_trade_date
                self.params.end_date = provider_trade_date
                result = super().ts2db_deal_duplicate_datas(keys)
            return result
        finally:
            self.params.str_date = str_date
            self.params.end_date = end_date


if __name__ == '__main__':
    get_rt_stk_quote_tick().run()

    # end_str = input("加载完毕，请复核是否正确执行！")
