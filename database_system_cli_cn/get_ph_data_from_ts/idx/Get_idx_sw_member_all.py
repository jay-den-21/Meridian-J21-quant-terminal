"""
Created on 2022年3月7日

@author: Jayden21 <jayden0721@163.com>

申万行业成分构成(分级)
接口：index_member_all
描述：按三级分类提取申万行业成分，可提供某个分类的所有成分，也可按股票代码提取所属分类，参数灵活
限量：单次最大2000行，总量不限制
权限：用户需2000积分可调取，积分获取方法请参阅积分获取办法


index_member 与 index_member_all 对比

项目 | index_member | index_member_all
--- | --- | ---
查询方式 | 按单个行业指数或股票查询 | 按L1/L2/L3行业或股票查询
结果结构 | 扁平的index_code/con_code | 分级的l1/l2/l3/ts_code
PIT字段 | in_date/out_date/is_new | in_date/out_date/is_new
数据库表 | hq_idx_sw_member | hq_idx_sw_member_all
项目定位 | SW2014历史区间权威来源 | SW2021分级历史区间权威来源

本脚本负责SW2021分级历史区间，按L1查询后保留L1/L2/L3。
它没有src参数，不能替代index_member恢复SW2014；构建完整PIT时两个接口都要抓Y和N。



输入参数

名称	类型	必选	描述
l1_code	str	N	一级行业代码
l2_code	str	N	二级行业代码
l3_code	str	N	三级行业代码
ts_code	str	N	股票代码
is_new	str	N	是否最新（默认为“Y是”）


输出参数

名称	类型	默认显示	描述
l1_code	str	Y	一级行业代码
l1_name	str	Y	一级行业名称
l2_code	str	Y	二级行业代码
l2_name	str	Y	二级行业名称
l3_code	str	Y	三级行业代码
l3_name	str	Y	三级行业名称
ts_code	str	Y	成分股票代码
name	str	Y	成分股票名称
in_date	str	Y	纳入日期
out_date	str	Y	剔除日期
is_new	str	Y	是否最新Y是N否

"""
from basis import *


class get_idx_sw_member_all(ts2db_by_codelist_template):
    table_name = 'hq_idx_sw_member_all'  # 保存到数据库的库名
    table_name_cn = '申万行业成分构成_all'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.index_member_all  # 告诉框架本接口对应的tushare的接口函数
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = init_data.init_codeList(self.params.db_engine, 'hq_idx_sw_classify')  # 必须初始化，需要遍历的列表
        self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据
        self.params.one_time_rows_limit = 2000  # 官方文档单次最大返回量
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['ts_code'],
                                  ['l1_code'],
                                  ['l2_code'],
                                  ['l3_code']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'ts_code, l1_code, l2_code, l3_code, in_date'

    # 每只证券抓取后，实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'l1_code': NVARCHAR(20),
                                     'l1_name': NVARCHAR(50),
                                     'l2_code': NVARCHAR(20),
                                     'l2_name': NVARCHAR(50),
                                     'l3_code': NVARCHAR(20),
                                     'l3_name': NVARCHAR(50),
                                     'ts_code': NVARCHAR(20),
                                     'name': NVARCHAR(50),
                                     'in_date': DATE,
                                     'out_date': DATE,
                                     'is_new': NVARCHAR(2)
                                     })

    def ts2db_get_data(self):
        return self.params.ts_api(l1_code=self.params.code,
                                  is_new=self.params.is_new,
                                  limit=self.params.one_time_rows_limit,
                                  offset=self.params.offset)

    def _run(self):
        missing = object()
        previous_is_new = getattr(self.params, 'is_new', missing)
        result = 0
        try:
            for is_new in ('Y', 'N'):
                self.params.is_new = is_new
                result = super()._run()
            return result
        finally:
            if previous_is_new is missing:
                delattr(self.params, 'is_new')
            else:
                self.params.is_new = previous_is_new


if __name__ == '__main__':
    get_idx_sw_member_all().run()

    # end_str = input("加载完毕，请复核是否正确执行！
