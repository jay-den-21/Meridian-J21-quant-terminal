"""
Created on 2024年12月12日

@author: Jayden21 <jayden0721@163.com>

开盘啦题材库
接口：kpl_concept
描述：获取开盘啦概念题材列表，每天盘后更新
限量：单次最大5000条，可根据日期循环获取历史数据
积分：5000积分可提取数据，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
trade_date	str	N	交易日期（YYYYMMDD格式）
ts_code	str	N	题材代码（xxxxxx.KP格式）
name	str	N	题材名称


输出参数

名称	类型	默认显示	描述
trade_date	str	Y	交易日期
ts_code	str	Y	题材代码
name	str	Y	题材名称
z_t_num	None	Y	涨停数量
up_num	str	Y	排名上升位数


接口用法


pro = ts.pro_api()

df = pro.kpl_concept(trade_date='20241014')


数据样例

    trade_date    ts_code     name      z_t_num up_num
0     20241014  000111.KP     化债概念       15      0
1     20241014  000262.KP     跨境支付        2      0
2     20241014  000039.KP     华为鸿蒙        8      0
3     20241014  000259.KP   墨脱水电概念        3     68
4     20241014  000276.KP   神经网络概念        1      0
..         ...        ...      ...      ...    ...
160   20241014  000267.KP     乙游概念        0      0
161   20241014  000203.KP      碳纤维        0      0
162   20241014  000167.KP   冷锻工艺概念        0      0
163   20241014  000059.KP    一体化压铸        0      0
164   20241014  000266.KP  集换式卡牌概念        0      0
"""
from basis import *


class get_stk_kpl_concept(ts2db_by_date_template):
    table_name = 'hq_stk_kpl_concept'  # 保存到数据库的库名
    table_name_cn = '开盘啦题材库'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.kpl_concept  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 5000  # 官方文档单次最大返回量
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
                                     'name': NVARCHAR(50),
                                     'z_t_num': DECIMAL(25, 4),
                                     'up_num': DECIMAL(25, 4)
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250101', end_date=init_currentDate())
    get_stk_kpl_concept(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")
