"""
@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！
"""
from datetime import datetime
from basis.constant import ts2db_config


class _params:
    def __init__(self, str_date='20250101', str_time=None, end_date='20250101', end_time=None):
        self.ts = None  # ts接口
        self.ts_pro = None  # ts_pro接口
        self.ts_api = None  # 当前接口使用的api

        self.server = 'ts'  # 数据源服务器，默认 ts：tushare，xc：湘财，jx：镜像源
        self.table_name = None
        self.table_name_cn = ''

        self.str_date = self._validate_date(str_date)
        self.str_time = str_time
        self.end_date = self._validate_date(end_date)
        self.end_time = end_time

        self.one_time_rows_limit = 50000  # 该接口限制每次调用，最大获取数据量
        self.times_limit_in_1min = 100000  # 该接口限制,每分钟最多调用次数
        self.retry_sleep_time = ts2db_config.ts2db_config['run_config']['retry_sleep_time']  # 重试间隔时间 61
        self.retry_times = ts2db_config.ts2db_config['run_config']['retry_times']
        self.how_many_codes_onetime = 1  # 一次调用最多获取多少个代码对应的数据，针对可以一次传多个代码的接口的快速取数
        self.rt_deal_duplicate_data = False  # 是否实时内存去重数据

        self.market = 'CN'
        self.src = 'sina'  # 数据源 （sina-新浪 dc-东方财富，默认sina）
        self.code = None  # 每次抓取所使用的代码或代码列表
        self.codelist = None

        self.write_db = ''  # 存数据的实现函数
        self.get_data = ''  # 取数据的实现函数
        self.deal_data__duplicate_data_key = None  # 该接口用于框架自动去重的键字,None表示不去重
        self.db_indexes = None  # 该接口用于框架自动建立索引，None表示不用建立索引

        self.db_engine = None

        # 以下是框架自检参数，不要随意修改：
        self.auto_detect__break_point_type = 1  # 自动断点续作  1：自动分析已下载数据并进行断点续作  2：每日只加载一次，自动识别当日是否已运行 0：关闭该功能
        self.auto_detect__break_point_key = 'trade_date'  # 自动断点续作关键字
        self.auto_detect__break_point_chg_pct = 0.1  # 自检数据变动比率
        self.data_already_ok = False  # 数据是否已经ok了，不用再重复抓取
        self.auto_detect__otrl__already = False  # 是否已经进行otrl检测

    def get_idate_iso(self):
        return f"{self.idate[:4]}-{self.idate[4:6]}-{self.idate[6:]}"

    def get_str_date_iso(self):
        return f"{self.str_date[:4]}-{self.str_date[4:6]}-{self.str_date[6:]}"

    def get_end_date_iso(self):
        return f"{self.end_date[:4]}-{self.end_date[4:6]}-{self.end_date[6:]}"

    def get_str_date_date_type(self):
        return datetime.strptime(self.str_date, '%Y%m%d')

    def get_end_date_date_type(self):
        return datetime.strptime(self.end_date, '%Y%m%d')

    def _validate_date(self, date_str):
        """验证日期格式是否为YYYYMMDD"""
        try:
            # 尝试将字符串转换为datetime对象以验证格式
            datetime.strptime(date_str, '%Y%m%d')
            return date_str
        except Exception as ex:
            import logging
            logging.error(f"日期格式不正确: {date_str} 应为 YYYYMMDD 格式 例如：20250618 详细错误信息 {ex}")
            exit(99)




