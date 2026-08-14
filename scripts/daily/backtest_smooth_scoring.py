"""
v2陡峭 vs v3平滑 全市场回测对比
基于 backtest_full_market.py 结构, 评分模块化
用法: python backtest_smooth_scoring.py [--universe 243|full]
"""
import json, os, sys, math
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import (
    score_v2, score_v3, load_config, is_limit_up, get_lp,
    step_score_asc, step_score_desc, piecewise_linear
)

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

INIT_CASH = 200000
START = '2023-08-04'
END = '2026-08-04'
STOP_LOSS = -0.10        # -10% hard stop
AUCTION_WEAK_GAP = 4.0   # 竞价gap<4% → 弱, 卖出换股
MIN_LU_HISTORY = 2       # 质量过滤: 至少历史涨停N次才纳入候选


# ============================================================
# 数据加载
# ============================================================

def load_kline_index():
    """加载K线索引: 优先backtest_kline(完整180天), 其次kline_data"""
    stock_files = {}  # code → (name, path)

    # 目录优先级: backtest_kline (完整历史) > kline_data (实时跟踪)
    dirs = [
        os.path.join(BASE, 'data', 'backtest_kline'),
        os.path.join(BASE, 'data', 'kline_data'),
    ]

    for kline_dir in dirs:
        if not os.path.exists(kline_dir):
            continue
        for fn in os.listdir(kline_dir):
            if not fn.endswith('.json'): continue
            # backtest_kline: {code}.json, kline_data: {name}_{code}.json
            if '_' in fn:
                parts = fn.replace('.json', '').rsplit('_', 1)
                if len(parts) == 2:
                    name, code = parts
            else:
                code = fn.replace('.json', '')
                name = code  # no name info in backtest_kline

            if code not in stock_files:  # backtest_kline takes priority
                stock_files[code] = (name, os.path.join(kline_dir, fn))

    date_range = {}
    for code, (name, fpath) in stock_files.items():
        try:
            with open(fpath, encoding='utf-8') as f:
                kls = json.load(f)
            if kls:
                for k in kls:
                    for field in ['open', 'close', 'high', 'low', 'volume']:
                        try: k[field] = round(float(k[field]), 2)
                        except: k[field] = 0.0
                date_range[code] = (kls[0].get('date', kls[0].get('day', '')),
                                    kls[-1].get('date', kls[-1].get('day', '')),
                                    name, fpath)
        except:
            pass
    return stock_files, date_range


def load_klines(fpath):
    try:
        with open(fpath, encoding='utf-8') as f:
            kls = json.load(f)
        for k in kls:
            for field in ['open', 'close', 'high', 'low', 'volume']:
                try: k[field] = round(float(k[field]), 2)
                except: k[field] = 0.0
        return kls
    except:
        return []


def get_trading_days(start, end):
    """生成交易日列表 (周一至周五, 简单版本)"""
    days = []
    d = datetime.strptime(start, '%Y-%m-%d')
    ed = datetime.strptime(end, '%Y-%m-%d')
    while d <= ed:
        if d.weekday() < 5:
            days.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    return days


# ============================================================
# 评分 (使用 scoring.py 模块)
# ============================================================

def score_stock(code, klines, idx, scorer, cfg):
    """用指定scorer对klines[idx]评分, 返回(score, details)"""
    # 截取0..idx的K线用于precompute
    sub_klines = klines[:idx+1]
    return scorer(code, sub_klines, {}, cfg)


# ============================================================
# 扫描涨停股
# ============================================================

