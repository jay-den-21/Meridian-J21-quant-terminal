"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

场内基金日线行情
接口：fund_daily
描述：获取场内基金日线行情，类似股票日行情
更新：每日收盘后2小时内
限量：单次最大5000行记录，总量不限制
积分：用户需要至少500积分才可以调取，具体请参阅积分获取办法

复权行情实现参考：

后复权 = 当日最新价 × 当日复权因子
前复权 = 当日复权价 ÷ 最新复权因子

输入参数

名称	类型	必选	描述
ts_code	str	N	基金代码（二选一）
trade_date	str	N	交易日期（二选一）
start_date	str	N	开始日期
end_date	str	N	结束日期
输出参数

名称	类型	默认显示	描述
ts_code	str	Y	TS代码
trade_date	str	Y	交易日期
open	float	Y	开盘价(元)
high	float	Y	最高价(元)
low	float	Y	最低价(元)
close	float	Y	收盘价(元)
pre_close	float	Y	昨收盘价(元)
change	float	Y	涨跌额(元)
pct_chg	float	Y	涨跌幅(%)
vol	float	Y	成交量(手)
amount	float	Y	成交额(千元)
"""
from basis import *


# 该处使用了模板类的设计模式，接口只用继承行为相同的模板类，即可获取模板类的抓取能力；
# 这里的接口类只用实现自己的存入数据库函数write_db即可，当然必要的参数初始化也需要
# 自己扩展接口时，可以参照一个现成的，抓取行为一样的接口进行改写，改写代码也就上面的两个函数
# 使用时，只需要实例化改接口类后，调用run()方法即可
class get_fund_daily(ts2db_by_date_template):
    table_name = 'hq_fund_daily'  # 保存到数据库的库名
    table_name_cn = '场内基金日线行情'  # 接口名称

    # 初始化的工作都放在这里,该接口无法按日期段抓取
    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.fund_daily  # 告诉框架本接口对应的tushare的接口函数
        # 框架会使用basis.params.py中的默认参数，以下需要对每个接口单独配置行为参数，可以打开以下参数，进行设置
        self.params.one_time_rows_limit = 5000  # 官方文档单次最大返回量
        # self.params.times_limit = 800  # 该接口限制,每分钟最多调用次数
        # self.params.sleep_time = 61  # 一分钟内到了最多调用次数上线后，休眠多少秒
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        # 自动维护数据库表的索引，提高数据访问性能，一般能提高至少一个数量级；
        # 可根据查询数据的需要自定义一些索引，提高查询性能（只要在这里定义了，框架会自动帮你维护索引）
        # 这里一个列表即一个索引，需建立多个索引则配置多个列表，比如：self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # 注意：至少把下面去重的键值，建立一个索引
        self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        # 数据整理函数，定义后框架会自动调用，以进行数据整理
        # 数据整理是根据抓取数据的时间段进行整理的，如需指定特定时间段进行整理，请使用“单独运行数据整理.py”程序
        # 数据去重，配置好该数据接口的唯一键字组合后，框架会以此进行去重处理
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE,
                                     'pre_close': DECIMAL(25, 4),
                                     'open': DECIMAL(25, 4),
                                     'high': DECIMAL(25, 4),
                                     'low': DECIMAL(25, 4),
                                     'close': DECIMAL(25, 4),
                                     'change': DECIMAL(25, 4),
                                     'pct_chg': DECIMAL(25, 4),
                                     'vol': DECIMAL(25, 4),
                                     'amount': DECIMAL(25, 4)})


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20220101', end_date=init_currentDate())
    get_fund_daily(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
