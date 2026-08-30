#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)


__author__ = "Jayden21 <jayden0721@163.com>"

import os
import sys

# 要在命令行运行，必须加上下面这两句
sys.path.append(os.path.split(os.path.abspath(os.path.dirname(__file__)))[0])  # 加载项目根目录
sys.path.append(os.path.split(os.path.split(os.path.abspath(os.path.dirname(__file__)))[0])[0])

from basis import *

from deal_data.deal_duplicatetData import deal_duplicate_data
from deal_data.deal_lostData import deal_lost_data
from get_ph_data_from_ts.stk.Get_stk_daily import get_stk_daily
from get_ph_data_from_ts.stk.Get_stk_daily_basic import get_stk_daily_basic

def deal_wrong_date(params):
    params.db_engine = init_db()
    # 整理重复数据和该日期段缺失数据
    logging.info('====================================开始数据整理========================================')
    # 这里需要设置接口名和主键值得二维数组
    # 数据去重配置
    tableDict_deal_duplicate_data = [
        # 股票
        ['hq_stk_daily', 'trade_date, ts_code'],
        ['hq_stk_daily_basic', 'trade_date, ts_code'],
        # ['hq_stk_limit_list', 'trade_date, ts_code'],
        # ['hq_stk_limit_list', 'trade_date, ts_code'],
        # ['hq_stk_moneyflow', 'trade_date, ts_code'],
        # # 可转债
        # ['hq_cb_daily', 'trade_date, ts_code'],
        # # 指数
        # ['hq_idx_weight', 'index_code, con_code, trade_date'],
        # # 回购
        # ['hq_repo_daily', 'trade_date, ts_code'],
        # # 财务
        # # ['hq_financial_fina_indicator', 'ts_code, ann_date, update_flag'],
        # # ['hq_financial_income', 'ts_code, ann_date, f_ann_date, end_date, update_flag'],
        # # 港股
        # ['hq_hk_daily', 'trade_date, ts_code'],
        # # ['hq_hk_ccass_hold_detail', 'ts_code, trade_date, col_participant_id'],
        # #  港股通
        # ['hq_hsgt_north_top10', 'trade_date,ts_code,market_type'],
        # # 基金
        # ['hq_fund_daily', 'trade_date, ts_code'],
        # # 期权
        # ['hq_fut_daily', 'trade_date, ts_code'],
        # # 同花顺
        # ['hq_ths_daily', 'ts_code, trade_date'],
        # ['hq_ths_index', 'ts_code, list_date'],
        # # ['hq_ths_member', 'ts_code, code'],
        # # 另类数据
        # ['hq_alternative_cctv_news', 'trade_date, title'],
        # # 其他
        # ['hq_adj_factor', 'trade_date, ts_code'],
        # ['hq_topinst', 'trade_date, ts_code, exalter, side, net_buy, reason'],
        # ['hq_toplist', 'trade_date, ts_code, reason']
    ]

    deal_duplicate_data(params, tableDict_deal_duplicate_data)
    # 这里，按传入的日期段和接口表列表和对应的函数入口，补全缺失数据,在tableDict_date字典里的接口就是要补全的接口，
    # tableDict_code里面有没有登记没关系，只是个效率优化手段
    # 数据补全配置（按日期补全）：
    # tableDict_date_deal_lost_data = {
    #     'hq_stk_daily': get_stk_daily(params).run(),
    #     'hq_stk_daily_basic': get_stk_daily_basic(params).run(),
    # }
    # 数据补全配置（按代码补全），该部分主要为效率考虑，如需使用需实现按代码抓取接口，实际看来用处不大，可以不使用
    # tableDict_code_deal_lost_data = {
    #     # 'hq_stk_daily_basic': get_Daily_Basic_By_Code,
    #     # 'hq_stk_daily': get_Daily_By_Code,
    #     # 'hq_adj_factor': get_Adj_Factor_By_Code,
    #     # 'hq_fund_daily': get_Fund_Daily_By_Code
    # }
    # deal_lost_data(params, tableDict_date_deal_lost_data, tableDict_code_deal_lost_data)


if __name__ == '__main__':
    # 初始化
    # 指定日期是注意日期格式应为：'20210901'
    params = _params()
    params.str_date = '20240101'
    params.end_date = init_currentDate()
    # 按日期段进行数据整理
    deal_wrong_date(params)

