"""
Created on 2021年10月18日

@author: Jayden21 <jayden0721@163.com>

申万行业分类
接口：index_classify
描述：获取申万行业分类，可以获取申万2014年版本（28个一级分类，104个二级分类，227个三级分类）和2021年本版（31个一级分类，134个二级分类，346个三级分类）列表信息
权限：用户需2000积分可以调取，具体请参阅积分获取办法



输入参数

名称	类型	必选	描述
index_code	str	N	指数代码
level	str	N	行业分级（L1/L2/L3）
parent_code	str	N	父级代码（一级为0）
src	str	N	指数来源（SW2014：申万2014年版本，SW2021：申万2021年版本）


输出参数

名称	类型	默认显示	描述
index_code	str	Y	指数代码
industry_name	str	Y	行业名称
parent_code	str	Y	父级代码
level	str	Y	行业名称
industry_code	str	Y	行业代码
is_pub	str	Y	是否发布了指数
src	str	N	行业分类（SW申万）


接口示例


#获取申万一级行业列表
df = pro.index_classify(level='L1', src='SW2021')

#获取申万二级行业列表
df = pro.index_classify(level='L2', src='SW2021')

#获取申万三级级行业列表
df = pro.index_classify(level='L3', src='SW2021')


数据示例

     index_code industry_name level
0   801020.SI            采掘    L1
1   801030.SI            化工    L1
2   801040.SI            钢铁    L1
3   801050.SI          有色金属    L1
4   801710.SI          建筑材料    L1
5   801720.SI          建筑装饰    L1
6   801730.SI          电气设备    L1
7   801890.SI          机械设备    L1
8   801740.SI          国防军工    L1
9   801880.SI            汽车    L1
10  801110.SI          家用电器    L1
11  801130.SI          纺织服装    L1
12  801140.SI          轻工制造    L1
13  801200.SI          商业贸易    L1
14  801010.SI          农林牧渔    L1
15  801120.SI          食品饮料    L1
16  801210.SI          休闲服务    L1
17  801150.SI          医药生物    L1
18  801160.SI          公用事业    L1
19  801170.SI          交通运输    L1
20  801180.SI           房地产    L1
21  801080.SI            电子    L1
22  801750.SI           计算机    L1
23  801760.SI            传媒    L1
24  801770.SI            通信    L1
25  801780.SI            银行    L1
26  801790.SI          非银金融    L1
27  801230.SI            综合    L1

"""
from basis import *


class get_idx_sw_classify(ts2db_by_limit_template):
    table_name = 'hq_idx_sw_classify'  # 保存到数据库的库名
    table_name_cn = '申万行业分类'  # 接口名称

    # 初始化的工作都放在这里
    def ts2db_init(self):
        self.params.auto_detect__break_point_type = 0
        self.params.ts_api = self.params.ts_pro.index_classify
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['index_code'],
                                  ['src', 'level', 'index_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'src, level, index_code'

    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              if_exists='append', chunksize=10000, index=False,
                              dtype={'index_code': NVARCHAR(20),
                                     'industry_name': NVARCHAR(20),
                                     'parent_code': NVARCHAR(20),
                                     'level': NVARCHAR(20),
                                     'industry_code': NVARCHAR(20),
                                     'is_pub': NVARCHAR(20),
                                     'src': NVARCHAR(20)
                                     })

    def ts2db_get_data(self):
        return self.params.ts_api(
            level=self.params.level,
            src=self.params.classification_src,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    def _run(self):
        missing = object()
        previous_level = getattr(self.params, 'level', missing)
        previous_src = getattr(self.params, 'classification_src', missing)
        result = 0
        try:
            for classification_src in ('SW2014', 'SW2021'):
                self.params.classification_src = classification_src
                for level in ('L1', 'L2', 'L3'):
                    self.params.level = level
                    result, _ = self._run_paginated()
            return result
        finally:
            if previous_level is missing:
                delattr(self.params, 'level')
            else:
                self.params.level = previous_level
            if previous_src is missing:
                delattr(self.params, 'classification_src')
            else:
                self.params.classification_src = previous_src


if __name__ == '__main__':
    get_idx_sw_classify().run()
