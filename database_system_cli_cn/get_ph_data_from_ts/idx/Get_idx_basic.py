"""
Created on 2021年7月17日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

指数基本信息
接口：index_basic，可以通过数据工具调试和查看数据。
描述：获取指数基础信息，单次返回8000行。

输入参数

名称	类型	必选	描述
ts_code	str	N	指数代码
name	str	N	指数简称
market	str	N	交易所或服务商(默认SSE)
publisher	str	N	发布商
category	str	N	指数类别
输出参数

名称	类型	描述
ts_code	str	TS代码
name	str	简称
fullname	str	指数全称
market	str	市场
publisher	str	发布方
index_type	str	指数风格
category	str	指数类别
base_date	str	基期
base_point	float	基点
list_date	str	发布日期
weight_rule	str	加权方式
desc	str	描述
exp_date	str	终止日期
市场说明(market)

市场代码	说明
MSCI	MSCI指数
CSI	中证指数
SSE	上交所指数
SZSE	深交所指数
CICC	中金指数
SW	申万指数
OTH	其他指数
指数列表

主题指数
规模指数
策略指数
风格指数
综合指数
成长指数
价值指数
有色指数
化工指数
能源指数
其他指数
外汇指数
基金指数
商品指数
债券指数
行业指数
贵金属指数
农副产品指数
软商品指数
油脂油料指数
非金属建材指数
煤焦钢矿指数
谷物指数
接口使用


pro = ts.pro_api()

df = pro.index_basic(market='SW')
数据样例

       ts_code    name              market     publisher   category     base_date  base_point  \
5    801010.SI    农林牧渔             SW      申万   一级行业指数  19991230      1000.0
6    801011.SI    林业Ⅱ               SW     申万  二级行业指数  19991230      1000.0
7    801012.SI    农产品加工           SW      申万   二级行业指数  19991230      1000.0
8    801013.SI    农业综合Ⅱ           SW      申万  二级行业指数  19991230      1000.0
9    801014.SI    饲料Ⅱ               SW     申万  二级行业指数  19991230      1000.0
10   801015.SI    渔业                 SW      申万   二级行业指数  19991230      1000.0
11   801016.SI    种植业               SW      申万   二级行业指数  19991230      1000.0
12   801017.SI    畜禽养殖Ⅱ           SW      申万  二级行业指数  20111010      1000.0
13   801018.SI    动物保健Ⅱ           SW      申万研  二级行业指数  19991230      1000.0
14   801020.SI    采掘                 SW      申万   一级行业指数  19991230      1000.0
15   801021.SI    煤炭开采Ⅱ           SW      申万  二级行业指数  19991230      1000.0
16   801022.SI    其他采掘Ⅱ           SW      申万  二级行业指数  19991230      1000.0
17   801023.SI    石油开采Ⅱ           SW      申万  二级行业指数  19991230      1000.0
18   801024.SI    采掘服务Ⅱ           SW      申万  二级行业指数  19991230      1000.0
"""
from basis import *


class get_idx_basic(ts2db_by_limit_template):
    table_name = 'hq_idx_basic'  # 保存到数据库的库名
    table_name_cn = '指数基本信息'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        # self.params.auto_detect__break_point_type = 0
        self.params.ts_api = self.params.ts_pro.index_basic  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 8000  # 官方文档单次最大返回量
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
                                     'name': NVARCHAR(250),
                                     'market': NVARCHAR(20),
                                     'publisher': NVARCHAR(250),
                                     'category': NVARCHAR(50),
                                     'base_date': DATE,
                                     'base_point': DECIMAL(25, 4),
                                     'list_date': DATE})

    def ts2db_get_data(self):
        df = self.params.ts_api(**{
            "ts_code": "",
            "market": "",
            "publisher": "",
            "category": "",
            "name": "",
            "limit": self.params.one_time_rows_limit,
            "offset": self.params.offset
        }, fields=[
            "ts_code",
            "name",
            "market",
            "publisher",
            "category",
            "base_date",
            "base_point",
            "list_date",
            "fullname",
            "index_type",
            "weight_rule",
            "desc",
            "exp_date"
        ])
        return df


if __name__ == '__main__':
    get_idx_basic(_params()).run()
