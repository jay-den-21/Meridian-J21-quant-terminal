"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.

同花顺概念和行业指数
接口：ths_index
描述：获取同花顺板块指数。注：数据版权归属同花顺，如做商业用途，请主动联系同花顺，如需帮助请联系微信migedata 。
限量：本接口需获得5000积分，单次最大5000，一次可提取全部数据，请勿循环提取。



输入参数

名称	类型	必选	描述
ts_code	str	N	指数代码
exchange	str	N	市场类型A-a股 HK-港股 US-美股
type	str	N	指数类型 N-板块指数 I-行业指数 S-同花顺特色指数


输出参数

名称	类型	默认显示	描述
ts_code	str	Y	代码
name	str	Y	名称
count	int	Y	成分个数
exchange	str	Y	交易所
list_date	str	Y	上市日期
type	str	Y	N概念指数S特色指数


接口示例


pro = ts.pro_api()

df = pro.ths_index()


数据样例

       ts_code     name       count exchange list_date type
0    885835.TI     参股银行    126        A  20190416    N
1    885472.TI    上海自贸区     51        A  20130813    N
2    885788.TI     网络直播     63        A  20180312    N
3    885881.TI      云办公     29        A  20200203    N
4    885785.TI     小米概念     91        A  20180306    N
..         ...      ...    ...      ...       ...  ...
266  885566.TI      大飞机     58        A  20140519    N
267  885841.TI  草地贪夜蛾防治     18        A  20190517    N
268  885760.TI    装配式建筑     50        A  20170918    N
269  885909.TI     辅助生殖     15        A  20201023    N
270  885883.TI   医疗废物处理     25        A  20200207    N
"""
from basis import *


class get_ths_index(ts2db_by_limit_template):
    table_name = 'hq_ths_index'  # 保存到数据库的库名
    table_name_cn = '同花顺概念和行业指数'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.ths_index  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 5000  # 官方文档单次最大返回量
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'ts_code': NVARCHAR(20),
                                     'name': NVARCHAR(200),
                                     'count': DECIMAL(25, 4),
                                     'exchange': NVARCHAR(20),
                                     'list_date': DATE,
                                     'type': NVARCHAR(10),
                                     })


if __name__ == '__main__':
    get_ths_index().run()
