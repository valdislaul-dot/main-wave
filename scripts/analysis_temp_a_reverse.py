# -*- coding: utf-8 -*-
"""用K线反推A的真实买卖价规则: 遍历常见入场/出场组合, 找出与记录盈亏最吻合的"""
import json, os, sys, io, glob, statistics as st
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
rot = json.load(open('data/_a_rotation.json', encoding='utf-8'))
def rd(p):
    try: return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError: return json.load(open(p, encoding='gbk'))
# name -> code
nm = {}
for p in glob.glob('data/kline_data/*_*.json'):
    b = os.path.basename(p)[:-5]
    n, _, c = b.rpartition('_')
    if c.isdigit(): nm.setdefault(n, c)
for base in ('data/zt_pool_history_ths',):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json'): continue
        d = rd(os.path.join(base, f))
        for x in (d if isinstance(d, list) else d.get('stocks', [])):
            if x.get('name') and x.get('code'): nm.setdefault(x['name'], str(x['code']).zfill(6))
tr = {t['name'] + t['buy_date']: t for t in json.load(open('data/_a_trades_enriched.json', encoding='utf-8'))}

cache = {}
def kl(code):
    if code in cache: return cache[code]
    p = f'data/kline_data/{code}.json'
    m = None
    if os.path.exists(p):
        raw = rd(p); rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        m = {b['date']: b for b in rows if b.get('date')}
    cache[code] = m
    return m

recs = []
for r in rot:
    if not r['sell']: continue
    code = nm.get(r['name'])
    if not code: continue
    m = kl(code)
    if not m: continue
    ds = sorted(m)
    if r['buy'] not in m or r['sell'] not in m: continue
    ib, isl = ds.index(r['buy']), ds.index(r['sell'])
    b, s = m[r['buy']], m[r['sell']]
    prev = m[ds[ib-1]] if ib > 0 else None
    recs.append(dict(name=r['name'], code=code, buy=ib, sell=isl, b=b, s=s, prev=prev,
                     gap=(b['open']-prev['close'])/prev['close']*100 if prev else None))
print(f'可用 {len(recs)} 笔\n')

# 记录盈亏
def pnl(name, code):
    for k, v in tr.items():
        if k.startswith(name) and v.get('pnl') is not None:
            return v['pnl']
    return None

rules = {
    '买入日开盘 → 次日开盘': lambda r: (r['s']['open'] - r['b']['open']) / r['b']['open'] * 100,
    '买入日开盘 → 次日收盘': lambda r: (r['s']['close'] - r['b']['open']) / r['b']['open'] * 100,
    '买入日开盘 → 次日最高': lambda r: (r['s']['high'] - r['b']['open']) / r['b']['open'] * 100,
    '买入日开盘 → 次日涨停价': lambda r: ((r['prev']['close'] * 1.1 if r['prev'] else 0) - r['b']['open']) / r['b']['open'] * 100,
    '买入日收盘 → 次日开盘': lambda r: (r['s']['open'] - r['b']['close']) / r['b']['close'] * 100,
    '买入日收盘 → 次日收盘': lambda r: (r['s']['close'] - r['b']['close']) / r['b']['close'] * 100,
}
have = [r for r in recs if pnl(r['name'], r['code']) is not None]
print(f'有记录盈亏的 {len(have)} 笔 — 各规则与记录值的平均绝对误差:')
for lab, fn in rules.items():
    errs = []
    for r in have:
        v = pnl(r['name'], r['code'])
        try: errs.append(abs(fn(r) - v))
        except Exception: pass
    if errs: print(f'  {lab:24s} MAE {st.mean(errs):7.2f}pt  (吻合<1.5pt的: {sum(1 for e in errs if e<1.5)}/{len(errs)})')

print('\n=== 明细对照 (前20笔有盈亏的) ===')
print('%-9s %-11s %-11s %7s %7s %7s %7s %7s %8s' % (
    '名称','买入日','卖出日','记录pnl','开→次开','开→次收','开→次高','收→次收','买入gap'))
for r in have[:20]:
    v = pnl(r['name'], r['code'])
    print('%-9s %-11s %-11s %+7.1f %+7.1f %+7.1f %+7.1f %+7.1f %+8.1f' % (
        r['name'], '', '', v,
        (r['s']['open']-r['b']['open'])/r['b']['open']*100,
        (r['s']['close']-r['b']['open'])/r['b']['open']*100,
        (r['s']['high']-r['b']['open'])/r['b']['open']*100,
        (r['s']['close']-r['b']['close'])/r['b']['close']*100,
        r['gap'] or 0))
