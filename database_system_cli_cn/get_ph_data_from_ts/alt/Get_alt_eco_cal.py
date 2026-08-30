"""
Created on 2021年7月18日

@author: Jayden21 <jayden0721@163.com>

财经日历
接口：eco_cal
描述：获取全球财经日历、包括经济事件数据更新
限量：单次最大获取100行数据
积分：2000积分可调取



输入参数

名称	类型	必选	描述
date	str	N	日期（YYYYMMDD格式）
start_date	str	N	开始日期
end_date	str	N	结束日期
currency	str	N	货币代码
country	str	N	国家（比如：中国、美国）
event	str	N	事件 （支持模糊匹配： *非农*）


输出参数

名称	类型	默认显示	描述
date	str	Y	日期
time	str	Y	时间
currency	str	Y	货币代码
country	str	Y	国家
event	str	Y	经济事件
value	str	Y	今值
pre_value	str	Y	前值
fore_value	str	Y	预测值


接口示例


pro = ts.pro_api()


#获取指定日期全球经济日历
df = pro.eco_cal(date='20200403')


#获取中国经济事件
df = pro.eco_cal(country='中国')

#获取美国非农数据
df = pro.eco_cal(event='美国季调后非农*', fields='date,time,country,event,value,pre_value,fore_value')


数据示例

    date      time    country                   event         value pre_value fore_value
0   20200410  09:30      中国      中国PPI年率(%)(年度)(三月)           -0.4%      -1.1%
1   20200410  09:30      中国      中国CPI月率(%)(月度)(三月)            0.8%      -0.7%
2   20200410  09:30      中国      中国CPI年率(%)(年度)(三月)            5.2%       4.9%
3   20200407  15:00      中国              中国外汇储备(美元)          3.107T
4   20200403  09:45      中国          中国财新服务业PMI(三月)  43.0      26.5
..       ...    ...     ...                     ...   ...       ...        ...
95  20200229  09:00      中国         中国官方非制造业PMI(二月)  29.6      54.1
96  20200229  09:00      中国          中国官方制造业PMI(二月)  35.7      50.0       46.0
97  20200229  09:00      中国           中国官方综合PMI(二月)  28.9      53.0
98  20200308  00:17      中国           中国贸易帐(美元)(二月)          47.21B     12.75B
99  20200308  00:17      中国  中国进口年率-美元计价(%)(年度)(二月)           16.5%      -9.0%


美国非农数据：

    date       time   country              event                 value pre_value fore_value
0   20200403  20:30      美国  美国季调后非农就业人口变动(三月)  -701K      275K      -100K
1   20200403  20:30      美国  美国季调后非农就业人口变动(三月)             273K      -100K
2   20200403  20:30      美国  美国季调后非农就业人口变动(三月)             273K      -124K
3   20200403  20:30      美国  美国季调后非农就业人口变动(三月)             273K      -100K
4   20200403  20:30      美国  美国季调后非农就业人口变动(三月)             273K      -123K
..       ...    ...     ...                ...    ...       ...        ...
95  20190308  21:30      美国  美国季调后非农就业人口变动(二月)             304K       181K
96  20190308  21:30      美国  美国季调后非农就业人口变动(二月)             304K       180K
97  20190308  21:30      美国  美国季调后非农就业人口变动(二月)             304K       185K
98  20190308  21:30      美国  美国季调后非农就业人口变动(二月)             304K       180K
99  20190308  21:30      美国  美国季调后非农就业人口变动(二月)             304K       185K

"""
from basis import *


class get_alt_eco_cal(ts2db_by_period_template):
    table_name = 'hq_alt_eco_cal'  # 保存到数据库的库名
    table_name_cn = '财经日历'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.eco_cal  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 100  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['trade_date'], ['trade_date', 'currency']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'trade_date, currency, country, event, value, pre_value, fore_value'

    # 实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        self.df = self.df[self.df.trade_date.str.find("试验性") == -1]
        ret = self.df.to_sql(self.params.table_name, self.params.db_engine,
                             chunksize=1000000, if_exists='append', index=False,
                             dtype={'trade_date': DATETIME,
                                    'time': NVARCHAR(20),
                                    'currency': NVARCHAR(20),
                                    'country': NVARCHAR(20),
                                    'event': NVARCHAR(200),
                                    'value': NVARCHAR(20),
                                    'pre_value': NVARCHAR(20),
                                    'fore_value': NVARCHAR(20)
                                    })

        return ret

    def ts2db_clean_data(self):
        self.df.rename(columns={'date': 'trade_date'}, inplace=True)
        self.df['trade_date'] = (self.df['trade_date'].str[:4] + '-' + self.df['trade_date'].str[4:6]
                                 + '-' + self.df['trade_date'].str[6:8] + ' ' + self.df['time'] + ':00')


if __name__ == '__main__':
    # 初始化
    params = _params(str_date='20250101', end_date='20250309')
    get_alt_eco_cal(params).run()

    # end_str = input("加载完毕，请复核是否正确执行！")
