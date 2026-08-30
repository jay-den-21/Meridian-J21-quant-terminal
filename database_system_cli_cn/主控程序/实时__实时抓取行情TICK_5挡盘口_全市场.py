"""
@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！
"""
__author__ = "Jayden21 <jayden0721@163.com>"

import os
import sys


# 要在命令行运行，必须加上下面这两句
sys.path.append(os.path.split(os.path.abspath(os.path.dirname(__file__)))[0])  # 加载项目根目录
sys.path.append(os.path.split(os.path.split(os.path.abspath(os.path.dirname(__file__)))[0])[0])

from get_rt_data_from_ts.Get_rt_stk_quote_tick__sina import get_rt_stk_quote_tick

if __name__ == '__main__':
    # 初始化
    get_rt_stk_quote_tick().run()