def scan_limit_ups(stock_files, date_range, target_date, scorer, cfg, lu_freq=None):
    lu_stocks = []
    for code, (name, fpath) in stock_files.items():
        if code.startswith(('300', '301', '688', '8', '9')): continue
        # 质量过滤: 标的必须至少出现过MIN_LU_HISTORY次涨停
        if lu_freq and lu_freq.get(code, 0) < MIN_LU_HISTORY: continue
        dr = date_range.get(code)
        if not dr: continue
        if target_date < dr[0] or target_date > dr[1]: continue

        try:
            kls = load_klines(fpath)
            if len(kls) < 25: continue
            for i, k in enumerate(kls):
                d = k.get('date', k.get('day', ''))
                if d == target_date and i >= 25:
                    lpct = get_lp(code)
                    if i > 0 and is_limit_up(k['close'], kls[i-1]['close'], lpct):
                        score, details = score_stock(code, kls, i, scorer, cfg)
                        if score is not None and details:
                            # 风控过滤
                            if details.get('true_one_line'): continue
                            if details.get('one_line') and details.get('cons', 1) >= 4: continue
                            if score < cfg.get('score_min', 10): continue
                            lu_stocks.append({
                                'code': code, 'name': name,
                                'score': score, 'details': details,
                                'klines': kls, 'idx': i,
                            })
                    break
        except:
            pass
    return lu_stocks


# ============================================================
# 模拟交易
# ============================================================

def find_day_idx(klines, target_date):
    for i, k in enumerate(klines):
        if k.get('date', k.get('day', '')) == target_date:
            return i
    return None


