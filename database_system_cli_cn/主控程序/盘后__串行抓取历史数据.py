#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

from basis import *
from 主控程序.盘后__串行抓取接口列表 import get_data_by_reload_all, get_data_by_date

if __name__ == '__main__':
    # 初始化
    str_date = '20200101'
    end_date = init_currentDate() 
    #end_date = '20250801'

    params = _params(str_date=str_date, end_date=end_date)
    # 该函数集中了全清全重新加载的接口：加载列表信息，该类接口均为清空后重新加载，其中日期表建议加载一次就可以了
    get_data_by_reload_all()
    # 该函数集中了按日加载的接口：按日期段加载每日数据，需每日加载
    get_data_by_date(params)

    # 输出信息
    logging.info(f'数据加载完毕，处理日期：{str_date} 至 {end_date}')
