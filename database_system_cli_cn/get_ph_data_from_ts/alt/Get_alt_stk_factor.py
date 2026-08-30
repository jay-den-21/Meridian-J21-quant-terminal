"""
Created on 2022年6月4日

@author: Jayden21 <jayden0721@163.com>

股票技术因子（量化因子）
接口：stk_factor
描述：获取股票每日技术面因子数据，用于跟踪股票当前走势情况，数据由Tushare社区自产，覆盖全历史
限量：单次最大10000条，可以循环或者分页提取
积分：120积分可查看数据，5000积分每分钟可以请求100次，8000积分以上每分钟500次，具体请参阅积分获取办法

注：
1、本接口的前复权行情是从最新一个交易日开始往前复权，跟行情软件一致。
2、pro_bar接口的前复权是动态复权，即以end_date参数开始往前复权，与本接口会存在不一致的可能，属正常。
3、本接口技术指标都是基于前复权价格计算。


输入参数

名称	类型	必选	描述
ts_code	str	N	股票代码
trade_date	str	N	交易日期 （yyyymmdd，下同）
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	股票代码
trade_date	str	Y	交易日期
close	float	Y	收盘价
open	float	Y	开盘价
high	float	Y	最高价
low	float	Y	最低价
pre_close	float	Y	昨收价
change	float	Y	涨跌额
pct_change	float	Y	涨跌幅
vol	float	Y	成交量 （手）
amount	float	Y	成交额 （千元）
adj_factor	float	Y	复权因子
open_hfq	float	Y	开盘价后复权
open_qfq	float	Y	开盘价前复权
close_hfq	float	Y	收盘价后复权
close_qfq	float	Y	收盘价前复权
high_hfq	float	Y	最高价后复权
high_qfq	float	Y	最高价前复权
low_hfq	float	Y	最低价后复权
low_qfq	float	Y	最低价前复权
pre_close_hfq	float	Y	昨收价后复权
pre_close_qfq	float	Y	昨收价前复权
macd_dif	float	Y	MCAD_DIF (基于前复权价格计算，下同)
macd_dea	float	Y	MCAD_DEA
macd	float	Y	MCAD
kdj_k	float	Y	KDJ_K
kdj_d	float	Y	KDJ_D
kdj_j	float	Y	KDJ_J
rsi_6	float	Y	RSI_6
rsi_12	float	Y	RSI_12
rsi_24	float	Y	RSI_24
boll_upper	float	Y	BOLL_UPPER
boll_mid	float	Y	BOLL_MID
boll_lower	float	Y	BOLL_LOWER
cci	float	Y	CCI
"""
from basis import *


class get_alt_stk_factor(ts2db_by_period_and_codelist_template):
    table_name = 'hq_alt_stk_factor'  # 保存到数据库的库名
    table_name_cn = '股票技术因子（量化因子）'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.stk_factor  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 10000  # 官方文档单次最大返回量
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_stk_basic')  # 必须初始化，需要遍历的列表
        self.params.how_many_codes_onetime = 100
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['trade_date'], ['ts_code'], ['ts_code', 'trade_date']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE})


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_alt_stk_factor(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
