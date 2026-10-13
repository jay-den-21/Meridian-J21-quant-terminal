 #!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

from basis import *
from 主控程序.盘后__串行抓取接口列表 import get_data_by_reload_all, get_data_by_date

if __name__ == '__main__':
    # 初始化
    # 指定日期是注意日期格式应为：'20210901'
    # str_date = init_currentDate()
    str_date = init_currentDate()
    end_date = init_currentDate()

    params = _params(str_date=str_date, end_date=end_date)

    # 该函数集中了全清全重新加载的接口：加载列表信息，该类接口均为清空后重新加载，其中日期表建议加载一次就可以了
    get_data_by_reload_all()
    # 该函数集中了按日加载的接口：按日期段加载每日数据，需每日加载
    get_data_by_date(params)

