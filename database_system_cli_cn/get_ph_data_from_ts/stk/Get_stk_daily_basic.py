"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

每日指标
接口：daily_basic，可以通过数据工具调试和查看数据。
更新时间：交易日每日15点～17点之间
描述：获取全部股票每日重要的基本面指标，可用于选股分析、报表展示等。
限量：单次最大返回6000条数据，可按交易日循环提取全部历史。
积分：用户需要至少600积分才可以调取，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
ts_code	str	Y	股票代码（二选一）
trade_date	str	N	交易日期 （二选一）
start_date	str	N	开始日期(YYYYMMDD)
end_date	str	N	结束日期(YYYYMMDD)
注：日期都填YYYYMMDD格式，比如20181010

输出参数

名称	类型	描述
ts_code	str	TS股票代码
trade_date	str	交易日期
close	float	当日收盘价
turnover_rate	float	换手率（%）
turnover_rate_f	float	换手率（自由流通股）
volume_ratio	float	量比
pe	float	市盈率（总市值/净利润， 亏损的PE为空）
pe_ttm	float	市盈率（TTM，亏损的PE为空）
pb	float	市净率（总市值/净资产）
ps	float	市销率
ps_ttm	float	市销率（TTM）
dv_ratio	float	股息率 （%）
dv_ttm	float	股息率（TTM）（%）
total_share	float	总股本 （万股）
float_share	float	流通股本 （万股）
free_share	float	自由流通股本 （万）
total_mv	float	总市值 （万元）
circ_mv	float	流通市值（万元）

"""
import os
import sys

# 要在命令行运行，必须加上下面这两句
sys.path.append(os.path.split(os.path.abspath(os.path.dirname(__file__)))[0])  # 加载项目根目录
sys.path.append(os.path.split(os.path.split(os.path.abspath(os.path.dirname(__file__)))[0])[0])


from basis import *


class get_stk_daily_basic(ts2db_by_date_template):
    table_name = 'hq_stk_daily_basic'  # 保存到数据库的库名
    table_name_cn = '股票每日指标'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.daily_basic  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 6000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'], ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE,
                                     'close': DECIMAL(25, 4),
                                     'turnover_rate': DECIMAL(25, 4),
                                     'turnover_rate_f': DECIMAL(25, 4),
                                     'volume_ratio': DECIMAL(25, 4),
                                     'pe': DECIMAL(25, 4),
                                     'pe_ttm': DECIMAL(25, 4),
                                     'pb': DECIMAL(25, 4),
                                     'ps': DECIMAL(25, 4),
                                     'ps_ttm': DECIMAL(25, 4),
                                     'dv_ratio': DECIMAL(25, 4),
                                     'dv_ttm': DECIMAL(25, 4),
                                     'total_share': DECIMAL(25, 4),
                                     'float_share': DECIMAL(25, 4),
                                     'free_share': DECIMAL(25, 4),
                                     'total_mv': DECIMAL(25, 4),
                                     'circ_mv': DECIMAL(25, 4)
                                     })


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20230101', end_date=init_currentDate())
    get_stk_daily_basic(params).run()
    # end_str = input("加载完毕，请复核是否正确执行！")

