"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>

每日筹码分布
接口：cyq_chips
描述：获取A股每日的筹码分布情况，提供各价位占比，数据从2018年开始，每天18~19点之间更新当日数据
来源：Tushare社区
限量：单次最大6000条，可以按股票代码和日期循环提取
积分：5000积分每天20000次每分钟可以取200次，10000积分每天200000次，15000积分每天不限总量

输入参数

名称 类型 必选 描述
ts_code str Y 股票代码
trade_date str N 交易日期（YYYYMMDD）
start_date str N 开始日期
end_date str N 结束日期

输出参数

名称 类型 默认显示 描述
ts_code str Y 股票代码
trade_date str Y 交易日期
price float Y 成本价格
percent float Y 价格占比（%）

官方文档：https://tushare.pro/document/2?doc_id=294
"""
from basis import *


class get_stk_cyq_chips(ts2db_by_period_and_codelist_template):
    table_name = "hq_stk_cyq_chips"
    table_name_cn = "每日筹码分布"

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.cyq_chips
        # 官方文档 doc_id=294：cyq_chips 单次最大返回 6000 条。
        self.params.one_time_rows_limit = 6000  # 官方文档单次最大返回量
        self.params.codelist = init_data.init_codeList(
            self.params.db_engine,
            "hq_stk_basic",
        )
        self.params.how_many_codes_onetime = 1
        self.params.db_indexes = [
            ["ts_code"],
            ["trade_date"],
            ["trade_date", "ts_code", "price"],
        ]
        self.params.deal_data__duplicate_data_key = (
            "trade_date, ts_code, price"
        )

    def ts2db_write_db(self):
        return self.df.to_sql(
            self.params.table_name,
            self.params.db_engine,
            chunksize=1000000,
            if_exists="append",
            index=False,
            dtype={
                "ts_code": NVARCHAR(20),
                "trade_date": DATE,
                "price": DECIMAL(25, 4),
                "percent": DECIMAL(25, 4),
            },
        )

    def ts2db_get_data(self):
        return self.params.ts_api(
            ts_code=self.params.code,
            start_date=self.params.str_date,
            end_date=self.params.end_date,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )


if __name__ == "__main__":
    params = _params(str_date="20220101", end_date=init_currentDate())
    get_stk_cyq_chips(params).run()
