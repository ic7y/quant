# coding: utf8

"""
普量学院量化投资课程系列案例源码包
普量学院版权所有
仅用于教学目的，严禁转发和用于盈利目的，违者必究
©Plouto-Quants All Rights Reserved

普量学院助教微信：niuxiaomi3
"""

"""
单品种随机入市策略：使用聚宽平台提供的API实现，仅适用于聚宽平台。
回测前必须在聚宽上设置以下参数：
- 回测开始日期
- 回测结束日期
- 每分钟回测
详细用法请参考聚宽使用手册-如何创建一个策略。
https://www.joinquant.com/faq#%E5%A6%82%E4%BD%95%E7%BC%96%E5%86%99%E4%B8%80%E4%B8%AA%E6%9C%80%E7%AE%80%E5%8D%95%E7%9A%84%E7%AD%96%E7%95%A5
"""

# 导入函数库
import jqdata
import pandas as pd
from pandas.core.frame import DataFrame
import random


# 初始化函数，设定基准等等
def initialize(context):
    set_params(context)
    set_benchmark(get_future_code(g.future_symbol))
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='index_futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之23
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023, close_today_commission=0.0023),
                   type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', 0.15)

    # 运行函数（reference_security为运行时间的参考标的）
    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security=get_future_code(g.future_symbol))
    # 开盘时运行
    run_daily(while_open, time='every_bar', reference_security=get_future_code(g.future_symbol))
    # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security=get_future_code(g.future_symbol))


# 设置全局参数
def set_params(context):
    # 设置交易标的合约简称
    g.future_symbol = 'RB'
    # 当日的主力合约
    g.future = None
    # 最近一次交易的合约
    g.last_future = None
    # 多头仓位
    g.long_position = False
    # 空头仓位
    g.short_position = False
    # 设置真实波幅的时间窗口
    g.atr_window = 10
    # 波动性倍数
    g.ema_times = 3
    # 计算波动性得数的时间窗口
    g.ema_window = 10
    # 止损价格
    g.price_mark = [0, 0]
    # 头寸风险因子
    g.pos_factor = 0.01


# 开盘时运行函数
def while_open(context):
    # 获取标的当日的主力合约
    g.future = get_dominant_future(g.future_symbol)
    if g.last_future is None:
        g.last_future = g.future
    elif g.last_future != g.future:
        # 主力合约变更直接平仓。下次掷硬币重新入场。平仓后重置参数
        if g.long_position:
            order_target(g.last_future, 0, side='long')
            g.long_position = False
        elif g.short_position:
            order_target(g.last_future, 0, side='short')
            g.short_position = False
        g.last_future = g.future
        g.price_mark = [0, 0]
        log.info("主力合约改变，平仓！")

    ## 止盈止损判断
    # 最近1根K线的收盘价
    close_price = attribute_history(g.future, 1, '1m', 'close').values[0]
    if g.long_position:
        # 多头仓位上浮止损线
        g.price_mark[0] = max(close_price - g.price_mark[1], g.price_mark[0])
        # log.info("更新多头仓位上移止损线, price_mark=%s ", g.price_mark)

        # 最新价触发止损
        if get_current_data()[g.future].last_price < g.price_mark[0]:
            order_target(g.future, 0, side='long')
            log.info("多头平仓，时间=%s, last_price=%s, price_mark=%s ", str(context.current_dt.time()),
                     get_current_data()[g.future].last_price, g.price_mark)
            g.long_position = False

    if g.short_position:
        # 空头仓位下调止损线
        g.price_mark[0] = min(close_price + g.price_mark[1], g.price_mark[0])
        # log.info("空头仓位下移止损线, price_mark=%s ", g.price_mark)

        # 最新价触发止损
        if get_current_data()[g.future].last_price > g.price_mark[0]:
            order_target(g.future, 0, side='short')
            log.info("空头平仓，时间=%s, last_price=%s, price_mark=%s ", str(context.current_dt.time()),
                     get_current_data()[g.future].last_price, g.price_mark)
            g.short_position = False

    if g.long_position or g.short_position:
        return

    ## 盘中开仓
    trade(context)


# 开仓
def trade(context):
    # 当月合约
    future = g.future
    # 获取当月合约交割日期
    end_date = get_CCFX_end_date(future)
    # 当月合约交割日当天不开仓
    if (context.current_dt.date() == end_date):
        return

    # 查询历史数据
    price_list = attribute_history(g.future, g.atr_window + 1 + g.ema_window - 1, '1d', ['close', 'high', 'low'])

    # 如果没有数据，返回
    if len(price_list) == 0:
        return
    # 计算近10根K线的ATR(20)
    ATR_10 = []
    for i in range(0, g.ema_window):
        ATR_10.append(get_ATR(price_list[i: g.atr_window + i + 1], g.atr_window))

    # 计算EMA(ATR, 10)
    EMA = pd.ewma(DataFrame({"atr": ATR_10}), g.ema_window)['atr'].iloc[-1]
    # log.info("EMA=%s", EMA)

    # 开仓
    # 得到开仓信号：模拟随机掷硬币, 0是开空仓，1是开多仓
    open_signal = random.randint(0, 1)
    log.info("open_signal=%s", open_signal)
    # 多头开仓
    if open_signal == 1:
        # 多头开仓
        unit = get_unit(context.portfolio.total_value, ATR_10[-1], g.future_symbol)
        order(future, unit, side='long')
        if context.portfolio.positions[future].total_amount > 0:
            g.price_mark = [context.portfolio.long_positions[future].price - g.ema_times * EMA, g.ema_times * EMA]
            g.long_position = True
            log.info('多头建仓成功:', context.current_dt.time(), future, unit, g.long_position, g.long_position)
            log.info('初始止损:%s', g.price_mark)
            g.last_future = future
    # 空头开仓
    elif open_signal == 0:
        # 空头开仓
        unit = get_unit(context.portfolio.total_value, ATR_10[-1], g.future_symbol)
        order(future, unit, side='short')
        if context.portfolio.short_positions[future].total_amount > 0:
            g.price_mark = [context.portfolio.short_positions[future].price + g.ema_times * EMA, g.ema_times * EMA]
            g.short_position = True
            log.info('空头建仓成功:', context.current_dt.time(), future, unit, g.long_position, g.short_position)
            log.info('初始止损:%s', g.price_mark)
            g.last_future = future


