"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.


"""
from basis import *


# 注意tushare一般会限制一次调用分钟接口最多取8000条，所以尽量日期段短一点（一次一个月是最好的）
class get_stk_5min(ts2db_by_date_and_codelist_template):
    table_name = f"hq_stk_5min"  # 保存到数据库的库名
    table_name_cn = '股票行情5分钟k'  # 接口名称

    def ts2db_init(self):
        self.params.freq = '5min'  # 行情采样频率
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_stk_basic')  # 必须初始化，需要遍历的列表
        # self.params.codelist = self.params.codelist[self.params.codelist.ts_code.str[7:9] == 'SZ']  # 只要深圳市场的数据
        self.params.how_many_codes_onetime = 100
        self.params.one_time_rows_limit = 8000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['trade_date'],
                                  ['trade_time'],
                                  ['ts_code'],
                                  ['trade_date', 'trade_time'],
                                  ['trade_date', 'trade_time', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, trade_time, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE,
                                     'trade_time': TIME,
                                     'open': DECIMAL(25, 4),
                                     'close': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4),
                                     'pre_close': DECIMAL(25, 4)})

    # 抓取数据函数, 实现单次证券的抓取逻辑即可
    
    def ts2db_get_data(self):
        return self.params.ts_pro.stk_mins(ts_code=self.params.code,
                                           freq=self.params.freq,
                                           start_date=f"{self.params.get_idate_iso()} 09:00:00",
                                           end_date=f"{self.params.get_idate_iso()} 15:01:00",
                                           limit=self.params.one_time_rows_limit,
                                           offset=self.params.offset)
    def ts2db_clean_data(self):
        self.df['trade_time'] = pd.to_datetime(self.df['trade_time'])
        self.df['trade_date'] = self.df['trade_time'].dt.strftime('%Y-%m-%d')
        self.df['trade_time'] = self.df['trade_time'].dt.strftime('%H:%M:%S')

if __name__ == '__main__':
    params = _params(str_date='20250101', end_date=init_currentDate())
    get_stk_5min(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
