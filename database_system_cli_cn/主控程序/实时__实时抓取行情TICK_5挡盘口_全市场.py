"""
@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.
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
