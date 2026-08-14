"""
回测：一字板过滤 vs 一字板保留
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


def load_curated_klines():
    with open(os.path.join(BASE, 'data', 'backtest_codes.json')) as f:
        pool = set(json.load(f))
    all_data = {}
    for kd in [os.path.join(BASE, 'data', 'kline_data'), os.path.join(BASE, 'data', 'backtest_kline')]:
        if not os.path.exists(kd): continue
        for fn in os.listdir(kd):
            if not fn.endswith('.json'): continue
            code = fn.replace('.json', '').rsplit('_', 1)[-1] if '_' in fn else fn.replace('.json', '')
            if code not in pool or code in all_data: continue
            if code.startswith(('300', '301', '688', '8', '9')): continue
            kls = None
            for enc in ['utf-8', 'gbk']:
                try:
                    with open(os.path.join(kd, fn), 'r', encoding=enc) as f:
                        raw = json.load(f)
                    kls = raw['data'] if isinstance(raw, dict) and 'data' in raw else raw
                    break
                except: pass
            if kls is None or not isinstance(kls, list) or len(kls) < 25: continue
            if isinstance(kls[0], dict) and 'volume_lots' in kls[0] and 'volume' not in kls[0]:
                for k in kls: k['volume'] = k.get('volume_lots', 0) * 100
            for k in kls:
                for fld in ['open', 'close', 'high', 'low', 'volume']:
                    try: k[fld] = round(float(k[fld]), 2)
                    except: k[fld] = 0.0
            all_data[code] = kls
    return all_data


def precompute_lu_freq(all_klines):
    freq = {}
    for code, kls in all_klines.items():
        count = 0
        for i in range(25, len(kls)):
            if is_limit_up(kls[i]['close'], kls[i-1]['close'], get_lp(code)):
                count += 1
        freq[code] = count
    return freq


def run_sim(all_klines, trading_days, cfg, score_min, lu_freq, keep_one_line=True):
    cash = INIT_CASH
    holding = None
    trades = []
    stop_hits = 0
    one_line_picks = 0
    one_line_trades = []

    label = 'keep' if keep_one_line else 'filter'
    print(f'  [{label}] 预扫描...', end=' ', flush=True)
    t0 = _time.time()
    daily_candidates = {}

    for ti, day in enumerate(trading_days):
        candidates = []
        for code, kls in all_klines.items():
            if lu_freq.get(code, 0) < MIN_LU_HISTORY: continue
            day_idx = None
            for i in range(max(25, len(kls)-300), len(kls)):
                if kls[i].get('date', '') == day:
                    day_idx = i; break
            if day_idx is None or day_idx < 25: continue
            if not is_limit_up(kls[day_idx]['close'], kls[day_idx-1]['close'], get_lp(code)):
                continue

            score, details = score_v3(code, kls[:day_idx+1], {}, cfg)
            if score is None or score < score_min: continue

            is_true_one = details.get('true_one_line', False)
            is_one = details.get('one_line', False)
            cons = details.get('cons', 1)

            if not keep_one_line:
                # Old rule: filter true_one_line and 4板+one_line
                if is_true_one: continue
                if is_one and cons >= 4: continue

            candidates.append((code, kls, day_idx, score, details, is_one))

        candidates.sort(key=lambda x: x[3], reverse=True)
        top3 = candidates[:3]
        daily_candidates[day] = min(top3, key=lambda x: x[4].get('vr20', 999)) if top3 else None

    print(f'{_time.time()-t0:.1f}s', flush=True)

    for ti, today in enumerate(trading_days):
        if holding:
            hkls = holding['klines']
            sell_idx = None
            for i in range(holding['idx']+1, min(holding['idx']+5, len(hkls))):
                if hkls[i].get('date', '') == today:
                    sell_idx = i; break
            if sell_idx is None: sell_idx = holding['idx'] + 1
            if sell_idx < len(hkls):
                sell_k = hkls[sell_idx]; prev_k = hkls[sell_idx-1]
                gap = (sell_k['open']-prev_k['close'])/prev_k['close']*100 if prev_k['close']>0 else 0
                code = holding['code']
                yesterday_lu = is_limit_up(prev_k['close'],
                    hkls[sell_idx-2]['close'] if sell_idx>=2 else 0, get_lp(code))

                should_sell = False; sell_price = sell_k['open']; sell_reason = ''
                stop_price = round(holding['buy_price']*(1+STOP_LOSS), 2)
                if sell_k['low'] <= stop_price and sell_k['low'] > 0:
                    should_sell = True; sell_price = stop_price; sell_reason = '止损'; stop_hits += 1
                elif yesterday_lu and gap < 0:
                    should_sell = True; sell_price = sell_k['high']; sell_reason = '昨涨停+低开'
                elif not yesterday_lu and gap < 4:
                    should_sell = True
                    sell_price = 0.7*(sell_k['high']+sell_k['open'])/2+0.3*sell_k['close']
                    sell_reason = '昨断板+弱竞价'
                if ti == len(trading_days)-1:
                    should_sell = True; sell_reason = '期末'

                if should_sell:
                    cash += holding['shares']*sell_price
                    t = {'code': code, 'buy_date': holding['buy_date'], 'sell_date': today,
                         'buy_price': holding['buy_price'], 'sell_price': round(sell_price,2),
                         'shares': holding['shares'],
                         'pnl_pct': round((sell_price-holding['buy_price'])/holding['buy_price']*100,2),
                         'reason': sell_reason, 'one_line': holding.get('one_line', False)}
                    trades.append(t)
                    if holding.get('one_line'):
                        one_line_trades.append(t)
                    holding = None

        if holding is None and cash > 0:
            prev_day = trading_days[ti-1] if ti > 0 else None
            if prev_day:
                best = daily_candidates.get(prev_day)
                if best:
                    code, bkls, lu_idx, score, details, is_one = best
                    buy_idx = None
                    for i in range(lu_idx+1, min(lu_idx+5, len(bkls))):
                        if bkls[i].get('date', '') == today:
                            buy_idx = i; break
                    if buy_idx is None: buy_idx = lu_idx+1
                    if buy_idx >= len(bkls): continue
                    b_today = bkls[buy_idx]
                    if (abs(b_today['high']-b_today['low'])<0.001 and buy_idx>0 and
                        is_limit_up(b_today['close'], bkls[buy_idx-1]['close'], get_lp(code))):
                        continue
                    bp = b_today['open']
                    if bp <= 0: continue
                    shares = int(cash/bp/100)*100
                    if shares < 100: continue
                    cash -= shares*bp
                    if is_one: one_line_picks += 1
                    holding = {'code':code, 'buy_date':today, 'buy_price':bp,
                               'shares':shares, 'klines':bkls, 'idx':buy_idx,
                               'one_line': is_one}

    if holding:
        sp = holding['klines'][-1]['close']
        cash += holding['shares']*sp
        t = {'code':holding['code'], 'buy_date':holding['buy_date'],
             'sell_date':'END', 'buy_price':holding['buy_price'],
             'sell_price':round(sp,2), 'shares':holding['shares'],
             'pnl_pct':round((sp-holding['buy_price'])/holding['buy_price']*100,2),
             'reason':'期末', 'one_line': holding.get('one_line', False)}
        trades.append(t)
        if holding.get('one_line'):
            one_line_trades.append(t)

    ret = (cash-INIT_CASH)/INIT_CASH*100
    wins = [t for t in trades if t['pnl_pct']>0]
    wr = len(wins)/len(trades)*100 if trades else 0
    avg = sum(t['pnl_pct'] for t in trades)/len(trades) if trades else 0

    ol_wins = [t for t in one_line_trades if t['pnl_pct']>0]
    ol_wr = len(ol_wins)/len(one_line_trades)*100 if one_line_trades else 0
    ol_avg = sum(t['pnl_pct'] for t in one_line_trades)/len(one_line_trades) if one_line_trades else 0

    return {'return_pct':round(ret,2), 'final_cash':round(cash,2), 'trades':len(trades),
            'win_rate':round(wr,1), 'avg_pnl':round(avg,2), 'stop_hits':stop_hits,
            'one_line_picks': one_line_picks, 'one_line_trades': len(one_line_trades),
            'one_line_wr': round(ol_wr,1), 'one_line_avg': round(ol_avg,2)}


def main():
    cfg = load_config()
    print('='*70)
    print(f'  一字板回测: 过滤 vs 保留')
    print(f'  {START} ~ {END} | 精选池 | 初始{INIT_CASH/1000:.0f}K | 全仓')
    print('='*70)

    print('\n[1/2] 加载...')
    all_klines = load_curated_klines()
    lu_freq = precompute_lu_freq(all_klines)
    print(f'  精选池: {len(all_klines)} 只', flush=True)

    days = []
    d = datetime.strptime(START, '%Y-%m-%d')
    ed = datetime.strptime(END, '%Y-%m-%d')
    while d <= ed:
        if d.weekday() < 5: days.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)

    print()
    print('[2/2] Running comparison...')
    thresholds = [0, 5, 10, 15, 20]
    hdr = '{:>4s}  {:>8s}  {:>5s}  {:>6s}  |  {:>8s}  {:>5s}  {:>6s}  |  {:>8s}  {:>5s}  {:>6s}'.format(
        'Thr', 'Old%', 'Trd', 'Win%', 'New%', 'Trd', 'Win%', 'Diff', '1LTrd', '1LWin%')
    print('  ' + hdr)
    print('  ' + '-' * 80)

    for sm in thresholds:
        r_old = run_sim(all_klines, days, cfg, sm, lu_freq, keep_one_line=False)
        r_new = run_sim(all_klines, days, cfg, sm, lu_freq, keep_one_line=True)
        diff = r_new['return_pct'] - r_old['return_pct']
        row = '  >= {:<3d}  {:>+7.1f}%  {:>4d}T  {:>5.0f}%  |  {:>+7.1f}%  {:>4d}T  {:>5.0f}%  |  {:>+7.1f}%  {:>4d}OL  {:>4.0f}%'.format(
            sm, r_old['return_pct'], r_old['trades'], r_old['win_rate'],
            r_new['return_pct'], r_new['trades'], r_new['win_rate'],
            diff, r_new['one_line_trades'], r_new['one_line_wr'])
        print(row, flush=True)

    print()
    print('=' * 70)


if __name__ == '__main__':
    main()
