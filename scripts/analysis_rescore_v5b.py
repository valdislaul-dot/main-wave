# -*- coding: utf-8 -*-
"""V5b 修正版:
  ① 归一化: 低基数特征(divergence/heavy_vol/板型)逐值映射; 连续特征分位映射
  ② 权重: 不做激进搜索 —— 以等权/温和权重为准(训练集搜索会过拟合)
"""
import json, os, sys, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
DAYSA = sorted(df['date'].unique())
df['buy_date'] = df['date'].map({d: DAYSA[i + 1] for i, d in enumerate(DAYSA) if i + 1 < len(DAYSA)})
df['divergence'] = ((df['vr20'] >= 2) & (df['open_num'] >= 1)).astype(float)
df['heavy_vol'] = (df['vr20'] >= 2).astype(float)
df['low_vol'] = (df['vr20'] < 0.5).astype(float)
df['cons_x'] = df['limit_days']
df['mktcap_x'] = df['mktcap']
df['ret5_x'] = df['ret5']
df['turnover_x'] = df['turnover']
df['seal_x'] = df['first_seal_min']
df['theme_x'] = df['theme_max']
df['btype_x'] = df['board_type'].map({'一字板': 3, 'T字板': 2, '换手板': 1})

SPLIT = '2026-04-01'
FACTORS = ['vr20', 'gap', 'cons_x', 'divergence', 'seal_x', 'theme_x',
           'mktcap_x', 'ret5_x', 'turnover_x', 'btype_x']
LOWCARD = {'divergence', 'btype_x'}

W = df[(df['gap'] >= 4) & (df['gap'] <= 8)].copy()
W['divergence'] = W['divergence'].fillna(0)
tr = W[W['date'] < SPLIT]
print('训练 %d (封板%.1f%%) | 验证 %d (封板%.1f%%)' % (
    len(tr), tr['seal_buy'].mean()*100,
    len(W[W['date'] >= SPLIT]), W[W['date'] >= SPLIT]['seal_buy'].mean()*100))

MAP = {}
NQ = 6
for f in FACTORS:
    s = tr[[f, 'seal_buy']].dropna()
    if len(s) < 200:
        continue
    if f in LOWCARD or s[f].nunique() <= 6:
        g = s.groupby(f)['seal_buy'].agg(['mean', 'size'])
        g = g[g['size'] >= 20]
        MAP[f] = ('vals', g.index.values.astype(float), g['mean'].values)
        print('%-12s 逐值: %s' % (f, ' '.join('%.0f→%.0f%%' % (v, r*100)
                                              for v, r in zip(g.index, g['mean']))))
    else:
        s = s.copy()
        s['q'] = pd.qcut(s[f], NQ, labels=False, duplicates='drop')
        g = s.groupby('q')['seal_buy'].mean()
        edges = s.groupby('q')[f].max().values
        MAP[f] = ('q', np.append(edges[:-1], -np.inf), g.values)
        print('%-12s 分位: %s' % (f, ' '.join('%.0f%%' % (r*100) for r in g.values)))


def nscore(f, vals):
    if f not in MAP:
        return pd.Series(50.0, index=vals.index)
    kind, edges, rates = MAP[f]
    base = rates.min()
    r = (rates - base) / (rates.max() - base) * 100 if rates.max() > base else rates * 0
    r = 40 + r * 0.6                      # 压缩到 40-100, 避免某个因子一票否决
    if kind == 'vals':
        m = {e: rr for e, rr in zip(edges, r)}
        out = vals.map(m)
    else:
        idx = np.clip(np.searchsorted(edges, vals.values, side='right'), 0, len(r) - 1)
        out = pd.Series(r[idx], index=vals.index)
    return pd.Series(np.where(pd.isna(vals.values), np.nan, out.values), index=vals.index)


N = pd.DataFrame({f: nscore(f, W[f]) for f in FACTORS}, index=W.index)
N['buy_date'] = W['buy_date'].values
N['date'] = W['date'].values
N['seal'] = W['seal_buy'].values
N['ret'] = W['ret_a'].values
N['is_tr'] = (W['date'] < SPLIT).values


def run(w, d, name):
    cols = FACTORS
    sc = (d[cols].fillna(d[cols].median()) * (np.array(w) / np.sum(w))).sum(axis=1)
    d = d.assign(_s=sc)
    pick = d.sort_values('_s').groupby('buy_date').tail(1)
    base = d.groupby('buy_date').agg(s=('seal', 'mean'), r=('ret', 'mean'))
    print('  %-16s 每日Top1 封板率%.1f%% 收益%+.2f%% 胜率%.0f%% (n=%d天) | 全池 %.1f%%/%+.2f%%' % (
        name, pick['seal'].mean()*100, pick['ret'].mean(), (pick['ret'] > 0).mean()*100,
        len(pick), base['s'].mean()*100, base['r'].mean()))
    return pick


print()
print('=' * 82)
print('【等权打分】')
print('=' * 82)
eq = np.ones(len(FACTORS))
for lab, d in (('训练', N[N['is_tr']]), ('验证', N[~N['is_tr']].dropna(subset=['ret']))):
    run(eq, d, '等权 ' + lab)

