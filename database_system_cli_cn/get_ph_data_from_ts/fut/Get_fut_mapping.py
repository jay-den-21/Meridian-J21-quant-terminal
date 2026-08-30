"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>

期货主力与连续合约
接口：fut_mapping
描述：获取期货主力（或连续）合约与月合约映射数据
限量：单次最大2000条，总量不限制
积分：用户需要至少600积分才可以调取，未来可能调整积分，请尽可能多积累积分。具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
ts_code	str	N	合约代码
trade_date	str	N	交易日期(YYYYMMDD格式，下同)
start_date	str	N	开始日期
end_date	str	N	结束日期


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	连续合约代码
trade_date	str	Y	起始日期
mapping_ts_code	str	Y	期货合约代码


接口示例


pro = ts.pro_api()

#获取主力合约TF.CFX每日对应的月合约
df = pro.fut_mapping(ts_code='TF.CFX')


数据示例

     ts_code trade_date mapping_ts_code
0     TF.CFX   20190823      TF1912.CFX
1     TF.CFX   20190822      TF1912.CFX
2     TF.CFX   20190821      TF1912.CFX
3     TF.CFX   20190820      TF1912.CFX
4     TF.CFX   20190819      TF1912.CFX
5     TF.CFX   20190816      TF1912.CFX
6     TF.CFX   20190815      TF1912.CFX
7     TF.CFX   20190814      TF1912.CFX
8     TF.CFX   20190813      TF1912.CFX
9     TF.CFX   20190812      TF1909.CFX
10    TF.CFX   20190809      TF1909.CFX
11    TF.CFX   20190808      TF1909.CFX
12    TF.CFX   20190807      TF1909.CFX
13    TF.CFX   20190806      TF1909.CFX
14    TF.CFX   20190805      TF1909.CFX
15    TF.CFX   20190802      TF1909.CFX
16    TF.CFX   20190801      TF1909.CFX
17    TF.CFX   20190731      TF1909.CFX
18    TF.CFX   20190730      TF1909.CFX
19    TF.CFX   20190729      TF1909.CFX
20    TF.CFX   20190726      TF1909.CFX

"""
from basis import *


class get_fut_mapping(ts2db_by_codelist_template):
    table_name = 'hq_fut_mapping'  # 保存到数据库的库名
    table_name_cn = '期货主力与连续合约'  # 接口名称

    def ts2db_init(self):
        self.params.auto_detect__break_point_type = 0
        self.params.ts_api = self.params.ts_pro.fut_mapping  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 2000  # 官方文档单次最大返回量
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = init_data.init_fut_ts_mcodeList(self.params.db_engine)  # 必须初始化，需要遍历的列表
        self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'],
                                  ['trade_date'],
                                  ['trade_date', 'ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, ts_code'

    def ts2db_get_data(self):
        return self.params.ts_api(
            ts_code=self.params.code,
            start_date=self.params.str_date,
            end_date=self.params.end_date,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    # 每只证券抓取后，实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'trade_date': DATE,
                                     'mapping_ts_code': NVARCHAR(20)
                                     })


if __name__ == '__main__':
    get_fut_mapping().run()

    # end_str = input("加载完毕，请复核是否正确执行！")
