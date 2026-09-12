# -*- coding: utf-8 -*-
"""最终分解: 封板率 = 体制基率 + 选股alpha; 用「同日同gap档基率」做公平对照
封板判定统一 = D+1 是否在当日涨停池名单中 (池文件=全市场涨停, 无K线依赖)
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
DAYS = sorted(pools)
def nextday(d):
    nx = [x for x in DAYS if x > d]
    return nx[0] if nx else None

def gap_and_seal(d, code):
    """D为涨停日, 返回(D+1开盘gap, D+1是否封板)"""
    n1 = nextday(d)
    if not n1: return None, None
    kl_p = f'data/kline_data/{code}.json'
    if not os.path.exists(kl_p): return None, None
    raw = rd(kl_p)
    rows = raw.get('data', raw) if isinstance(raw, dict) else raw
    m = {b['date']: b for b in rows if b.get('date')}
    b0, b1 = m.get(d), m.get(n1)
    if not b0 or not b1 or not b0.get('close') or not b1.get('open'): return None, None
    return (b1['open'] - b0['close']) / b0['close'] * 100, (1 if code in pools[n1] else 0)

# ---------- 基率表 (按时代 × gap档) ----------
BASE = {'A': defaultdict(list), 'U': defaultdict(list)}
def bucket(g):
    if g < 0: return '<0'
    if g < 2: return '0-2'
    if g < 4: return '2-4'
    if g < 6: return '4-6'
    if g < 8: return '6-8'
    if g < 10: return '8-10'
    return '>=10'

for d in DAYS:
    if not ('2026-03-01' <= d <= '2026-09-11'): continue
    era = 'A' if d <= '2026-07-31' else 'U'
    if d in pools and len(pools[d]) > 0:
        for c in pools[d]:
            g, s = gap_and_seal(d, c)
            if g is not None:
                BASE[era][bucket(g)].append(s)

print('=== 基率: D+1封板率 (按gap档) ===')
print('%-9s %8s %8s %10s %10s' % ('gap档','A时代n','A封板率','我方n','我方封板率'))
for b in ('<0','0-2','2-4','4-6','6-8','8-10','>=10'):
    a, u = BASE['A'][b], BASE['U'][b]
    fa = f'{sum(a)/len(a)*100:.1f}%' if len(a) >= 20 else '样本少'
    fu = f'{sum(u)/len(u)*100:.1f}%' if len(u) >= 20 else '样本少'
    print('%-9s %8d %8s %10d %10s' % (b, len(a), fa, len(u), fu))

def base_for(era, g):
    a = BASE[era][bucket(g)]
    return sum(a)/len(a)*100 if len(a) >= 20 else None

# ---------- A 的选股 ----------
a_tr = json.load(open('data/_a_trades_enriched.json', encoding='utf-8'))
a_rows = []
for t in a_tr:
    d = nextday(t['buy_date'])  # 反推: 买入日前一交易日 = D
    prev = [x for x in DAYS if x < t['buy_date']]
    if not prev: continue
    d = prev[-1]
    if t['code'] not in pools.get(d, set()):   # 非 T-1涨停 接力, 剔除
        continue
    g, s = gap_and_seal(d, t['code'])
    if g is None: continue
    a_rows.append(dict(gap=g, seal=s, base=base_for('A', g), pnl=t['pnl']))

# ---------- 我方推荐 ----------
rev = json.load(open('logs/recommendation_review.json', encoding='utf-8'))['reviews']
u_rows = []
for date, r in rev.items():
    for s in r['stocks']:
        code = str(s.get('code', '')).zfill(6)
        d = nextday(date)   # 推荐日date=T(买入日), 需要 T-1
        prev = [x for x in DAYS if x < date]
        if not prev: continue
        d0 = prev[-1]
        g, seal = gap_and_seal(d0, code)
        gg = s.get('rec_gap')
        u_rows.append(dict(date=date, gap=gg, seal=seal if seal is not None else 0,
                           base=base_for('U', gg) if gg is not None else None,
                           pnl=s.get('pnl_pct')))

def report(name, rows, era):
    rs = [r for r in rows if r['base'] is not None]
    if not rs: print(f'{name}: 无可用样本'); return
    actual = sum(r['seal'] for r in rs)/len(rs)*100
    base = st.mean([r['base'] for r in rs])
    pnl = [r['pnl'] for r in rs if r['pnl'] is not None]
    print(f'\n[{name}]  n={len(rs)}')
    print(f'  实际封板率   {actual:5.1f}%')
    print(f'  同期同gap基率 {base:5.1f}%')
    print(f'  选股alpha    {actual-base:+5.1f}pt  (lift {actual/base:.2f}x)')
    if pnl: print(f'  实际收益 均 {st.mean(pnl):+.2f}%  胜率 {sum(1 for x in pnl if x>0)/len(pnl)*100:.0f}%')

print('\n' + '='*64)
print('=== 选股alpha 分解 (同期同gap档基率对照) ===')
report('A 的实盘交易', a_rows, 'A')
report('我方 66 笔推荐(全期)', u_rows, 'U')
us = [r for r in u_rows if r['date'] >= '2026-09-01']
report('我方 09月推荐', us, 'U')
json.dump(dict(a=a_rows, u=u_rows), open('data/_decompose.json','w',encoding='utf-8'), ensure_ascii=False)
