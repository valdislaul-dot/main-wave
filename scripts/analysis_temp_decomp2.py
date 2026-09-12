# -*- coding: utf-8 -*-
"""二维分解: 选股 × 出场 (实盘窗口 08-10~09-11)"""
import json, os, sys, io, statistics as st
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def rd(p):
    try: return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError: return json.load(open(p, encoding='gbk'))
CACHE = json.load(open('data/_regime_klines_aug.json', encoding='utf-8'))
_loc = {}
def kl(c):
    if c in _loc: return _loc[c]
    p = f'data/kline_data/{c}.json'
    m = None
    if os.path.exists(p):
        raw = rd(p); rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        m = {b['date']: b for b in rows if b.get('date')}
    _loc[c] = m; return m
def bar(c, d):
    m = kl(c)
    if m and d in m: return m[d]
    for r in (CACHE.get(c) or []):
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
auc = {}
for f in sorted(os.listdir('data/auction')):
    if not f.endswith('.json') or '_' in f: continue
    data = json.load(open('data/auction/'+f, encoding='utf-8'))
    auc[f[:-5]] = {str(s.get('code','')).zfill(6): s for s in data.get('stocks', [])}

def trade(code, T, exit_rule):
    """T开盘买, 返回%"""
    b0 = bar(code, T); T1 = nxt(T)
    if not b0 or not T1 or not b0.get('open'): return None
    b1 = bar(code, T1)
    if not b1 or not b1.get('open'): return None
    e = b0['open']
    sealed = (b0.get('pct_change') or 0) >= 9.8
    if exit_rule == 'A式':
        lu = (b1.get('pct_change') or 0) >= 9.8
        p = b1.get('close') if lu else 0.7*(b1.get('high',0)+b1.get('open',0))/2 + 0.3*b1.get('close',0)
    elif exit_rule == 'A式_次高':
        p = b1.get('high')
    elif exit_rule == 'A式_保守开盘':
        lu = (b1.get('pct_change') or 0) >= 9.8
        p = b1.get('close') if lu else b1.get('open')
    elif exit_rule == 'A式_保守收盘':
        lu = (b1.get('pct_change') or 0) >= 9.8
        p = b1.get('close') if lu else b1.get('close')
    elif exit_rule == '仅T+1涨停卖':
        lu = (b1.get('pct_change') or 0) >= 9.8
        p = b1.get('close') if lu else None
    elif exit_rule == '引擎式':
        # 近似现有引擎: 昨涨停低开→开盘卖; 否则持有到次日(hmm)… 用"T收"近似做错即走
        p = b0.get('close') if sealed else b1.get('open')
    else: return None
    return (p - e) / e * 100 if p else None

START, END = '2026-08-10', '2026-09-11'
# 现有模型推荐
rev = json.load(open('logs/recommendation_review.json', encoding='utf-8'))['reviews']
mine = []
for d, r in rev.items():
    if not (START <= d <= END): continue
    for s in r['stocks']:
        c = str(s.get('code','')).zfill(6)
        mine.append(dict(T=d, code=c, name=s.get('name'), actual=s.get('pnl_pct')))

# 全池 (限可交易: 排除300/301/688/8/9 开头)
uni = []
for T in DAYS:
    if not (START <= T <= END) or T not in auc: continue
    prev = [x for x in DAYS if x < T]
    if not prev: continue
    D = prev[-1]
    for c in pools[D]:
        if c.startswith(('300','301','688','8','9')): continue
        s = auc[T].get(c)
        if not s: continue
        g = s.get('gap_pct') if s.get('gap_pct') is not None else None
        if g is None and s.get('open') and s.get('prev_close'):
            g = (s['open']-s['prev_close'])/s['prev_close']*100
        if g is None: continue
        uni.append(dict(T=T, code=c, gap=float(g)))

def rep(lab, arr, rule):
    vs = [v for v in (trade(x['code'], x['T'], rule) for x in arr) if v is not None]
    if not vs: print(f'  {lab:38s} 无样本'); return None
    print(f'  {lab:38s} n={len(vs):4d}  均 {st.mean(vs):+6.2f}%  胜率 {sum(1 for v in vs if v>0)/len(vs)*100:4.0f}%')
    return st.mean(vs)

print('=== 出场规则敏感性 (选股固定=全池 gap4-8%) ===')
for _r in ('A式', 'A式_保守开盘', 'A式_保守收盘', 'A式_次高', '仅T+1涨停卖'):
    rep(_r, [x for x in uni if 4 <= x['gap'] <= 8], _r)

print('\n=== 二维分解 (实盘窗口 08-10~09-11) ===')
print('\n[出场 = A式 (T+1涨停→涨停价挂单成交 / 否则 70%(H+O)/2+30%收)]')
a1 = rep('选股=全池 (gap>0, 可交易)', [x for x in uni if x['gap'] > 0], 'A式')
a2 = rep('选股=全池 (gap 4-8%)', [x for x in uni if 4 <= x['gap'] <= 8], 'A式')
a3 = rep('选股=现有模型Top3', mine, 'A式')
print('\n[出场 = A式_保守开盘 (T+1涨停→涨停价 / 否则→次日开盘价)]')
rep('选股=全池 (gap>0, 可交易)', [x for x in uni if x['gap'] > 0], 'A式_保守开盘')
rep('选股=全池 (gap 4-8%)', [x for x in uni if 4 <= x['gap'] <= 8], 'A式_保守开盘')
rep('选股=现有模型Top3', mine, 'A式_保守开盘')
print('\n[出场 = 现有引擎式]')
b1 = rep('选股=全池 (gap>0)', [x for x in uni if x['gap'] > 0], '引擎式')
b2 = rep('选股=全池 (gap 4-8%)', [x for x in uni if 4 <= x['gap'] <= 8], '引擎式')
vs = [x['actual'] for x in mine if x['actual'] is not None]
print(f'  {"选股=现有模型Top3 (实测账)":38s} n={len(vs):4d}  均 {st.mean(vs):+6.2f}%  胜率 {sum(1 for v in vs if v>0)/len(vs)*100:4.0f}%')

print('\n=== 稳健性 (选股=全池 gap4-8%) ===')
import math as _m
from collections import defaultdict as _dd
_sel = [x for x in uni if 4 <= x['gap'] <= 8]
for _r in ('A式', 'A式_保守开盘', '引擎式'):
    _vs = [v for v in (trade(x['code'], x['T'], _r) for x in _sel) if v is not None]
    _se = st.pstdev(_vs) / _m.sqrt(len(_vs))
    print('  %-14s n=%3d 均%+6.2f%% 中位%+6.2f%% 标准差%.1f t=%.2f %s' % (
        _r, len(_vs), st.mean(_vs), st.median(_vs), st.pstdev(_vs),
        st.mean(_vs)/_se, '(显著)' if abs(st.mean(_vs)/_se) > 1.96 else '(不显著)'))
_bym = _dd(list)
for x in _sel:
    v = trade(x['code'], x['T'], 'A式')
    if v is not None: _bym[x['T'][:7]].append(v)
print('  A式 按月: ' + ' | '.join(
    '%s n=%d 均%+.2f%% 胜%.0f%%' % (m, len(_bym[m]), st.mean(_bym[m]),
    sum(1 for v in _bym[m] if v > 0)/len(_bym[m])*100) for m in sorted(_bym)))
