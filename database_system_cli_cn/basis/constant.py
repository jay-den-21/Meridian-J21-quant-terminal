"""
@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！
"""


class _config:
    def __init__(self):
        import os
        self.proj_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 获取当前项目路径
        from basis._yamler import yamler
        self.ts2db_config = yamler(f"{self.proj_path}/config/ts2db_config.yaml").read()
        self.dbPath = f"mysql+pymysql://" \
                      f"{self.ts2db_config['db_config']['user']}:" \
                      f"{self.ts2db_config['db_config']['pwd']}@" \
                      f"{self.ts2db_config['db_config']['host']}:" \
                      f"{self.ts2db_config['db_config']['port']}/" \
                      f"{self.ts2db_config['db_config']['db']}"
        self.log_path = self.format_config_str(self.ts2db_config['log_config']['log_path'])
        self.retry_times = self.ts2db_config['run_config']['retry_times']  # 重试次数
        self.retry_sleep_time = self.ts2db_config['run_config']['retry_sleep_time']  # 重试间隔时间

    def format_config_str(self, config_str):
        config_str = config_str.replace('$proj_path$', self.proj_path)
        return config_str


ts2db_config = _config()
