"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

新闻联播
为了更加深入地学习贯彻我党的重要指示精神，利用新时代的新技术弘扬社会主义新价值观，特地整理了过去十年新闻联播的文字稿供大家研究、参考学习。希望大家领悟在心，实务在行，同时也别忘了抓住投资机会。

接口：cctv_news
描述：获取新闻联播文字稿数据，数据开始于2006年6月，超过12年历史
限量：总量不限制
积分：用户积累5000积分可以调取，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
date	str	Y	日期（输入格式：YYYYMMDD 比如：20181211）


输出参数

名称	类型	默认显示	描述
date	str	Y	日期
title	str	Y	标题
content	str	Y	内容


接口调用


pro = ts.pro_api()

df = pro.cctv_news(date='20181211')

"""
from sqlalchemy import BLOB
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from basis import *
from basis.tools import get_next_day_str


class get_alt_cctv_news(ts2db_by_date_template):
    table_name = 'hq_alt_cctv_news'  # 保存到数据库的库名
    table_name_cn = '新闻联播'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.cctv_news  # 告诉框架本接口对应的tushare的接口函数
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['trade_date']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, title'

    def ts2db_get_data(self):
        return self.params.ts_api(
            date=self.params.idate,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    def _run(self):
        self.params.idate = self.params.str_date
        itimes = 0
        result = 0
        while self.params.idate <= self.params.end_date:
            result, itimes = self._run_paginated(
                itimes,
                sleep_after_last=True,
            )
            self.params.idate = get_next_day_str(self.params.idate)
        return result

    def ts2db_auto_detect__check_downloaded_db_data(self):
        bp_key = getattr(
            self.params,
            "auto_detect__break_point_key",
            "trade_date",
        )
        try:
            table_tools = db_tools(self.params)
            if (
                not table_tools.has_table(self.params.table_name)
                or not table_tools.has_column(
                    self.params.table_name,
                    bp_key,
                )
            ):
                raise LookupError(
                    "table or breakpoint column is unavailable"
                )
            sqlstr_count = (
                f"select {bp_key}, count(*) as count from "
                f"{self.params.table_name} where {bp_key} between "
                f"'{self.params.str_date}' and '{self.params.end_date}' "
                f"group by {bp_key} order by {bp_key} asc"
            )
            data_status = pd.read_sql_query(
                sqlstr_count,
                self.params.db_engine,
            )
            data_status = self.ts2db_auto_detect__tag_bad_data(data_status)
            downloaded = {
                value.strftime("%Y%m%d")
                if hasattr(value, "strftime")
                else str(value).replace("-", "")
                for value in data_status[bp_key]
            }
            first_missing = None
            idate = self.params.str_date
            while idate <= self.params.end_date:
                if idate not in downloaded:
                    first_missing = idate
                    break
                idate = get_next_day_str(idate)
            if first_missing is None:
                data_need = pd.DataFrame(
                    columns=["str_date", "end_date"]
                )
            else:
                data_need = pd.DataFrame(
                    [
                        {
                            "str_date": first_missing,
                            "end_date": self.params.end_date,
                        }
                    ]
                )
        except Exception as ex:
            logging.warning(
                f"数据表 {self.params.table_name} "
                f"({self.params.table_name_cn}) 在断点续作时报错，"
                f"框架将继续处理。{ex}"
            )
            data_need = pd.DataFrame(
                [
                    {
                        "str_date": self.params.str_date,
                        "end_date": self.params.end_date,
                    }
                ]
            )
        self.params.auto_detect__datas_need_to_get = data_need
        return data_need

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'trade_date': DATE,
                                     'title': NVARCHAR(5000),
                                     'content': TEXT})

    def ts2db_clean_data(self):
        self.df.rename(columns={"date": "trade_date"}, inplace=True)  # 将日期字段修改为trade_date 不然缺失数据补全程序无法识别
        if self.df.content.str.len().max() > 21845:
            self.df['content'] = self.df.content.str[:21845]
            logging.warning(f"数据表{self.params.table_name} 中 content 列 超过最大长度 21845 ，已将超长的行截短！")


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250312', end_date='20250312')
    get_alt_cctv_news(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
