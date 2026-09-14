# -*- coding: utf-8 -*-
"""最终策略: 封板则继续持有(格局) vs 封板即卖
入场 T开盘(gap4-8%) | 出场: 不封板日按 A式(70%(H+O)/2+30%C)
"""
import json, os, sys, io, warnings, statistics as st
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))


pools = {}
for base in ('data/zt_pool_history_ths', 'data/zt_pool'):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json') or f == 'stock_index.json':
            continue
        ymd = f[:-5]
        d = ymd[:4] + '-' + ymd[4:6] + '-' + ymd[6:8]
        data = rd(os.path.join(base, f))
        rows = data if isinstance(data, list) else data.get('stocks', [])
        pools[d] = {str(x.get('code', '')).zfill(6) for x in rows if x.get('code')}
DAYS = sorted(pools)
NX = {d: DAYS[i + 1] for i, d in enumerate(DAYS) if i + 1 < len(DAYS)}
AUG = json.load(open('data/_regime_klines_aug.json', encoding='utf-8'))
KL = {}


def kl(c):
    if c in KL:
        return KL[c]
    p = 'data/kline_data/' + c + '.json'
    out = {}
    if os.path.exists(p):
        raw = rd(p)
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        out = {b['date']: b for b in rows if b.get('date')}
    KL[c] = out
    return out


def kb(c, d):
    m = kl(c)
    if d in m:
        return m[d]
    for r in (AUG.get(c) or []):
        if r.get('date') == d:
            return r
    return None


def aexit(b):
    lu = (b.get('pct_change') or 0) >= 9.8
    if lu:
        return b['close']
    return 0.7 * (b['high'] + b['open']) / 2 + 0.3 * b['close']


df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
df['code'] = df['code'].astype(str).str.zfill(6)
df = df.dropna(subset=['gap'])
sel = df[(df['gap'] >= 4) & (df['gap'] <= 8)].copy()

recs = []
for _, r in sel.iterrows():
    # 数据集 date = 涨停日D; 买入日 T = D+1; 出场日 T1 = D+2
    T = NX.get(r['date'])
    T1 = NX.get(T) if T else None
    if not T or not T1:
        continue
    b0, b1 = kb(r['code'], T), kb(r['code'], T1)
    if not b0 or not b1 or not b0.get('open'):
        continue
    e = b0['open']
    sealed1 = r['code'] in pools.get(T1, set())
    # 策略A: T+1 一律按A式出
    retA = (aexit(b1) - e) / e * 100
    # 策略B: T+1封板则继续持有, 直到首个非封板日按A式出(最多3天)
    if not sealed1:
        retB = retA
    else:
        cur, cur_d, prev_sealed = e, T1, True
        for step in range(3):
            nd = NX.get(cur_d)
            if not nd:
                break
            bn = kb(r['code'], nd)
            if not bn:
                break
            if r['code'] in pools.get(nd, set()):
                cur_d = nd
                continue
            retB = (aexit(bn) - e) / e * 100
            prev_sealed = False
            break
        else:
            bn = kb(r['code'], cur_d)
            retB = (aexit(bn) - e) / e * 100 if bn else retA
        if prev_sealed:
            bn = kb(r['code'], cur_d)
            retB = (aexit(bn) - e) / e * 100 if bn else retA
    recs.append(dict(date=T, code=r['code'], gap=r['gap'], seal1=sealed1,
                     retA=retA, retB=retB))

d = pd.DataFrame(recs)
print('gap4-8%% 样本 %d | T+1封板率 %.1f%%\n' % (len(d), d['seal1'].mean()*100))
for lab, dd in (('全期', d), ('训练 2025-06~2026-03', d[d['date'] < '2026-04-01']),
                ('验证 2026-04~09', d[d['date'] >= '2026-04-01'])):
    if len(dd) < 30:
        continue
    print('【%s】n=%d' % (lab, len(dd)))
    for k, nm in (('retA', 'A) T+1一律A式出'), ('retB', 'B) 封板则继续持有')):
        v = dd[k].values
        se = st.pstdev(v) / len(v) ** 0.5
        print('    %-20s 均%+6.2f%% 中位%+6.2f%% 胜率%3.0f%% t=%5.2f 最大%+.1f%%' % (
            nm, v.mean(), np.median(v), (v > 0).mean()*100, v.mean()/se, v.max()))
    # 配对
    dv = (dd['retB'] - dd['retA']).values
    se = st.pstdev(dv) / len(dv) ** 0.5
    print('    配对差(B-A) %+.2fpt  t=%.2f' % (dv.mean(), dv.mean()/se if se else 0))
    print()

# 持有天数分布
hold = []
for _, r in sel.iterrows():
    pass
print('参考: 封板票持有多一天的边际收益')
sub = d[d['seal1']]
print('  封板票 n=%d  A式(T+1出)均 %+.2f%%  B式(继续持)均 %+.2f%%' % (
    len(sub), sub['retA'].mean(), sub['retB'].mean()))
sub2 = d[~d['seal1']]
print('  未封板票 n=%d 两策略相同 均 %+.2f%%' % (len(sub2), sub2['retA'].mean()))
