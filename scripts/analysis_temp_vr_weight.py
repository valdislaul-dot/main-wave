# -*- coding: utf-8 -*-
"""临时分析(2026-09-07): vr量比因子权重提升验证
1. 模型池内(gap4-8窗口+Top1+恒定55%) vr分段的一年表现(胜率/均笔)
2. vr权重扫描 5.9%→6/8/10/12/15/20%(其余因子等比缩放) 的一年收益/胜率/均笔
口径=backtest_v4同框架(定稿权重+决策树卖出+开盘价执行+A式恒定55%仓位)
只读数据, 不写回任何配置。
"""
import json, os, sys
from datetime import datetime
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
INIT = 200000
COST = 0.00125
FACTORS = ['vr', 'gap', 'board_type', 'cons', 'seal', 'zhaban', 'sector', 'divergence', 'dt_risk', 'turnover']
WS, WE = '2025-09-01', '2026-08-19'

with open(os.path.join(BASE, 'data', 'scoring_config.json'), encoding='utf-8') as f:
    _cfg = json.load(f)
WEIGHTS = _cfg['v4']['weights']
NORM = _cfg['v4']['normalize']

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
all_dates = [fn.replace('.json', '') for fn in ths_files if WS.replace('-', '') <= fn.replace('.json', '') <= WE.replace('-', '')]

# 因子预计算(与backtest_v4同口径, 额外保存vr原始值)
factor_days = {}
for ymd in all_dates:
    date_fmt = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
    with open(os.path.join(THS_DIR, f'{ymd}.json'), encoding='utf-8') as f:
        info = json.load(f)
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
        day_map[code] = (f, board_type, cons, k, vr)
    factor_days[date_fmt] = day_map
print(f'因子预计算: {len(factor_days)}天')

def simulate(weights, dates_fmt):
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
                        trades.append({'pnl': pnl, 'vr': pos.get('vr')})
                        pos = None
        if pos is None and i > 0:
            prev_d = dates_fmt[i - 1]
            cands = []
            for code, (f, btype, cons, k, vr) in factor_days.get(prev_d, {}).items():
                if btype == '一字' or (cons >= 4 and btype in ('一字', 'T字')):
                    continue
                score = sum(weights[fac] * f[fac] for fac in FACTORS) / 100.0
                cands.append((score, code, vr))
            cands.sort(key=lambda x: -x[0])
            for score, code, vr in cands:
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
                budget = cash * 0.55  # A式恒定55%
                shares = int(min(cash, budget) / price / 100) * 100
                if shares <= 0:
                    continue
                cash -= shares * price
                pos = {'code': code, 'buy_date': d, 'buy_price': price, 'shares': shares, 'vr': vr}
                break
    final = cash
    if pos:
        kls = ktbl.get(pos['code'])
        if kls:
            final += pos['shares'] * kls[-1]['close'] * (1 - COST)
            # 期末持仓不入trades(无卖出pnl)
    return final, trades

def vr_bucket(vr):
    if vr < 0.5: return '<0.5x(缩量)'
    if vr < 1: return '0.5-1x'
    if vr < 2: return '1-2x'
    if vr < 4: return '2-4x'
    return '>=4x(爆量)'

dates_fmt = sorted(factor_days.keys())

# 1. 定稿权重下的 vr 分段表现
final, trades = simulate(WEIGHTS, dates_fmt)
ret = (final / INIT - 1) * 100
print(f'\n===== 1. vr分段表现 (定稿权重, 一年窗, N={len(trades)}笔, 总收益{ret:+.1f}%) =====')
by_vr = defaultdict(list)
for t in trades:
    by_vr[vr_bucket(t['vr'])].append(t['pnl'])
print(f"{'vr段':<14}{'笔数':>5}{'胜率':>8}{'均笔':>8}{'合计':>9}")
for b in ['<0.5x(缩量)', '0.5-1x', '1-2x', '2-4x', '>=4x(爆量)']:
    pnls = by_vr.get(b, [])
    if not pnls:
        continue
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    print(f'{b:<14}{len(pnls):>5}{wr:>7.0f}%{sum(pnls)/len(pnls):>+8.2f}%{sum(pnls):>+8.1f}%')

