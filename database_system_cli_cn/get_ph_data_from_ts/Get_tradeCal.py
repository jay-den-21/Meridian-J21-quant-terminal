"""
Created on 2021年8月04日

@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！

交易日历
接口：trade_cal
描述：获取各大交易所交易日历数据,默认提取的是上交所

输入参数

名称	类型	必选	描述
exchange	str	N	交易所 SSE上交所,SZSE深交所,CFFEX 中金所,SHFE 上期所,CZCE 郑商所,DCE 大商所,INE 上能源,IB 银行间,XHKG 港交所
start_date	str	N	开始日期 （格式：YYYYMMDD 下同）
end_date	str	N	结束日期
is_open	str	N	是否交易 '0'休市 '1'交易
输出参数

名称	类型	默认显示	描述
exchange	str	Y	交易所 SSE上交所 SZSE深交所
cal_date	str	Y	日历日期
is_open	str	Y	是否交易 0休市 1交易
pretrade_date	str	N	上一个交易日
接口示例
pro = ts.pro_api()
df = pro.trade_cal(exchange='', start_date='20180101', end_date='20181231')
或者
df = pro.query('trade_cal', start_date='20180101', end_date='20181231')
"""
from basis import *


class get_tradeCal(ts2db_by_limit_template):
    table_name = 'hq_trade_cal'  # 保存到数据库的库名
    table_name_cn = '交易日历'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.trade_cal  # 告诉框架本接口对应的tushare的接口函数
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['cal_date']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'exchange, cal_date'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'exchange': NVARCHAR(20),
                                     'cal_date': DATE,
                                     'is_open': NVARCHAR(1),
                                     'pretrade_date': DATE})


if __name__ == '__main__':
    get_tradeCal(_params()).run()
