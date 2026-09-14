# -*- coding: utf-8 -*-
"""复刻A的操作流程 在实盘窗口(08-10~09-11)上回测, 与现有模型实盘对照
A流程(从xlsx+K线反推): T-1涨停 → T竞价高开 → T开盘买 → T+1冲高卖; 单票轮动
入场gap用竞价快照(全覆盖), 出场价用补拉K线缓存
"""
import json, os, sys, io, statistics as st
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def rd(p):
    try: return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError: return json.load(open(p, encoding='gbk'))

CACHE = json.load(open('data/_regime_klines_aug.json', encoding='utf-8'))
_loc = {}
def kl(code):
    if code in _loc: return _loc[code]
    p = f'data/kline_data/{code}.json'
    m = None
    if os.path.exists(p):
        raw = rd(p); rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        m = {b['date']: b for b in rows if b.get('date')}
    _loc[code] = m
    return m
def bar(code, d):
    """优先本地(更全的历史), 缺则补拉缓存"""
    m = kl(code)
    if m and d in m: return m[d]
    for r in (CACHE.get(code) or []):
        if r.get('date') == d: return r
    return None

pools = {}
for base in ('data/zt_pool_history_ths', 'data/zt_pool'):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json') or f == 'stock_index.json': continue
        ymd = f[:-5]; d = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
        data = rd(os.path.join(base, f))
        rows = data if isinstance(data, list) else data.get('stocks', [])
        pools[d] = {str(x.get('code','')).zfill(6): x for x in rows if x.get('code')}
DAYS = sorted(pools)
def nxt(d, k=1):
    nx = [x for x in DAYS if x > d]
    return nx[k-1] if len(nx) >= k else None

# 竞价快照: T日 gap + open
auc = {}
for f in sorted(os.listdir('data/auction')):
    if not f.endswith('.json') or '_' in f: continue
    day = f[:-5]
    data = json.load(open('data/auction/'+f, encoding='utf-8'))
    auc[day] = {str(s.get('code','')).zfill(6): s for s in data.get('stocks', [])}

START, END = '2026-08-10', '2026-09-11'
print(f'窗口 {START} ~ {END}\n')

# 构造候选: 每天 T, 取 T-1池 且在 T竞价快照里有gap的
cands = []
for T in DAYS:
    if not (START <= T <= END): continue
    if T not in auc: continue
    prev = [x for x in DAYS if x < T]
    if not prev: continue
    D = prev[-1]
    for c in pools[D]:
        s = auc[T].get(c)
        if not s: continue
        g = s.get('gap_pct')
        if g is None and s.get('open') and s.get('prev_close'):
            g = (s['open']-s['prev_close'])/s['prev_close']*100
        if g is None: continue
        b0 = bar(c, T)
        if not b0 or not b0.get('open'): continue
        cands.append(dict(T=T, D=D, code=c, gap=float(g), entry=b0['open'] if b0 else s.get('open')))
print(f'候选(T-1涨停股带竞价gap) {len(cands)} 个票次')

def ret(c, T, rule):
    """入场=T开盘, 按rule出场, 返回%"""
    b0 = bar(c, T); T1 = nxt(T)
    if not b0 or not T1: return None
    b1 = bar(c, T1)
    if not b1: return None
    e = b0.get('open')
    if not e: return None
    sealed = (b0.get('pct_change') or 0) >= 9.8
    if rule == 'A_次高':   p = b1.get('high')
    elif rule == '次开':   p = b1.get('open')
    elif rule == '次收':   p = b1.get('close')
    elif rule == 'T收':    p = b0.get('close')
    elif rule == '封板持次日高_否则T收': p = b1.get('high') if sealed else b0.get('close')
    elif rule == '封板持次日高_否则次开': p = b1.get('high') if sealed else b1.get('open')
    elif rule == '可执行A':   # T+1涨停→涨停价(挂单成交,=最高); 否则(H+O)/2近似冲高
        lu = (b1.get('pct_change') or 0) >= 9.8
        p = b1.get('close') if lu else (b1.get('high',0)+b1.get('open',0))/2
    elif rule == '可执行A_保守':  # T+1涨停→收盘(=涨停价) ; 否则70%(H+O)/2+30%收
        lu = (b1.get('pct_change') or 0) >= 9.8
        p = b1.get('close') if lu else 0.7*(b1.get('high',0)+b1.get('open',0))/2 + 0.3*b1.get('close',0)
    else: return None
    if not p: return None
    return (p - e) / e * 100

def run(name, sel, rule):
    rs = [r for r in sel if (v := ret(r['code'], r['T'], rule)) is not None]
    if not rs: print(f'{name:34s} 无样本'); return
    vs = [ret(r['code'], r['T'], rule) for r in rs]
    print(f'{name:34s} n={len(rs):4d}  均 {st.mean(vs):+6.2f}%  胜率 {sum(1 for v in vs if v>0)/len(vs)*100:4.0f}%  '
          f'中位 {st.median(vs):+6.2f}%')

print('\n=== 全池(不限gap) 各出场规则 ===')
for rule in ('A_次高','次开','次收','T收','可执行A','可执行A_保守'):
    run(f'全池 / {rule}', [r for r in cands if r['gap'] > 0], rule)

print('\n=== gap分档 (出场=次日最高, A口径) ===')
for lo, hi, lab in ((-99, 0, 'gap<0 (A不做)'), (0, 2, 'gap 0-2%'), (2, 4, '2-4%'),
                    (4, 6, '4-6%'), (6, 8, '6-8%'), (8, 10, '8-10%'), (10, 99, '>=10% 一字')):
    run(f'{lab} / A_次高', [r for r in cands if lo <= r['gap'] < hi], 'A_次高')

print('\n=== 对照: 现有模型实测(推荐回看 同窗口) ===')
rev = json.load(open('logs/recommendation_review.json', encoding='utf-8'))['reviews']
u = [(d, s.get('pnl_pct')) for d, r in rev.items() if START <= d <= END for s in r['stocks'] if s.get('pnl_pct') is not None]
if u:
    print(f'{"现有模型 66→本窗口":34s} n={len(u):4d}  均 {st.mean([x[1] for x in u]):+6.2f}%  胜率 {sum(1 for x in u if x[1]>0)/len(u)*100:4.0f}%')
