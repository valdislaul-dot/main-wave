"""
三年门槛曲线 — 优化版 (全量预加载 + 向量化)
用法: python backtest_3y_curve.py
"""
import json, os, sys, time as _time
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import score_v3, load_config, is_limit_up, get_lp

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

INIT_CASH = 200000
START = '2023-08-04'
END = '2026-08-04'
STOP_LOSS = -0.10
MIN_LU_HISTORY = 2


def load_all_klines():
    """一次性加载所有K线到内存"""
    kline_dirs = [
        os.path.join(BASE, 'data', 'backtest_kline'),
        os.path.join(BASE, 'data', 'kline_data'),
    ]
    all_data = {}  # code -> (name, klines_list)
    t0 = _time.time()

    for kd in kline_dirs:
        if not os.path.exists(kd): continue
        for fn in os.listdir(kd):
            if not fn.endswith('.json'): continue
            if '_' in fn:
                name, code = fn.replace('.json', '').rsplit('_', 1)
            else:
                code = fn.replace('.json', '')
                name = code

            if code in all_data: continue
            if code.startswith(('300', '301', '688')): continue

            try:
                with open(os.path.join(kd, fn), 'r', encoding='utf-8') as f:
                    kls = json.load(f)
                for k in kls:
                    for field in ['open', 'close', 'high', 'low', 'volume']:
                        try: k[field] = round(float(k[field]), 2)
                        except: k[field] = 0.0
                if len(kls) >= 25:
                    all_data[code] = (name, kls)
            except:
                pass

    print('  加载 {} 只股票 K线 ({:.1f}s)'.format(len(all_data), _time.time() - t0))
    return all_data


def make_date_index(all_klines):
    """构建 日期 → [(code, name, klines, day_idx), ...] 的索引"""
    date_idx = defaultdict(list)
    for code, (name, kls) in all_klines.items():
        for i, k in enumerate(kls):
            if i >= 25:  # only index dates with enough history
                d = k.get('date', k.get('day', ''))
                date_idx[d].append((code, name, kls, i))
    return date_idx


def precompute_lu_freq(all_klines):
    """预计算涨停频次"""
    freq = {}
    for code, (name, kls) in all_klines.items():
        count = 0
        for i in range(25, len(kls)):
            lpct = get_lp(code)
            if is_limit_up(kls[i]['close'], kls[i-1]['close'], lpct):
                count += 1
        freq[code] = count
    return freq


