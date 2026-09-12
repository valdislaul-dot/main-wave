# -*- coding: utf-8 -*-
"""证伪"是市场好"的解释: 高涨停日全池基率 vs 模型选中票 —— 同日对照
若高涨停日基率高而模型选中票仍差 → 选股逻辑问题, 非市场问题
"""
import json, os, sys, io, warnings, math
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
        pools[d] = {str(x.get('code', '')).zfill(6): x for x in rows if x.get('code')}
DAYS = sorted(pools)
NX = {d: DAYS[i + 1] for i, d in enumerate(DAYS) if i + 1 < len(DAYS)}

AUG = json.load(open('data/_regime_klines_aug.json', encoding='utf-8'))
_kl = {}


def kl(c):
    if c in _kl:
        return _kl[c]
    p = 'data/kline_data/' + c + '.json'
    rows = []
    if os.path.exists(p):
        raw = rd(p)
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
    _kl[c] = rows
    return rows


def kb(c, d):
    for b in kl(c):
        if str(b.get('date')) == d:
            return b
    for b in (AUG.get(c) or []):
        if b.get('date') == d:
            return b
    return None


# 模型选中票 (推荐回看)
rev = json.load(open('logs/recommendation_review.json', encoding='utf-8'))['reviews']
picks = {}
for d, r in rev.items():
    picks[d] = {str(s.get('code')).zfill(6): bool(s.get('T', {}).get('limit_up'))
                for s in r['stocks']}

rows = []
for T in DAYS:
    if not ('2026-07-24' <= T <= '2026-09-11'):
        continue
    T1 = NX.get(T)
    if not T1:
        continue
    zt_n = len(pools[T])          # 当日涨停数
    # 全池基率: T-1池 中 次日(T)封板的比例
    prev = [x for x in DAYS if x < T]
    if not prev:
        continue
    D = prev[-1]
    n_base = 0
    n_seal = 0
    for c in pools[D]:
        if kb(c, D) is None:
            continue
        n_base += 1
        if c in pools[T]:
            n_seal += 1
    base = n_seal / n_base * 100 if n_base else None
    # 模型选中票
    p = picks.get(T)
    if p:
        pk = sum(1 for v in p.values() if v) / len(p) * 100
    else:
        pk = None
    rows.append(dict(T=T, zt_n=zt_n, base=base, pick=pk, n_base=n_base))

df = pd.DataFrame(rows).dropna(subset=['base'])
df['diff'] = df['pick'] - df['base']
print('=' * 88)
print('【核心证伪】同日对照: 全池基率 vs 模型选中票封板率')
print('=' * 88)
print('%-12s %7s %10s %10s %9s' % ('买入日', '涨停数', '全池基率', '模型选中', '差值'))
for _, r in df.iterrows():
    pk = '%.0f%%' % r['pick'] if r['pick'] is not None else '—'
    dd = '%+.0fpt' % r['diff'] if r['pick'] is not None else '—'
    print('%-12s %7d %9.0f%% %10s %9s' % (r['T'], r['zt_n'], r['base'], pk, dd))

print()
print('=' * 88)
print('【按涨停数分层】')
print('=' * 88)
df['bucket'] = pd.cut(df['zt_n'], [0, 40, 60, 80, 999],
                      labels=['<40 极弱', '40-60', '60-80', '>=80 强势'])
for b, g in df.groupby('bucket', observed=True):
    gg = g.dropna(subset=['pick'])
    print('  %-10s n=%2d天 | 全池基率 %.1f%% | 模型选中 %.1f%% | 差值 %+.1fpt' % (
        b, len(g), g['base'].mean(),
        gg['pick'].mean() if len(gg) else float('nan'),
        gg['diff'].mean() if len(gg) else float('nan')))

hi = df[df['zt_n'] >= 60]
print()
print('高涨停日(%d天, 涨停数60+):' % len(hi))
print('  全池基率均值 %.1f%%   模型选中均值 %.1f%%' % (
    hi['base'].mean(), hi.dropna(subset=['pick'])['pick'].mean()))
d = hi.dropna(subset=['pick'])['diff']
se = d.std(ddof=1) / math.sqrt(len(d))
print('  同日差值 %+.1fpt  SE %.1f  t=%.2f  %s' % (
    d.mean(), se, d.mean() / se if se else 0,
    '显著' if abs(d.mean() / se) > 1.96 else '不显著'))

# 老版本时段(7月底~8月中)对照
old = df[(df['T'] >= '2026-07-24') & (df['T'] <= '2026-08-14')].dropna(subset=['pick'])
new = df[(df['T'] >= '2026-08-26')].dropna(subset=['pick'])
print()
print('【时段对照】')
for lab, g in (('7月底~8月中(老版本)', old), ('8-26起(V4)', new)):
    if len(g) < 3:
        continue
    dd = g['diff']
    se = dd.std(ddof=1) / math.sqrt(len(dd))
    print('  %-20s n=%2d天 | 全池基率 %.1f%% | 模型选中 %.1f%% | 差值 %+.1fpt (t=%.2f)' % (
        lab, len(g), g['base'].mean(), g['pick'].mean(), dd.mean(),
        dd.mean() / se if se else 0))
