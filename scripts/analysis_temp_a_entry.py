# -*- coding: utf-8 -*-
"""反解A的真实入场价: 用记录盈亏反推 隐含入场 = 出场价/(1+pnl)
检验: 隐含入场落在当日[low,high]的什么位置 (开盘? 均价? 低点?)
"""
import json, os, sys, io, statistics as st
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def rd(p):
    try: return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError: return json.load(open(p, encoding='gbk'))
rot = json.load(open('data/_a_rotation.json', encoding='utf-8'))
tr = json.load(open('data/_a_trades_enriched.json', encoding='utf-8'))
pnl_of = {}
for t in tr:
    if t.get('pnl') is not None:
        pnl_of.setdefault(t['name'], []).append(t['pnl'])
    else:
        pnl_of.setdefault(t['name'], []).append(None)

_k = {}
def kl(c):
    if c in _k: return _k[c]
    p = f'data/kline_data/{c}.json'
    m = None
    if os.path.exists(p):
        raw = rd(p); rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        m = {b['date']: b for b in rows if b.get('date')}
    _k[c] = m; return m
# name->code
nm = json.load(open('data/_a_trades_enriched.json', encoding='utf-8'))
code_of = {t['name']: t['code'] for t in nm}

rows = []
for r in rot:
    if not r['sell']: continue
    c = code_of.get(r['name'])
    if not c: continue
    m = kl(c)
    if not m or r['buy'] not in m: continue
    ds = sorted(m)
    ib = ds.index(r['buy'])
    if ib + 1 >= len(ds): continue
    b, b1 = m[r['buy']], m[ds[ib+1]]
    pnl = None
    for t in tr:
        if t['name'] == r['name'] and t.get('pnl') is not None:
            pnl = t['pnl']; break
    rows.append(dict(name=r['name'], code=c, buy=r['buy'], b=b, b1=b1, pnl=pnl))

have = [x for x in rows if x['pnl'] is not None]
print(f'可用 {len(rows)} 笔, 其中有盈亏 {len(have)} 笔\n')

print('=== 若"出场=次日最高", 反解入场价落在当日什么位置 ===')
print('%-9s %-11s %7s %7s %7s %7s %7s   %s' % ('名称','买入日','pnl','开','低','高','隐含入场','位置'))
pos = []
for x in have:
    b, b1, pnl = x['b'], x['b1'], x['pnl']
    imp = b1['high'] / (1 + pnl/100)
    rng = b['high'] - b['low']
    p = (imp - b['low'])/rng*100 if rng > 0 else None
    if p is not None: pos.append(p)
    print('%-9s %-11s %+7.1f %7.2f %7.2f %7.2f %7.3f   %s' % (
        x['name'], x['buy'], pnl, b['open'], b['low'], b['high'], imp,
        f'区间{p:.0f}%位' if p is not None else '出界'))
print(f'\n隐含入场在当日[低,高]区间的平均位置: {st.mean(pos):.1f}%  (0%=最低, 100%=最高, 开盘价位置另算)')
op = [(x['b']['open']-x['b']['low'])/(x['b']['high']-x['b']['low'])*100
      for x in have if x['b']['high'] > x['b']['low']]
print(f'对照: 开盘价在该区间的平均位置 {st.mean(op):.1f}%')
below = sum(1 for x in have if x['b']['high']/(1+x['pnl']/100) < x['b']['open'])
print(f'隐含入场 < 当日开盘价 的笔数: {below}/{len(have)}')