def run_3y_sim(all_klines, trading_days, cfg, score_min, lu_freq):
    """三年回测 (内存优化版)"""
    cash = INIT_CASH
    holding = None
    trades = []
    stop_hits = 0

    # 预扫描: 每天有哪些候选 (避免每天重复扫786只)
    print('    预扫描候选池...', end=' ', flush=True)
    t0 = _time.time()
    daily_candidates = {}  # date -> [(code, name, klines, idx, score, details), ...]

    for ti, day in enumerate(trading_days):
        candidates = []
        for code, (name, kls) in all_klines.items():
            if lu_freq.get(code, 0) < MIN_LU_HISTORY: continue
            # 找day在klines中的位置
            day_idx = None
            for i in range(max(25, len(kls)-300), len(kls)):  # 搜最近300天
                if kls[i].get('date', kls[i].get('day', '')) == day:
                    day_idx = i
                    break
            if day_idx is None or day_idx < 25: continue

            lpct = get_lp(code)
            if not is_limit_up(kls[day_idx]['close'], kls[day_idx-1]['close'], lpct):
                continue

            score, details = score_v3(code, kls[:day_idx+1], {}, cfg)
            if score is None or score < score_min: continue
            if details.get('true_one_line'): continue
            if details.get('one_line') and details.get('cons', 1) >= 4: continue

            candidates.append((code, name, kls, day_idx, score, details))

        # Top3 by score, pick lowest vr
        candidates.sort(key=lambda x: x[4], reverse=True)
        top3 = candidates[:3]
        if top3:
            best = min(top3, key=lambda x: x[5].get('vr20', 999))
            daily_candidates[day] = best
        else:
            daily_candidates[day] = None

    print('{:.1f}s'.format(_time.time() - t0))

    # 模拟
    for ti, today in enumerate(trading_days):
        # ── 卖出 ──
        if holding:
            hkls = holding['klines']
            # 找today索引
            sell_idx = None
            start_search = holding['idx'] + 1
            for i in range(start_search, min(start_search + 5, len(hkls))):
                if hkls[i].get('date', hkls[i].get('day', '')) == today:
                    sell_idx = i
                    break
            if sell_idx is None: sell_idx = holding['idx'] + 1  # fallback

            if sell_idx < len(hkls):
                sell_k = hkls[sell_idx]
                prev_k = hkls[sell_idx - 1]
                today_open = sell_k['open']
                today_low = sell_k['low']
                prev_close = prev_k['close']
                gap = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0
                code = holding['code']

                yesterday_lu = is_limit_up(prev_k['close'],
                    hkls[sell_idx-2]['close'] if sell_idx >= 2 else 0, get_lp(code))

                should_sell = False
                sell_price = today_open
                sell_reason = ''

                # 止损
                stop_price = round(holding['buy_price'] * (1 + STOP_LOSS), 2)
                if today_low <= stop_price and today_low > 0:
                    should_sell = True
                    sell_price = stop_price
                    sell_reason = '止损(-10%)'
                    stop_hits += 1
                elif yesterday_lu and gap < 0:
                    should_sell = True
                    sell_price = sell_k['high']
                    sell_reason = '昨涨停+低开'
                elif not yesterday_lu and gap < 4:
                    should_sell = True
                    sell_price = 0.7 * (sell_k['high'] + sell_k['open']) / 2 + 0.3 * sell_k['close']
                    sell_reason = '昨断板+弱竞价'

                if ti == len(trading_days) - 1:
                    should_sell = True
                    sell_reason = '期末'

                if should_sell:
                    pnl = (sell_price - holding['buy_price']) / holding['buy_price'] * 100
                    cash = holding['shares'] * sell_price
                    trades.append({
                        'code': code, 'name': holding['name'],
                        'buy_date': holding['buy_date'], 'sell_date': today,
                        'buy_price': holding['buy_price'], 'sell_price': round(sell_price, 2),
                        'shares': holding['shares'], 'pnl_pct': round(pnl, 2),
                        'reason': sell_reason,
                    })
                    holding = None

        # ── 买入 ──
        if holding is None and cash > 0:
            prev_day_idx = ti - 1
            if prev_day_idx >= 0:
                prev_day = trading_days[prev_day_idx]
                best = daily_candidates.get(prev_day)
                if best:
                    code, name, bkls, lu_idx, score, details = best
                    # 找today在最佳候选K线中的位置
                    buy_idx = None
                    for i in range(lu_idx + 1, min(lu_idx + 5, len(bkls))):
                        if bkls[i].get('date', bkls[i].get('day', '')) == today:
                            buy_idx = i
                            break
                    if buy_idx is None: buy_idx = lu_idx + 1
                    if buy_idx >= len(bkls): continue

                    b_today = bkls[buy_idx]
                    # 一字封死?
                    if (abs(b_today['high'] - b_today['low']) < 0.001 and buy_idx > 0 and
                        is_limit_up(b_today['close'], bkls[buy_idx-1]['close'], get_lp(code))):
                        continue

                    bp = b_today['open']
                    if bp <= 0: continue
                    shares = int(cash / bp / 100) * 100
                    if shares < 100: continue
                    cash -= shares * bp
                    holding = {'code': code, 'name': name, 'buy_date': today,
                               'buy_price': bp, 'shares': shares,
                               'klines': bkls, 'idx': buy_idx}

    # 期末清仓
    if holding:
        last_k = holding['klines'][-1]
        sp = last_k['close']
        pnl = (sp - holding['buy_price']) / holding['buy_price'] * 100
        cash = holding['shares'] * sp
        trades.append({'code': holding['code'], 'name': holding['name'],
                       'buy_date': holding['buy_date'], 'sell_date': 'END',
                       'buy_price': holding['buy_price'], 'sell_price': round(sp, 2),
                       'shares': holding['shares'], 'pnl_pct': round(pnl, 2),
                       'reason': '期末'})

    ret = (cash - INIT_CASH) / INIT_CASH * 100
    wins = [t for t in trades if t['pnl_pct'] > 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg = sum(t['pnl_pct'] for t in trades) / len(trades) if trades else 0
    ml = min((t['pnl_pct'] for t in trades), default=0)

    return {'label': 'V3_min{}'.format(score_min), 'final_cash': round(cash, 2),
            'return_pct': round(ret, 2), 'trades': len(trades),
            'win_rate': round(wr, 1), 'avg_pnl': round(avg, 2),
            'max_loss': round(ml, 2), 'stop_hits': stop_hits}


def main():
    cfg = load_config()
    print('=' * 60)
    print('  三年门槛曲线 — V3平滑评分 (2023-08 ~ 2026-08)')
    print('  质量过滤: >= {}次涨停 | 止损: {}%'.format(MIN_LU_HISTORY, STOP_LOSS*100))
    print('=' * 60)

    print('\n[1/4] 加载K线...')
    all_klines = load_all_klines()

    lu_freq = precompute_lu_freq(all_klines)
    qualified = sum(1 for c in lu_freq if lu_freq[c] >= MIN_LU_HISTORY)
    print('  历史涨停>=2次: {} / {}'.format(qualified, len(all_klines)))

    # 生成交易日
    trading_days = []
    d = datetime.strptime(START, '%Y-%m-%d')
    ed = datetime.strptime(END, '%Y-%m-%d')
    while d <= ed:
        if d.weekday() < 5:
            trading_days.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    print('  交易日: {} 天'.format(len(trading_days)))

    # 门槛扫描
    thresholds = [0, 5, 10, 15, 20, 25, 30, 35, 40]
    print('\n[2/4] 扫描买入门槛...')

    curve = []
    for sm in thresholds:
        t0 = _time.time()
        result = run_3y_sim(all_klines, trading_days, cfg, sm, lu_freq)
        curve.append({'threshold': sm, **{k: result[k] for k in
            ['return_pct', 'final_cash', 'trades', 'win_rate', 'avg_pnl', 'max_loss']}})
        print('    >= {:2d}: {:>+7.1f}%  {:>8.0f}k  {:3d}笔  {:2.0f}%胜  {:>+5.1f}%均价  ({:.0f}s)'.format(
            sm, result['return_pct'], result['final_cash']/1000, result['trades'],
            result['win_rate'], result['avg_pnl'], _time.time() - t0))

    print('\n[3/4] 三年门槛曲线:')
    print('=' * 60)
    print('  {:8s} {:>8s} {:>8s} {:>6s} {:>6s} {:>6s}'.format(
        '门槛', '收益率', '资产(k)', '笔数', '胜率', '均价'))
    print('  ' + '-' * 44)
    best = max(curve, key=lambda x: x['return_pct'])
    for c in curve:
        marker = ' <= BEST' if c == best else ''
        print('  >= {:<5d} {:>+7.1f}% {:>7.0f}k {:>5d} {:>5.0f}% {:>+5.1f}%{}'.format(
            c['threshold'], c['return_pct'], c['final_cash']/1000,
            c['trades'], c['win_rate'], c['avg_pnl'], marker))
    print('=' * 60)

    # 月度收益
    print('\n[4/4] 最优门槛 (>={}) 年度明细:'.format(best['threshold']))
    out_path = os.path.join(BASE, 'logs', 'threshold_3y_curve.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'config': {'start': START, 'end': END, 'init': INIT_CASH},
                   'curve': curve, 'best': best['threshold']}, f, ensure_ascii=False, indent=2)
    print('  保存: {}'.format(out_path))
    return curve


if __name__ == '__main__':
    main()