def run_sim(stock_files, date_range, trading_days, scorer, cfg, label='v2',
            lu_freq=None, score_min=None):
    """
    实战版模拟:
    - 原版卖出规则 (已验证+132%) + -10%硬止损
    - 卖出当日上午即可买入新候选 (T+0回收现金)
    - lu_freq: 历史涨停频次 (质量过滤)
    - score_min: 最低买入评分 (None=用config默认值)
    """
    if score_min is None:
        score_min = cfg.get('score_min', 10)
    cash = INIT_CASH
    holding = None
    trades = []
    daily_equity = []
    stop_hits = 0

    for ti, today in enumerate(trading_days):
        # ══════ 第一步: 卖出判断 ══════
        if holding:
            hkls = holding['klines']
            sell_idx = find_day_idx(hkls, today)
            if sell_idx is not None and sell_idx > holding['idx']:
                sell_k = hkls[sell_idx]
                prev_k = hkls[sell_idx - 1]
                today_open = sell_k['open']
                today_low = sell_k['low']
                prev_close = prev_k['close']
                gap = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0
                code = holding['code']

                yesterday_lu = is_limit_up(prev_k['close'],
                    hkls[sell_idx-2]['close'] if sell_idx >= 2 else 0,
                    get_lp(code))
                hold_days = (datetime.strptime(today, '%Y-%m-%d') -
                             datetime.strptime(holding['buy_date'], '%Y-%m-%d')).days

                should_sell = False
                sell_reason = ''
                sell_price = today_open

                # 条件1: 止损 (优先级最高)
                stop_price = round(holding['buy_price'] * (1 + STOP_LOSS), 2)
                if today_low <= stop_price and today_low > 0:
                    should_sell = True
                    sell_price = stop_price
                    sell_reason = f'止损({STOP_LOSS*100:.0f}%)'
                    stop_hits += 1

                # 条件2: 原版卖出规则 (保持原版执行价)
                elif yesterday_lu and gap < 0:
                    should_sell = True
                    sell_price = sell_k['high']  # 涨停日挂涨停价
                    sell_reason = f'昨涨停+低开({gap:.1f}%)'
                elif not yesterday_lu and gap < 4:
                    should_sell = True
                    # 原版: 70%(H+O)/2 + 30%收盘价
                    sell_price = 0.7 * (sell_k['high'] + sell_k['open']) / 2 + 0.3 * sell_k['close']
                    sell_reason = f'昨断板+弱竞价(gap={gap:.1f}%)'

                # 条件4: 期末
                if ti == len(trading_days) - 1:
                    should_sell = True
                    sell_reason = '期末清仓'

                if should_sell:
                    pnl_pct = (sell_price - holding['buy_price']) / holding['buy_price'] * 100
                    proceeds = holding['shares'] * sell_price
                    cash = proceeds
                    trades.append({
                        'code': code, 'name': holding['name'],
                        'buy_date': holding['buy_date'], 'sell_date': today,
                        'buy_price': holding['buy_price'], 'sell_price': round(sell_price, 2),
                        'shares': holding['shares'], 'pnl_pct': round(pnl_pct, 2),
                        'reason': sell_reason,
                    })
                    holding = None

        # ══════ 第二步: 无持仓 → 当日买入候选 ══════
        if holding is None and cash > 0:
            prev_day_idx = ti - 1
            if prev_day_idx >= 0:
                prev_day = trading_days[prev_day_idx]
                candidates = scan_limit_ups(stock_files, date_range, prev_day, scorer, cfg, lu_freq)

                if candidates:
                    # 评分门槛过滤
                    candidates = [c for c in candidates if c['score'] >= score_min]
                if candidates:
                    candidates.sort(key=lambda x: x['score'], reverse=True)
                    top3 = candidates[:3]
                    best = min(top3, key=lambda x: x['details'].get('vr20', 999))

                    bkls = best['klines']
                    b_today_idx = find_day_idx(bkls, today)
                    if b_today_idx is not None:
                        b_today = bkls[b_today_idx]
                        is_locked = (abs(b_today['high'] - b_today['low']) < 0.001 and
                                     is_limit_up(b_today['close'], bkls[b_today_idx-1]['close'],
                                                 get_lp(best['code'])))
                        if not is_locked:
                            buy_price = b_today['open']
                            if buy_price > 0:
                                shares = int(cash / buy_price / 100) * 100
                                if shares >= 100:
                                    cost = shares * buy_price
                                    cash -= cost
                                    holding = {
                                        'code': best['code'], 'name': best['name'],
                                        'buy_date': today, 'buy_price': buy_price,
                                        'shares': shares, 'klines': bkls, 'idx': b_today_idx,
                                    }

        # ══════ 日终净值 ══════
        eq = cash
        if holding:
            hkls = holding['klines']
            hi = find_day_idx(hkls, today)
            if hi is not None:
                eq += holding['shares'] * hkls[hi]['close']
            else:
                eq += holding['shares'] * holding['buy_price']
        daily_equity.append({'date': today, 'equity': round(eq, 2)})

    # 期末清仓
    if holding:
        last_k = holding['klines'][-1]
        sell_price = last_k['close']
        pnl_pct = (sell_price - holding['buy_price']) / holding['buy_price'] * 100
        proceeds = holding['shares'] * sell_price
        cash = proceeds
        trades.append({
            'code': holding['code'], 'name': holding['name'],
            'buy_date': holding['buy_date'], 'sell_date': 'END',
            'buy_price': holding['buy_price'], 'sell_price': round(sell_price, 2),
            'shares': holding['shares'], 'pnl_pct': round(pnl_pct, 2),
            'reason': '期末清仓',
        })
        holding = None

    final_cash = cash
    ret_pct = (final_cash - INIT_CASH) / INIT_CASH * 100
    win_trades = [t for t in trades if t['pnl_pct'] > 0]
    wr = len(win_trades) / len(trades) * 100 if trades else 0
    avg_pnl = sum(t['pnl_pct'] for t in trades) / len(trades) if trades else 0
    max_loss = min(t['pnl_pct'] for t in trades) if trades else 0
    loss_trades = [t for t in trades if t['pnl_pct'] < 0]

    return {
        'label': label,
        'final_cash': round(final_cash, 2),
        'return_pct': round(ret_pct, 2),
        'trades': len(trades),
        'win_rate': round(wr, 1),
        'avg_pnl': round(avg_pnl, 2),
        'max_loss': round(max_loss, 2),
        'stop_hits': stop_hits,
        'loss_trades_detail': [{'code': t['code'], 'name': t['name'], 'pnl': t['pnl_pct'],
                                'date': t['sell_date'], 'reason': t.get('reason', '')}
                               for t in sorted(loss_trades, key=lambda x: x['pnl_pct'])],
        'trades_detail': trades,
    }


# ============================================================
# 主流程
# ============================================================

