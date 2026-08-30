"""
Created on 2022年3月7日

@author: Jayden21 <jayden0721@163.com>

申万行业成分构成
接口：index_member
描述：申万行业成分
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

两个接口不能互相替代。本脚本负责已退役分类也能查询到的SW2014历史区间；
index_member_all没有src参数，不能补回SW2014。构建完整PIT时两个接口都要抓Y和N。



输入参数

名称	类型	必选	描述
index_code	str	N	指数代码
ts_code	str	N	股票代码
is_new	str	N	是否最新（默认为“Y是”）


输出参数

名称	类型	默认显示	描述
index_code	str	Y	指数代码
index_name	str	N	指数名称
con_code	str	Y	成分股票代码
con_name	str	Y	成分股票名称
in_date	str	Y	纳入日期
out_date	str	Y	剔除日期
is_new	str	N	是否最新Y是N否


接口示例


#获取黄金分类的成份股
df = pro.index_member(index_code='850531.SI')

#获取000001.SZ所属行业
df = pro.index_member(ts_code='000001.SZ')


数据示例

     index_code   index_name con_code  con_name    in_date    out_date
0   850531.SI         黄金  002155.SZ     湖南黄金  20140221     None
1   850531.SI         黄金  002237.SZ     恒邦股份  20140221     None
2   850531.SI         黄金  600311.SH     荣华实业  20140221     None
3   850531.SI         黄金  600489.SH     中金黄金  20140221     None
4   850531.SI         黄金  600687.SH    *ST刚泰  20140221     None
5   850531.SI         黄金  600766.SH     园城黄金  20140221     None
6   850531.SI         黄金  600988.SH     赤峰黄金  20140221     None
7   850531.SI         黄金  601899.SH     紫金矿业  20140221     None
8   850531.SI         黄金  601069.SH     西部黄金  20150129     None
9   850531.SI         黄金  600385.SH    *ST金泰  20160701     None
10  850531.SI         黄金  600547.SH     山东黄金  20140221     None

"""
from basis import *
from basis.init_data import PrerequisiteDataError


class get_idx_sw_member(ts2db_by_codelist_template):
    table_name = 'hq_idx_sw_member'  # 保存到数据库的库名
    table_name_cn = '申万行业成分构成'  # 接口名称

    def ts2db_init(self):
        self.params.ts_api = self.params.ts_pro.index_member  # 告诉框架本接口对应的tushare的接口函数
        self.params.one_time_rows_limit = 2000  # 官方文档单次最大返回量
        # -------------------------------------------数据初始化工作--------------------------------------------------------
        # # db_tools(self.params).truncate_table()  # 删除当前表
        # -------------------------------------------定义抓取代码列表------------------------------------------------------
        self.params.codelist = pd.read_sql_query(
            "select distinct index_code as ts_code "
            "from hq_idx_sw_classify where src='SW2014' "
            "and level in ('L1','L2','L3') order by index_code",
            self.params.db_engine,
        )
        if self.params.codelist.empty:
            raise PrerequisiteDataError(
                "hq_idx_sw_classify 缺少 SW2014 分类；请先运行 get_idx_sw_classify"
            )
        self.params.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据
        # -------------------------------------------定义数据库索引--------------------------------------------------------
        self.params.db_indexes = [['index_code'],
                                  ['con_code'],
                                  ['index_code', 'con_code', 'in_date']]
        # -------------------------------------------定义数据整理参数------------------------------------------------------
        self.params.deal_data__duplicate_data_key = 'index_code, con_code, in_date'

    # 每只证券抓取后，实现了写入数据库的逻辑，您也可以在此函数中添加一些写入文件或者数据预处理的操作作为扩展
    def ts2db_write_db(self):
        return self.df.to_sql(self.params.table_name, self.params.db_engine,
                              chunksize=1000000, if_exists='append', index=False,
                              dtype={'index_code': NVARCHAR(20),
                                     'index_name': NVARCHAR(20),
                                     'con_code': NVARCHAR(20),
                                     'con_name': NVARCHAR(20),
                                     'in_date': DATE,
                                     'out_date': DATE,
                                     'is_new': NVARCHAR(20)
                                     })

    def ts2db_get_data(self):
        return self.params.ts_api(
            index_code=self.params.code,
            is_new=self.params.is_new,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

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
    get_idx_sw_member().run()

    # end_str = input("加载完毕，请复核是否正确执行！