# 开盘前运行
def before_market_open(context):
    pass


# 收盘后运行
def after_market_close(context):
    pass


########################## 自定义函数 #################################
# 获取当天时间正在交易的期货主力合约
def get_future_code(symbol):
    future_code_list = {'A': 'A9999.XDCE', 'AG': 'AG9999.XSGE', 'AL': 'AL9999.XSGE', 'AU': 'AU9999.XSGE',
                        'B': 'B9999.XDCE', 'BB': 'BB9999.XDCE', 'BU': 'BU9999.XSGE', 'C': 'C9999.XDCE',
                        'CF': 'CF9999.XZCE', 'CS': 'CS9999.XDCE', 'CU': 'CU9999.XSGE', 'ER': 'ER9999.XZCE',
                        'FB': 'FB9999.XDCE', 'FG': 'FG9999.XZCE', 'FU': 'FU9999.XSGE', 'GN': 'GN9999.XZCE',
                        'HC': 'HC9999.XSGE', 'I': 'I9999.XDCE', 'IC': 'IC9999.CCFX', 'IF': 'IF9999.CCFX',
                        'IH': 'IH9999.CCFX', 'J': 'J9999.XDCE', 'JD': 'JD9999.XDCE', 'JM': 'JM9999.XDCE',
                        'JR': 'JR9999.XZCE', 'L': 'L9999.XDCE', 'LR': 'LR9999.XZCE', 'M': 'M9999.XDCE',
                        'MA': 'MA9999.XZCE', 'ME': 'ME9999.XZCE', 'NI': 'NI9999.XSGE', 'OI': 'OI9999.XZCE',
                        'P': 'P9999.XDCE', 'PB': 'PB9999.XSGE', 'PM': 'PM9999.XZCE', 'PP': 'PP9999.XDCE',
                        'RB': 'RB9999.XSGE', 'RI': 'RI9999.XZCE', 'RM': 'RM9999.XZCE', 'RO': 'RO9999.XZCE',
                        'RS': 'RS9999.XZCE', 'RU': 'RU9999.XSGE', 'SF': 'SF9999.XZCE', 'SM': 'SM9999.XZCE',
                        'SN': 'SN9999.XSGE', 'SR': 'SR9999.XZCE', 'T': 'T9999.CCFX', 'TA': 'TA9999.XZCE',
                        'TC': 'TC9999.XZCE', 'TF': 'TF9999.CCFX', 'V': 'V9999.XDCE', 'WH': 'WH9999.XZCE',
                        'WR': 'WR9999.XSGE', 'WS': 'WS9999.XZCE', 'WT': 'WT9999.XZCE', 'Y': 'Y9999.XDCE',
                        'ZC': 'ZC9999.XZCE', 'ZN': 'ZN9999.XSGE'}
    try:
        return future_code_list[symbol]
    except:
        return 'WARNING: 无此合约'


# 获取金融期货合约到期日
def get_CCFX_end_date(fature_code):
    # 获取金融期货合约到期日
    return get_security_info(fature_code).end_date


# 计算ATR
def get_ATR(price_list, T):
    TR_list = [max(price_list['high'].iloc[i] - price_list['low'].iloc[i],
                   abs(price_list['high'].iloc[i] - price_list['close'].iloc[i - 1]),
                   abs(price_list['close'].iloc[i - 1] - price_list['low'].iloc[i])) for i in range(1, T + 1)]
    ATR = np.array(TR_list).mean()
    return ATR


# 计算头寸规模
def get_unit(cash, ATR, symbol):
    future_coef_list = {'A': 10, 'AG': 15, 'AL': 5, 'AU': 1000,
                        'B': 10, 'BB': 500, 'BU': 10, 'C': 10,
                        'CF': 5, 'CS': 10, 'CU': 5, 'ER': 10,
                        'FB': 500, 'FG': 20, 'FU': 50, 'GN': 10,
                        'HC': 10, 'I': 100, 'IC': 200, 'IF': 300,
                        'IH': 300, 'J': 100, 'JD': 5, 'JM': 60,
                        'JR': 20, 'L': 5, 'LR': 10, 'M': 10,
                        'MA': 10, 'ME': 10, 'NI': 1, 'OI': 10,
                        'P': 10, 'PB': 5, 'PM': 50, 'PP': 5,
                        'RB': 10, 'RI': 20, 'RM': 10, 'RO': 10,
                        'RS': 10, 'RU': 10, 'SF': 5, 'SM': 5,
                        'SN': 1, 'SR': 10, 'T': 10000, 'TA': 5,
                        'TC': 100, 'TF': 10000, 'V': 5, 'WH': 20,
                        'WR': 10, 'WS': 50, 'WT': 10, 'Y': 10,
                        'ZC': 100, 'ZN': 5}
    return (cash * g.pos_factor / ATR) / future_coef_list[symbol]