def precompute_lu_freq(stock_files, date_range):
    """预计算每只股票在回测区间内的涨停次数 (用于质量过滤)"""
    print('  预计算涨停频次...')
    lu_freq = {}
    for code, (name, fpath) in stock_files.items():
        if code.startswith(('300', '301', '688', '8', '9')): continue
        try:
            kls = load_klines(fpath)
            count = 0
            for i in range(25, len(kls)):
                lpct = get_lp(code)
                if is_limit_up(kls[i]['close'], kls[i-1]['close'], lpct):
                    count += 1
            lu_freq[code] = count
        except:
            lu_freq[code] = 0
    return lu_freq


def main():
    cfg = load_config()
    print('=' * 70)
    print('  V3平滑评分 — 质量过滤 + 买入门槛曲线')
    print(f'  区间: {START} → {END} | 初始资金: {INIT_CASH:,}')
    print(f'  质量过滤: 历史涨停≥{MIN_LU_HISTORY}次 | 止损: {STOP_LOSS*100:.0f}%')
    print('=' * 70)

    print('\n[1/3] 加载K线索引...')
    stock_files, date_range = load_kline_index()
    print(f'  可用股票: {len(stock_files)} 只')

    trading_days = get_trading_days(START, END)
    print(f'  交易日: {len(trading_days)} 天')

    # 预计算涨停频次
    lu_freq = precompute_lu_freq(stock_files, date_range)
    qualified = sum(1 for c in lu_freq if lu_freq[c] >= MIN_LU_HISTORY)
    print(f'  历史涨停≥{MIN_LU_HISTORY}次: {qualified} 只 (过滤{len(stock_files)-qualified}只噪音)')

    # ══════ 门槛曲线扫描 ══════
    thresholds = [0, 5, 10, 15, 20, 25, 30, 35, 40]
    print(f'\n[2/3] 扫描买入门槛: {thresholds}')

    curve = []
    for sm in thresholds:
        result = run_sim(stock_files, date_range, trading_days, score_v3, cfg,
                         'V3_min{}'.format(sm), lu_freq=lu_freq, score_min=sm)
        curve.append({
            'threshold': sm,
            'return_pct': result['return_pct'],
            'final_cash': result['final_cash'],
            'trades': result['trades'],
            'win_rate': result['win_rate'],
            'avg_pnl': result['avg_pnl'],
            'max_loss': result['max_loss'],
        })
        print('    门槛>={:2d}: 收益={:+6.1f}%  笔数={:3d}  胜率={:.0f}%  均价={:+.1f}%'.format(
            sm, result['return_pct'], result['trades'],
            result['win_rate'], result['avg_pnl']))

    # 输出
    print('\n[3/3] 买入门槛曲线:')
    print('=' * 70)
    print('  {:8s} {:>8s} {:>6s} {:>6s} {:>6s} {:>6s}'.format(
        '门槛', '收益率', '笔数', '胜率', '均价', '最大亏'))
    print('  ' + '-' * 50)
    best = max(curve, key=lambda x: x['return_pct'])
    for c in curve:
        marker = ' <- 最优' if c == best else ''
        print('  >={:<6d} {:>+7.1f}% {:>5d} {:>5.0f}% {:>+5.1f}% {:>+5.1f}%{}'.format(
            c['threshold'], c['return_pct'], c['trades'],
            c['win_rate'], c['avg_pnl'], c['max_loss'], marker))
    print('=' * 70)
    print('\n  推荐买入门槛: >={} (收益={:+.1f}%)'.format(best['threshold'], best['return_pct']))

    # 保存
    output = {
        'config': {'start': START, 'end': END, 'init_cash': INIT_CASH,
                   'min_lu_history': MIN_LU_HISTORY, 'stop_loss': STOP_LOSS},
        'threshold_curve': curve,
        'best_threshold': best['threshold'],
    }
    out_path = os.path.join(BASE, 'logs', 'threshold_curve.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'  结果已保存: {out_path}')
    return curve


if __name__ == '__main__':
    main()
