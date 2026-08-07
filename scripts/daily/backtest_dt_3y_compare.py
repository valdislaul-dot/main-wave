"""
三年回测: V3.1基准 vs +反转DT因子 (762精选池)
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
    """只加载精选池的K线"""
    with open(os.path.join(BASE, 'data', 'backtest_codes.json')) as f:
        pool = set(json.load(f))

    all_data = {}
    t0 = _time.time()
    for kd in [os.path.join(BASE, 'data', 'kline_data'), os.path.join(BASE, 'data', 'backtest_kline')]:
        if not os.path.exists(kd): continue
        for fn in os.listdir(kd):
            if not fn.endswith('.json'): continue
            code = fn.replace('.json', '').rsplit('_', 1)[-1] if '_' in fn else fn.replace('.json', '')
            if code not in pool: continue
            if code in all_data: continue
            if code.startswith(('300', '301', '688')): continue
            kls = None
            for enc in ['utf-8', 'gbk']:
                try:
                    with open(os.path.join(kd, fn), 'r', encoding=enc) as f:
                        raw = json.load(f)
                    kls = raw['data'] if isinstance(raw, dict) and 'data' in raw else raw
                    break
                except: pass
            if kls is None or not isinstance(kls, list) or len(kls) == 0: continue
            if isinstance(kls[0], dict) and 'volume_lots' in kls[0] and 'volume' not in kls[0]:
                for k in kls: k['volume'] = k.get('volume_lots', 0) * 100
            for k in kls:
                for fld in ['open', 'close', 'high', 'low', 'volume']:
                    try: k[fld] = round(float(k[fld]), 2)
                    except: k[fld] = 0.0
            if len(kls) >= 25:
                all_data[code] = (fn.replace('.json', '').split('_')[0] if '_' in fn else code, kls)

    print(f'  精选池加载: {len(all_data)}/{len(pool)} 只 ({_time.time()-t0:.1f}s)', flush=True)
    return all_data


def load_dt_factors():
    dt_dir = os.path.join(BASE, 'data', 'dt_block')
    factors = {}
    files = [f for f in os.listdir(dt_dir) if f.endswith('.json') and f != '_summary.json']
    for fname in files:
        date = fname.replace('.json', '')
        with open(os.path.join(dt_dir, fname), encoding='utf-8') as f:
            day = json.load(f)
        date_map = {}
        if 'dragon_tiger' in day:
            block_by_code = defaultdict(list)
            for b in day.get('block_trades', []):
                block_by_code[b['code']].append(b)
            for r in day['dragon_tiger']:
                code = r['code']
                if code.startswith(('300','301','688')): continue
                net_buy = r.get('net_buy_wan', 0)
                turnover = r.get('turnover', 0)
                dt_score = 0
                if net_buy > 10000: dt_score += 3
                elif net_buy < -5000: dt_score -= 4
                if turnover > 30: dt_score -= 2
                elif turnover < 1: dt_score += 2
                blocks = block_by_code.get(code, [])
                blk_score = 0
                if blocks:
                    disc = sum(b['amount_wan'] for b in blocks if b.get('premium_pct',0)<-5)
                    prem = sum(b['amount_wan'] for b in blocks if b.get('premium_pct',0)>2)
                    if disc > 1000: blk_score -= 5
                    elif disc > 500: blk_score -= 3
                    elif disc > 100: blk_score -= 1
                    if prem > 500: blk_score += 4
                    elif prem > 100: blk_score += 2
                factor = -(dt_score + blk_score)
                if factor != 0:
                    date_map[code] = factor
        elif 'results' in day:
            for code, info in day['results'].items():
                f = -info.get('factor', 0)
                if f != 0:
                    date_map[code] = f
        if date_map:
            factors[date] = date_map
    nz = sum(len(v) for v in factors.values())
    print(f'  加载DT因子: {len(files)}天, {nz}条', flush=True)
    return factors


def precompute_lu_freq(all_klines):
    freq = {}
    for code, (name, kls) in all_klines.items():
        count = 0
        for i in range(25, len(kls)):
            if is_limit_up(kls[i]['close'], kls[i-1]['close'], get_lp(code)):
                count += 1
        freq[code] = count
    return freq


def run_sim(all_klines, trading_days, cfg, score_min, lu_freq, dt_factors=None, label=''):
    use_dt = dt_factors is not None
    cash = INIT_CASH
    holding = None
    trades = []
    stop_hits = 0

    print(f'  [{label}] 预扫描...', end=' ', flush=True)
    t0 = _time.time()
    daily_candidates = {}

    for ti, day in enumerate(trading_days):
        candidates = []
        for code, (name, kls) in all_klines.items():
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
            if details.get('true_one_line'): continue
            if details.get('one_line') and details.get('cons', 1) >= 4: continue

            if use_dt and dt_factors:
                dt_add = dt_factors.get(day, {}).get(code, 0)
                score += dt_add

            candidates.append((code, name, kls, day_idx, score, details))

        candidates.sort(key=lambda x: x[4], reverse=True)
        top3 = candidates[:3]
        daily_candidates[day] = min(top3, key=lambda x: x[5].get('vr20', 999)) if top3 else None

    print(f'{_time.time()-t0:.1f}s', flush=True)

    # Simulate
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
                    should_sell = True; sell_price = stop_price
                    sell_reason = '止损'; stop_hits += 1
                elif yesterday_lu and gap < 0:
                    should_sell = True; sell_price = sell_k['high']
                    sell_reason = '昨涨停+低开'
                elif not yesterday_lu and gap < 4:
                    should_sell = True
                    sell_price = 0.7*(sell_k['high']+sell_k['open'])/2+0.3*sell_k['close']
                    sell_reason = '昨断板+弱竞价'
                if ti == len(trading_days)-1:
                    should_sell = True; sell_reason = '期末'

                if should_sell:
                    cash += holding['shares']*sell_price
                    trades.append({
                        'code': code, 'buy_date': holding['buy_date'], 'sell_date': today,
                        'buy_price': holding['buy_price'], 'sell_price': round(sell_price,2),
                        'shares': holding['shares'],
                        'pnl_pct': round((sell_price-holding['buy_price'])/holding['buy_price']*100,2),
                        'reason': sell_reason})
                    holding = None

        if holding is None and cash > 0:
            prev_day = trading_days[ti-1] if ti > 0 else None
            if prev_day:
                best = daily_candidates.get(prev_day)
                if best:
                    code, name, bkls, lu_idx, score, details = best
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
                    holding = {'code':code, 'name':name, 'buy_date':today, 'buy_price':bp,
                               'shares':shares, 'klines':bkls, 'idx':buy_idx}

    if holding:
        sp = holding['klines'][-1]['close']
        cash += holding['shares']*sp
        trades.append({'code':holding['code'], 'buy_date':holding['buy_date'],
                       'sell_date':'END', 'buy_price':holding['buy_price'],
                       'sell_price':round(sp,2), 'shares':holding['shares'],
                       'pnl_pct':round((sp-holding['buy_price'])/holding['buy_price']*100,2),
                       'reason':'期末'})

    ret = (cash-INIT_CASH)/INIT_CASH*100
    wins = [t for t in trades if t['pnl_pct']>0]
    wr = len(wins)/len(trades)*100 if trades else 0
    avg = sum(t['pnl_pct'] for t in trades)/len(trades) if trades else 0
    return {'return_pct':round(ret,2), 'final_cash':round(cash,2), 'trades':len(trades),
            'win_rate':round(wr,1), 'avg_pnl':round(avg,2), 'stop_hits':stop_hits}


def main():
    cfg = load_config()
    print('='*70)
    print(f'  三年回测 (762精选池): V3.1基准 vs V3.1+反转DT因子')
    print(f'  {START} ~ {END} | 初始{INIT_CASH/1000:.0f}K | 全仓 | 止损{STOP_LOSS*100:.0f}%')
    print('='*70)

    print('\n[1/3] 加载精选池K线...')
    all_klines = load_curated_klines()
    lu_freq = precompute_lu_freq(all_klines)
    qualified = sum(1 for c in lu_freq if lu_freq[c] >= MIN_LU_HISTORY)
    print(f'  历史涨停>={MIN_LU_HISTORY}次: {qualified}/{len(all_klines)}', flush=True)

    print('\n[2/3] 加载DT反转因子...')
    dt_factors = load_dt_factors()

    days = []
    d = datetime.strptime(START, '%Y-%m-%d')
    ed = datetime.strptime(END, '%Y-%m-%d')
    while d <= ed:
        if d.weekday() < 5: days.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    print(f'  交易日: {len(days)}', flush=True)

    thresholds = [0, 5, 10, 15, 20, 25, 30]
    print(f'\n[3/3] 门槛扫描...')
    print(f'  {"门槛":>4s}  {"基准%":>8s}  {"基准笔":>5s}  {"基准胜%":>6s}  |  {"+DT%":>8s}  {"+DT笔":>5s}  {"+DT胜%":>6s}  |  {"差异":>8s}')
    print(f'  {"-"*64}')

    for sm in thresholds:
        r_base = run_sim(all_klines, days, cfg, sm, lu_freq, dt_factors=None, label=f'V3.1>={sm}')
        r_dt = run_sim(all_klines, days, cfg, sm, lu_freq, dt_factors=dt_factors, label=f'+DT>={sm}')
        diff = r_dt['return_pct'] - r_base['return_pct']
        print(f'  >= {sm:<3d}  {r_base["return_pct"]:>+7.1f}%  {r_base["trades"]:>4d}笔  {r_base["win_rate"]:>4.0f}%  '
              f'| {r_dt["return_pct"]:>+7.1f}%  {r_dt["trades"]:>4d}笔  {r_dt["win_rate"]:>4.0f}%  '
              f'| {diff:>+7.1f}%', flush=True)

    print(f'\n{"="*70}')


if __name__ == '__main__':
    main()