print()
print('=' * 82)
print('【几个温和权重方案 (不做激进搜索)】')
print('=' * 82)
SCHEMES = {
    'A方法论加权': {'vr20': 12, 'gap': 8, 'cons_x': 8, 'divergence': 15, 'seal_x': 10,
                    'theme_x': 12, 'mktcap_x': 7, 'ret5_x': 8, 'turnover_x': 8, 'btype_x': 12},
    'A方法论·重分歧': {'vr20': 12, 'gap': 8, 'cons_x': 8, 'divergence': 25, 'seal_x': 8,
                       'theme_x': 10, 'mktcap_x': 6, 'ret5_x': 6, 'turnover_x': 7, 'btype_x': 10},
    '分歧+爆量并列': {'vr20': 18, 'gap': 8, 'cons_x': 6, 'divergence': 18, 'seal_x': 10,
                      'theme_x': 12, 'mktcap_x': 6, 'ret5_x': 8, 'turnover_x': 6, 'btype_x': 8},
}
for nm, wd in SCHEMES.items():
    w = np.array([wd.get(f, 5) for f in FACTORS], dtype=float)
    for lab, d in (('训练', N[N['is_tr']]), ('验证', N[~N['is_tr']].dropna(subset=['ret']))):
        run(w, d, '%s %s' % (nm, lab))
    print('   权重: ' + ' '.join('%s=%d' % (f.replace('_x', ''), v) for f, v in zip(FACTORS, w)))
    print()

print('=' * 82)
print('【同期实盘对照 (A方法论加权)】')
print('=' * 82)
w = np.array([SCHEMES['A方法论加权'].get(f, 5) for f in FACTORS], dtype=float)
for lo, hi, lab in (('2026-08-10', '2026-08-25', 'V3时代'), ('2026-08-26', '2026-09-10', 'V4时代')):
    d = N[(N['buy_date'] >= lo) & (N['buy_date'] <= hi)].dropna(subset=['ret'])
    if len(d) < 10:
        continue
    run(w, d, lab)

print()
print('=' * 82)
print('【消融】A方法论加权方案逐项去掉')
print('=' * 82)
wd = SCHEMES['A方法论加权']
def run_drop(drop, lab):
    fs = [f for f in FACTORS if f in wd and f not in drop]
    w = np.array([wd[f] for f in fs], dtype=float)
    out = []
    for name, d in (('训练', N[N['is_tr']]), ('验证', N[~N['is_tr']].dropna(subset=['ret']))):
        sc = (d[fs].fillna(d[fs].median()) * (w / w.sum())).sum(axis=1)
        dd = d.assign(_ss=sc)
        pick = dd.sort_values('_ss').groupby('buy_date').tail(1)
        out.append('%s 封板%.1f%% 收益%+.2f%%' % (
            name, pick['seal'].mean()*100, pick['ret'].mean()))
    print('  %-20s %s' % (lab, ' | '.join(out)))
run_drop(set(), '完整')
run_drop({'divergence'}, '去掉 divergence')
run_drop({'vr20'}, '去掉 vr20')
run_drop({'divergence', 'vr20'}, '去掉 分歧+爆量')
run_drop({'btype_x'}, '去掉 板型')
run_drop({'seal_x'}, '去掉 首封时间')
run_drop({'theme_x'}, '去掉 板块')

print()
print('=' * 82)
print('【配对显著性】每日Top1 vs 当日全池 (A方法论加权)')
print('=' * 82)
import math
def paired(w, d, name):
    d = d.copy()
    sc = (d[FACTORS].fillna(d[FACTORS].median()) * (np.array(w) / np.sum(w))).sum(axis=1)
    d = d.assign(_s=sc)
    pick = d.sort_values('_s').groupby('buy_date').tail(1).set_index('buy_date')
    base = d.groupby('buy_date').agg(s=('seal', 'mean'), r=('ret', 'mean'))
    ds = (pick['seal'] - base['s']).dropna()
    dr = (pick['ret'] - base['r']).dropna()
    ms = ds.mean() * 100; ses = ds.std(ddof=1) / math.sqrt(len(ds)) * 100
    mr = dr.mean(); ser = dr.std(ddof=1) / math.sqrt(len(dr))
    print('  %s (n=%d天)' % (name, len(ds)))
    print('    封板率 %+.1fpt  SE %.1f  t=%.2f  %s' % (ms, ses, ms/ses if ses else 0,
          '显著' if abs(ms/ses) > 1.96 else '不显著'))
    print('    收益   %+.2fpt  SE %.2f  t=%.2f  %s' % (mr, ser, mr/ser if ser else 0,
          '显著' if abs(mr/ser) > 1.96 else '不显著'))
w2 = np.array([SCHEMES['A方法论加权'].get(f, 5) for f in FACTORS], dtype=float)
paired(w2, N[N['is_tr']], '训练 2025-06~2026-03')
paired(w2, N[~N['is_tr']].dropna(subset=['ret']), '验证 2026-04~09')
