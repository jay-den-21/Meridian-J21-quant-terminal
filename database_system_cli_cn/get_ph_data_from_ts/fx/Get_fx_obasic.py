"""
Created on 2021年7月17日

@author: Jayden21 <jayden0721@163.com>

外汇基础信息（海外）
接口：fx_obasic
描述：获取海外外汇基础信息，目前只有FXCM交易商的数据
数量：单次可提取全部数据
积分：用户需要至少2000积分才可以调取，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
exchange	str	N	交易商
classify	str	N	分类
ts_code	str	N	TS代码


classify分类说明

序号	分类代码	分类名称	样例
1	FX	外汇货币对	USDCNH（美元人民币对）
2	INDEX	指数	US30（美国道琼斯工业平均指数）
3	COMMODITY	大宗商品	SOYF（大豆）
4	METAL	金属	XAUUSD （黄金）
5	BUND	国库债券	Bund（长期欧元债券）
6	CRYPTO	加密数字货币	BTCUSD (比特币)
7	FX_BASKET	外汇篮子	USDOLLAR （美元指数）


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	外汇代码
name	str	Y	名称
classify	str	Y	分类
exchange	str	Y	交易商
min_unit	float	Y	最小交易单位
max_unit	float	Y	最大交易单位
pip	float	Y	点
pip_cost	float	Y	点值
traget_spread	float	Y	目标差价
min_stop_distance	float	Y	最小止损距离（点子）
trading_hours	str	Y	交易时间
break_time	str	Y	休市时间
接口示例


pro = ts.pro_api()

#获取差价合约(CFD)中指数产的基础信息
df = pro.fx_obasic(exchange='FXCM', classify='INDEX', fields='ts_code,name,min_unit,max_unit,pip,pip_cost')


数据示例

        ts_code                  name     min_unit  max_unit  pip  pip_cost
0    AUS200.FXCM  澳大利亚标准普尔200指数       1.0    2000.0  1.0       0.1
1     CHN50.FXCM      富时中国A50指数       1.0     100.0  1.0       0.1
2     ESP35.FXCM    西班牙IBEX35指数       1.0    5000.0  1.0       0.1
3   EUSTX50.FXCM      欧洲斯托克50指数       1.0    5000.0  1.0       0.1
4     FRA40.FXCM      法国CAC40指数       1.0    5000.0  1.0       0.1
5     GER30.FXCM        德国DAX指数       1.0    1000.0  1.0       0.1
6     HKG33.FXCM         香港恒生指数       1.0     300.0  1.0       1.0
7    JPN225.FXCM        日经225指数      10.0    1000.0  1.0      10.0
8    NAS100.FXCM    美国纳斯达克100指数       1.0    5000.0  1.0       0.1
9    SPX500.FXCM      美国标普500指数       1.0    5000.0  0.1       0.1
10    UK100.FXCM      英国富时100指数       1.0    4000.0  1.0       0.1
11     US30.FXCM      道琼斯工业平均指数       1.0    4000.0  1.0       0.1
12   US2000.FXCM     美国罗素2000指数       1.0    5000.0  0.1       0.1

"""
from basis import *


class get_fx_obasic(ts2db_by_limit_template):
    table_name = 'hq_fx_obasic'  # 保存到数据库的库名
    table_name_cn = '外汇基础信息（海外）'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.fx_obasic  # 告诉框架本接口对应的tushare的接口函数
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'name': NVARCHAR(20),
                                     'classify': NVARCHAR(20),
                                     'exchange': NVARCHAR(20),
                                     'min_unit': DECIMAL(25, 4),
                                     'max_unit': DECIMAL(25, 4),
                                     'pip': DECIMAL(25, 4),
                                     'pip_cost': DECIMAL(25, 4),
                                     'traget_spread': DECIMAL(25, 4),
                                     'min_stop_distance': DECIMAL(25, 4),
                                     'trading_hours': NVARCHAR(100),
                                     'break_time': NVARCHAR(100)
                                     })


if __name__ == '__main__':
    get_fx_obasic(_params()).run()
