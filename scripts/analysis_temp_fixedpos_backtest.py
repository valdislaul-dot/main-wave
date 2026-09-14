# -*- coding: utf-8 -*-
"""临时回测(2026-09-07): 仓位方案对比 — 温度四档 vs A式恒定仓位
口径=backtest_v4.py 同一框架(定稿权重+决策树卖出+开盘价执行), 唯一变量=仓位函数
窗口: 一年 2025-09-01~2026-08-19 / 三个月 2026-05-19~2026-08-19
只读数据, 不写回任何配置。
"""
import json, os, sys
from datetime import datetime
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
from backtest_common import temp_position

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
INIT = 200000
COST = 0.00125
FACTORS = ['vr', 'gap', 'board_type', 'cons', 'seal', 'zhaban', 'sector', 'divergence', 'dt_risk', 'turnover']

with open(os.path.join(BASE, 'data', 'scoring_config.json'), encoding='utf-8') as f:
    _cfg = json.load(f)
WEIGHTS = _cfg['v4']['weights']
NORM = _cfg['v4']['normalize']

WINDOWS = [
    ('一年', '2025-09-01', '2026-08-19'),
    # ('三个月', '2026-05-19', '2026-08-19'),  # 已跑过: 温度259.2% vs 恒50 200.8% vs 恒55 234.8% vs 恒100 679.0%
]

# ---- 因子预计算(与backtest_v4同口径) ----
klines_cache = {}
def get_klines(code):
    if code in klines_cache:
        return klines_cache[code]
    for enc in ('utf-8', 'gbk'):
        try:
            with open(os.path.join(KLINE_DIR, f'{code}.json'), encoding=enc) as f:
                raw = json.load(f)
            kls = raw.get('data', raw) if isinstance(raw, dict) else raw
            klines_cache[code] = kls
            return kls
        except Exception:
            continue
    klines_cache[code] = None
    return None

def is_lu_pct(k, pk):
    if k.get('pct_change') is not None:
        return k['pct_change'] >= 9.8
    return bool(pk) and pk['close'] > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098

ktbl = {}
for fn in os.listdir(KLINE_DIR):
    if not fn.endswith('.json') or fn.startswith('._'):
        continue
    code = fn.replace('.json', '')
    if code.startswith(('300', '301', '688', '8', '9')):
        continue
    kls = get_klines(code)
    if kls:
        ktbl[code] = kls
print(f'K线: {len(ktbl)}只')

ths_files = sorted(fn for fn in os.listdir(THS_DIR) if fn.endswith('.json'))

