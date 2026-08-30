"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

公募基金列表
接口：fund_basic，可以通过数据工具调试和查看数据。
描述：获取公募基金数据列表，包括场内和场外基金
积分：用户需要2000积分才可以调取，单次最大可以提取15000条数据，5000积分以上权限更高，具体请参阅积分获取办法

输入参数

名称	类型	必选	描述
market	str	N	交易市场: E场内 O场外（默认E）
status	str	N	存续状态 D摘牌 I发行 L上市中
输出参数

名称	类型	默认显示	描述
ts_code	str	Y	基金代码
name	str	Y	简称
management	str	Y	管理人
custodian	str	Y	托管人
fund_type	str	Y	投资类型
found_date	str	Y	成立日期
due_date	str	Y	到期日期
list_date	str	Y	上市时间
issue_date	str	Y	发行日期
delist_date	str	Y	退市日期
issue_amount	float	Y	发行份额(亿)
m_fee	float	Y	管理费
c_fee	float	Y	托管费
duration_year	float	Y	存续期
p_value	float	Y	面值
min_amount	float	Y	起点金额(万元)
exp_return	float	Y	预期收益率
benchmark	str	Y	业绩比较基准
status	str	Y	存续状态D摘牌 I发行 L已上市
invest_type	str	Y	投资风格
type	str	Y	基金类型
trustee	str	Y	受托人
purc_startdate	str	Y	日常申购起始日
redm_startdate	str	Y	日常赎回起始日
market	str	Y	E场内O场外
"""
from basis import *


class get_fund_basic(ts2db_by_limit_template):
    table_name = 'hq_fund_basic'  # 保存到数据库的库名
    table_name_cn = '公募基金列表'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.fund_basic  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 15000  # 官方文档单次最大返回量
        self.params.table_name = self.table_name
        self.params.table_name_cn = self.table_name_cn
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
                                     'name': NVARCHAR(255),
                                     'management': NVARCHAR(255),
                                     'custodian': NVARCHAR(255),
                                     'fund_type': NVARCHAR(20),
                                     'found_date': DATE,
                                     'due_date': DATE,
                                     'list_date': DATE,
                                     'issue_date': DATE,
                                     'delist_date': DATE,
                                     'issue_amount': DECIMAL(25, 4),
                                     'm_fee': DECIMAL(25, 4),
                                     'c_fee': DECIMAL(25, 4),
                                     'duration_year': DECIMAL(25, 4),
                                     'p_value': DECIMAL(25, 4),
                                     'min_amount': DECIMAL(25, 4),
                                     'exp_return': DECIMAL(25, 4),
                                     'benchmark': NVARCHAR(500),
                                     'status': NVARCHAR(20),
                                     'invest_type': NVARCHAR(255),
                                     'type': NVARCHAR(255),
                                     'trustee': NVARCHAR(255),
                                     'purc_startdate': DATE,
                                     'redm_startdate': DATE,
                                     'market': NVARCHAR(20)})


if __name__ == '__main__':
    get_fund_basic().run()