# 2. vr 权重扫描
print(f'\n===== 2. vr权重扫描 (其余因子等比缩放补足, 一年窗恒定55%) =====')
print(f"{'vr权重':>8}{'收益':>12}{'胜率':>8}{'笔数':>6}{'均笔':>8}")
results = []
for w in [5.9, 6, 8, 10, 12, 15, 20]:
    if abs(w - WEIGHTS['vr']) < 0.01:
        wts = dict(WEIGHTS)  # 定稿权重原值, 不做缩放
    else:
        wts = {k: v for k, v in WEIGHTS.items() if k != 'vr'}
        s_rest = sum(wts.values())
        for k in wts:
            wts[k] = round(wts[k] * (100 - w) / s_rest, 2)
        wts['vr'] = round(w, 2)
    final, tr = simulate(wts, dates_fmt)
    r = (final / INIT - 1) * 100
    wr = sum(1 for t in tr if t['pnl'] > 0) / len(tr) * 100 if tr else 0
    avg = sum(t['pnl'] for t in tr) / len(tr) if tr else 0
    results.append((w, r, wr, len(tr), avg))
    print(f'{w:>7.1f}%{r:>+11.1f}%{wr:>7.0f}%{len(tr):>6}{avg:>+7.2f}%')

# 3. vr归一化形状修正扫描 (定稿权重vr=9.5不变)
# 现行形状 <0.5:100/0.5-1:75/1-2:60/2-4:45/>=4:25 — 与池内实际U型表现矛盾
print(f'\n===== 3. vr归一化形状修正 (定稿权重, 一年窗恒定55%) =====')
print(f"{'形状方案':<46}{'收益':>12}{'胜率':>8}{'笔数':>6}{'均笔':>8}")
SHAPES = [
    ('现行 100/75/60/45/25', None),
    ('U型A 100/40/60/75/50', {'<0.5': 100, '0.5-1': 40, '1-2': 60, '2-4': 75, '>=4': 50}),
    ('U型B 100/35/55/80/60', {'<0.5': 100, '0.5-1': 35, '1-2': 55, '2-4': 80, '>=4': 60}),
    ('U型C 100/30/50/85/70', {'<0.5': 100, '0.5-1': 30, '1-2': 50, '2-4': 85, '>=4': 70}),
    ('仅压0.5-1 100/40/60/45/25', {'<0.5': 100, '0.5-1': 40, '1-2': 60, '2-4': 45, '>=4': 25}),
    ('仅提2-4 100/75/60/75/25', {'<0.5': 100, '0.5-1': 75, '1-2': 60, '2-4': 75, '>=4': 25}),
]
for label, shape in SHAPES:
    if shape is None:
        # 现行形状: 直接用第一节定稿结果
        print(f'{label:<46}{ret:>+11.1f}%{sum(1 for t in trades if t["pnl"]>0)/len(trades)*100:>7.0f}%{len(trades):>6}{sum(t["pnl"] for t in trades)/len(trades):>+7.2f}%')
        continue
    # 形状影响factor_days预存的归一化分, 重建f['vr']
    fd_new = {}
    for df2, dmap in factor_days.items():
        dmap2 = {}
        for code, (f0, bt, cs, k0, vr0) in dmap.items():
            f2 = dict(f0)
            f2['vr'] = shape.get(('<0.5' if vr0 < 0.5 else '0.5-1' if vr0 < 1 else '1-2' if vr0 < 2 else '2-4' if vr0 < 4 else '>=4'), 50)
            dmap2[code] = (f2, bt, cs, k0, vr0)
        fd_new[df2] = dmap2
    _saved = factor_days
    globals()['factor_days'] = fd_new
    final, tr = simulate(WEIGHTS, dates_fmt)
    globals()['factor_days'] = _saved
    r = (final / INIT - 1) * 100
    wr = sum(1 for t in tr if t['pnl'] > 0) / len(tr) * 100 if tr else 0
    avg = sum(t['pnl'] for t in tr) / len(tr) if tr else 0
    print(f'{label:<46}{r:>+11.1f}%{wr:>7.0f}%{len(tr):>6}{avg:>+7.2f}%')