def build_factor_days(ws, we):
    all_dates = [fn.replace('.json', '') for fn in ths_files if ws.replace('-', '') <= fn.replace('.json', '') <= we.replace('-', '')]
    factor_days, temp_of = {}, {}
    for ymd in all_dates:
        date_fmt = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
        with open(os.path.join(THS_DIR, f'{ymd}.json'), encoding='utf-8') as f:
            info = json.load(f)
        temp_of[date_fmt] = len(info)
        word_freq = Counter()
        entries = []
        for s in info:
            code = str(s.get('code', ''))
            if not code or code.startswith(('300', '301', '688', '8', '9')):
                continue
            ws2 = [w for w in str(s.get('reason_type', '')).replace('，', '+').split('+') if w.strip()]
            for w in ws2:
                word_freq[w] += 1
            entries.append((code, s, ws2))
        day_map = {}
        for code, s, ws2 in entries:
            kls = ktbl.get(code)
            if not kls:
                continue
            idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date_fmt), None)
            if idx is None or idx < 20:
                continue
            k, pk = kls[idx], kls[idx - 1]
            cons = 1
            j = idx - 1
            while j >= 1:
                if is_lu_pct(kls[j], kls[j - 1]):
                    cons += 1
                    j -= 1
                else:
                    break
            vols = [kls[t]['volume'] for t in range(max(0, idx - 20), idx) if kls[t].get('volume', 0) > 0]
            vr = k['volume'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1.0
            gap = (k['open'] - pk['close']) / pk['close'] * 100 if pk['close'] > 0 else 0
            lu_price = round(pk['close'] * 1.10, 2)
            is_yz = k['open'] >= lu_price - 0.005 and k['low'] >= lu_price - 0.005
            is_tz = k['open'] >= lu_price - 0.005 and k['close'] >= lu_price - 0.005 and k['low'] < lu_price - 0.005
            board_type = '一字' if is_yz else ('T字' if is_tz else '换手')
            try:
                to = float(s.get('turnover_rate', 0) or 0)
            except Exception:
                to = 0
            to_b = '<2' if to < 2 else ('2-20' if to < 20 else '>=20')
            try:
                seal_hm = datetime.fromtimestamp(int(s.get('first_limit_up_time'))).strftime('%H%M')
            except Exception:
                seal_hm = '1500'
            seal_b = '<5min' if seal_hm <= '0935' else ('5-10min' if seal_hm <= '0940' else (
                '10-30min' if seal_hm <= '1000' else ('30-60min' if seal_hm <= '1030' else '>60min')))
            zh = int(s.get('open_num', 0) or 0)
            zh_b = '0' if zh == 0 else ('1' if zh == 1 else ('2' if zh == 2 else '3+'))
            heat = max(word_freq[w] for w in ws2) if ws2 else 0
            sec_b = '<3' if heat < 3 else ('3-4' if heat < 5 else ('5-9' if heat < 10 else '>=10'))
            div_b = '分歧' if (zh >= 1 and vr >= 1.5) else '非分歧'
            if cons >= 3:
                dt_p = 30.5
            elif cons == 2:
                dt_p = 22.0
            elif vr >= 4:
                dt_p = 9.5
            elif vr < 1:
                dt_p = 4.1
            else:
                dt_p = 10.7
            f = {
                'vr': NORM['vr'].get(('<0.5' if vr < 0.5 else '0.5-1' if vr < 1 else '1-2' if vr < 2 else '2-4' if vr < 4 else '>=4'), 50),
                'gap': NORM['gap'].get(('<0' if gap < 0 else '0-2' if gap < 2 else '2-4' if gap < 4 else '4-6' if gap < 6 else '6-8' if gap < 8 else '8-10' if gap < 10 else '>=10'), 50),
                'board_type': NORM['board_type'].get(board_type, 50),
                'cons': NORM['cons'].get(('1' if cons == 1 else '2' if cons == 2 else '3' if cons == 3 else '4' if cons == 4 else '5+'), 55),
                'seal': NORM['seal'].get(seal_b, 60),
                'zhaban': NORM['zhaban'].get(zh_b, 70),
                'sector': NORM['sector'].get(sec_b, 70),
                'divergence': NORM['divergence'].get(div_b, 55),
                'dt_risk': max(10, min(100, 100 - (dt_p - 5) * 3)),
                'turnover': NORM.get('turnover', {}).get(to_b, 50),
            }
            day_map[code] = (f, board_type, cons, k)
        factor_days[date_fmt] = day_map
    return factor_days, temp_of

def simulate(factor_days, dates_fmt, pos_fn):
    """pos_fn(date) -> 仓位pct"""
    cash = INIT
    pos = None
    trades = []
    for i, d in enumerate(dates_fmt):
        if pos is not None and i > 0:
            prev_d = dates_fmt[i - 1]
            kls = ktbl.get(pos['code'])
            if kls:
                idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                if idx1 is not None and idx0 is not None:
                    k1, k0 = kls[idx1], kls[idx0]
                    yest_lu = is_lu_pct(k1, kls[idx1 - 1] if idx1 > 0 else None)
                    today_lu = is_lu_pct(k0, kls[idx0 - 1] if idx0 > 0 else None)
                    gap = (k0['open'] - k1['close']) / k1['close'] * 100
                    loss_min = (k0['low'] - pos['buy_price']) / pos['buy_price'] * 100
                    if loss_min <= -10:
                        sell_price = pos['buy_price'] * 0.90
                        action = 'sell'
                    elif yest_lu and gap < 0 and not today_lu:
                        sell_price = k0['high'] * (1 - COST)
                        action = 'sell'
                    elif not yest_lu and gap < 4 and not today_lu:
                        sell_price = k0['high'] * (1 - COST)
                        action = 'sell'
                    else:
                        action = 'hold'
                    if action == 'sell':
                        pnl = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                        cash += pos['shares'] * sell_price
                        trades.append({'pnl': pnl})
                        pos = None
        if pos is None and i > 0:
            prev_d = dates_fmt[i - 1]
            cands = []
            for code, (f, btype, cons, k) in factor_days.get(prev_d, {}).items():
                if btype == '一字' or (cons >= 4 and btype in ('一字', 'T字')):
                    continue
                score = sum(WEIGHTS[fac] * f[fac] for fac in FACTORS) / 100.0
                cands.append((score, code))
            cands.sort(key=lambda x: -x[0])
            for score, code in cands:
                kls = ktbl.get(code)
                if not kls:
                    continue
                idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                if idx0 is None or idx1 is None:
                    continue
                gap = (kls[idx0]['open'] - kls[idx1]['close']) / kls[idx1]['close'] * 100
                if not (4.0 <= gap <= 8.0):
                    continue
                price = kls[idx0]['open'] * (1 + COST)
                pct = pos_fn(d)
                if pct <= 0:
                    continue
                budget = cash * pct
                shares = int(min(cash, budget) / price / 100) * 100
                if shares <= 0:
                    continue
                cash -= shares * price
                pos = {'code': code, 'buy_date': d, 'buy_price': price, 'shares': shares}
                break
    final = cash
    if pos:
        kls = ktbl.get(pos['code'])
        if kls:
            final += pos['shares'] * kls[-1]['close'] * (1 - COST)
    return final, trades

def run(ws, we, label):
    fd, temp_of = build_factor_days(ws, we)
    dates_fmt = sorted(fd.keys())
    used_pct = []
    def temp_fn(d):
        p = temp_position(temp_of.get(d, 0))
        if p > 0:
            used_pct.append(p)
        return p
    schemes = {
        '温度四档(现行)': temp_fn,
        'A式恒定50%': lambda d: 0.5,
        'A式恒定55%': lambda d: 0.55,
        '恒定65%': lambda d: 0.65,
        '恒定70%': lambda d: 0.70,
        '恒定75%': lambda d: 0.75,
        '恒定全仓100%': lambda d: 1.0,
    }
    print(f'\n===== {label}窗 {ws}~{we} ({len(dates_fmt)}天) =====')
    print(f"{'仓位方案':<16}{'收益':>10}{'胜率':>8}{'笔数':>6}{'均笔':>8}{'期末资产':>12}")
    for name, fn in schemes.items():
        final, trades = simulate(fd, dates_fmt, fn)
        ret = (final / INIT - 1) * 100
        wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100 if trades else 0
        avg = sum(t['pnl'] for t in trades) / len(trades) if trades else 0
        print(f'{name:<16}{ret:>+9.1f}%{wr:>7.0f}%{len(trades):>6}{avg:>+7.2f}%{final:>12,.0f}')
    if used_pct:
        import statistics
        dist = {p: used_pct.count(p) for p in sorted(set(used_pct))}
        print(f'  ↳ 温度四档按笔仓位: 均{statistics.mean(used_pct):.0%} 分布{dist}')

for label, ws, we in WINDOWS:
    run(ws, we, label)
