# -*- coding: utf-8 -*-
"""gap分档 → 次日封板率 (分档基率), 对照A与我方选股的实际封板率
我方时代: 竞价快照(D+1开盘实时) + D+1池(全市场涨停名单) → 完全无缺失
A时代: 本地K线(搜狐历史快照, 连续覆盖) 
"""
import json, os, sys, io, statistics as st
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def rd(p):
    try: return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError: return json.load(open(p, encoding='gbk'))

pools = {}
for base in ('data/zt_pool_history_ths', 'data/zt_pool'):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json') or f == 'stock_index.json': continue
        ymd = f[:-5]; d = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
        data = rd(os.path.join(base, f))
        rows = data if isinstance(data, list) else data.get('stocks', [])
        pools[d] = {str(x.get('code', '')).zfill(6) for x in rows if x.get('code')}

def klmap(code):
    p = f'data/kline_data/{code}.json'
    if not os.path.exists(p): return None
    raw = rd(p)
    rows = raw.get('data', raw) if isinstance(raw, dict) else raw
    return {b['date']: b for b in rows if b.get('date')}

# ---------- 我方时代: 竞价快照 ----------
auc = {}
for f in sorted(os.listdir('data/auction')):
    if not f.endswith('.json'): continue
    d = json.load(open('data/auction/' + f, encoding='utf-8'))
    for s in d.get('stocks', []):
        c = str(s.get('code', '')).zfill(6)
        g = s.get('gap_pct')
        if g is None and s.get('open') and s.get('prev_close'):
            g = (s['open'] - s['prev_close']) / s['prev_close'] * 100
        if g is not None:
            auc.setdefault(f[:-5], {})[c] = float(g)

rows_u = []
for day, gm in auc.items():
    d = day if '-' in day else f'{day[:4]}-{day[4:6]}-{day[6:8]}'
    if d not in pools: continue
    nxt = None
    later = sorted(x for x in pools if x > d)
    if not later: continue
    nxt = pools[later[0]]
    for c, g in gm.items():
        if c not in pools[d]: continue
        rows_u.append(dict(date=d, code=c, gap=g, seal=1 if c in nxt else 0))

# ---------- A时代: K线 ----------
rows_a = []
for base in ('data/zt_pool_history_ths',):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json'): continue
        ymd = f[:-5]; d = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
        if not ('2026-03-01' <= d <= '2026-07-31'): continue
        later = sorted(x for x in pools if x > d)
        if not later: continue
        nxt = pools[later[0]]
        for c in pools[d]:
            kl = klmap(c)
            if not kl: continue
            b0, b1 = kl.get(d), kl.get(later[0])
            if not b0 or not b1 or not b0.get('close') or not b1.get('open'): continue
            g = (b1['open'] - b0['close']) / b0['close'] * 100
            rows_a.append(dict(date=d, code=c, gap=g, seal=1 if c in nxt else 0))

def show(name, rows, lo, hi):
    a = [r for r in rows if lo <= r['gap'] < hi]
    if len(a) < 15: return f'  {name:12s} n={len(a):5d}  样本不足'
    return (f'  {name:12s} n={len(a):5d} | 次日封板率 {sum(r["seal"] for r in a)/len(a)*100:5.1f}%')

print('=== gap分档 → 次日(买入日)封板率 ===')
for name, rows in (('A时代03~07', rows_a), ('我方08~09', rows_u)):
    print(f'\n[{name}]  总样本 {len(rows)}')
    for lo, hi, lab in ((-99, 0, 'gap<0 低开'), (0, 2, 'gap 0-2%'), (2, 4, 'gap 2-4%'),
                        (4, 6, 'gap 4-6%'), (6, 8, 'gap 6-8%'), (8, 10, 'gap 8-10%'),
                        (10, 99, 'gap>=10% 一字')):
        print(show(lab, rows, lo, hi))
    a = [r for r in rows if 4 <= r['gap'] < 8]
    print(f'  {"买入窗4-8%":12s} n={len(a):5d} | 次日封板率 {sum(r["seal"] for r in a)/len(a)*100:5.1f}%')

print('\n=== 对照: 实际选股封板率 ===')
print('  A 的 52 笔:        封板率 63.5%  (33/52)')
print('  我方 66 笔推荐:     封板率 31.8%  (21/66)')
print('  其中 09月 21 笔:    封板率  4.8%  (1/21)')
json.dump(dict(a=rows_a, u=rows_u), open('data/_gap_seal_rows.json','w',encoding='utf-8'), ensure_ascii=False)
