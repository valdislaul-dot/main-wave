# -*- coding: utf-8 -*-
"""严格特征排序: 单特征AUC(封板) 训练+验证双算 + 增量AUC(在gap之上)
再测"分歧质量"(爆量+烂板回封) 是否被误删
"""
import json, os, sys, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sklearn.metrics import roc_auc_score

df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
SPLIT = '2026-04-01'

# 补充派生特征
df['seal_span'] = df['last_seal_min'] - df['first_seal_min']
df['vol_per_amt'] = df['ord_amt'] / (df['mktcap'] * 1e8 / 100)       # 封单额/流通市值%
df['gap_x_vr'] = df['vr20'] / (df['gap'].abs() + 1)
df['is_strong_seal'] = ((df['first_seal_min'] <= 30) & (df['open_num'] == 0)).astype(float)
df['late_seal'] = (df['first_seal_min'] >= 14 * 60).astype(float)
df['big_amp'] = (df['amp'] >= 10).astype(float)
df['heavy_vol'] = (df['vr20'] >= 2).astype(float)
df['rotten'] = (df['open_num'] >= 1).astype(float)
df['divergence'] = ((df['heavy_vol'] == 1) & (df['rotten'] == 1)).astype(float)
df['div_strong'] = ((df['vr20'] >= 2) & (df['open_num'] >= 1) & (df['amp'] >= 10)).astype(float)
df['prev_heavy'] = (df['prev_pct'] >= 5).astype(float)
df['theme_strong'] = (df['theme_max'] >= 3).astype(float)
df['small_cap'] = (df['mktcap'] <= 50).astype(float)

CAND = ['turnover', 'open_num', 'suc_rate', 'mktcap', 'ord_amt', 'limit_days',
        'first_seal_min', 'last_seal_min', 'theme_max', 'vr20', 'prev_pct', 'amp',
        'is_yizi', 'pos20', 'ret5', 'ret10', 'ret20', 'zt_n', 'max_cons_day',
        'tp_seal_ratio', 'tp_opens', 'tp_first_pos', 'tp_final_sealed',
        'tp_close_pct', 'tp_min_after', 'tp_amp', 'tp_last30_min', 'board_type_num',
        'seal_span', 'vol_per_amt', 'gap_x_vr', 'is_strong_seal', 'late_seal',
        'big_amp', 'heavy_vol', 'rotten', 'divergence', 'div_strong',
        'prev_heavy', 'theme_strong', 'small_cap']
CAND = [c for c in CAND if c in df.columns]

tr, te = df[df['date'] < SPLIT], df[df['date'] >= SPLIT]
print('=== 单特征AUC 预测D+1封板 (0.5=无区分; 方向已取绝对值, 附方向) ===')
rows = []
for f in CAND:
    a = tr[[f, 'seal']].dropna()
    b = te[[f, 'seal']].dropna()
    if len(a) < 500 or len(b) < 300:
        continue
    au = roc_auc_score(a['seal'], a[f])
    bu = roc_auc_score(b['seal'], b[f])
    d = 1 if au >= 0.5 else -1
    rows.append((max(bu, 1 - bu), f, au, bu, d, len(b)))
print('%-18s %10s %10s %8s %7s' % ('特征', '训练AUC', '验证AUC', '验证|AUC|', '方向'))
for ab, f, au, bu, d, n in sorted(rows, reverse=True):
    print('%-18s %10.4f %10.4f %8.4f %7s' % (f, au, bu, ab, '+' if d > 0 else '-'))

print()
print('=== 增量: 在 gap 之上的AUC提升 (验证集) ===')
te3 = te.dropna(subset=['gap'])
base = roc_auc_score(te3['seal'], te3['gap'])
print('gap 单变量 AUC = %.4f' % base)
inc = []
te2 = te3.copy()
for f in CAND:
    b = te2[[f, 'seal', 'gap']].dropna()
    if len(b) < 300:
        continue
    # 简单组合: 用gap的分位 + 特征的分位做 logistic 近似, 这里用秩和
    r1 = b['gap'].rank(pct=True)
    r2 = b[f].rank(pct=True) if roc_auc_score(b['seal'], b[f]) >= 0.5 else 1 - b[f].rank(pct=True)
    for w in (0.2, 0.35):
        comb = (1 - w) * r1 + w * r2
        inc.append((roc_auc_score(b['seal'], comb) - roc_auc_score(b['seal'], r1), f, w, len(b)))
seen = {}
for v, f, w, n in inc:
    seen[f] = max(seen.get(f, -9), v)
for f, v in sorted(seen.items(), key=lambda kv: -kv[1])[:15]:
    print('  %-18s 增量 %+.4f' % (f, v))

print()
print('=== 分歧质量检验 (V4把它权重设为0) ===')
for lab, sel in (('全样本', df),
                 ('gap4-8%', df[(df['gap'] >= 4) & (df['gap'] <= 8)])):
    print('  [%s]' % lab)
    for f in ('divergence', 'div_strong', 'heavy_vol', 'rotten', 'big_amp', 'is_strong_seal'):
        g = sel.groupby(f).agg(n=('seal', 'size'), seal=('seal', 'mean'),
                               ret=('ret_a', 'mean'))
        if len(g) < 2:
            continue
        r0, r1 = g.loc[0], g.loc[1]
        print('    %-14s =0: n=%5d 封板%4.1f%% 收益%+5.2f%% | =1: n=%5d 封板%4.1f%% 收益%+5.2f%% | 差%+5.1fpt' % (
            f, r0['n'], r0['seal']*100, r0['ret'], r1['n'], r1['seal']*100, r1['ret'],
            (r1['seal']-r0['seal'])*100))
    print()

print('=== 分歧组内细分: 分歧后修复能不能识别 ===')
d = df[(df['gap'] >= 4) & (df['gap'] <= 8) & (df['divergence'] == 1)].copy()
print('  gap4-8 窗口内 且 分歧(爆量vr>=2 & 炸板): n={} 封板率{:.1f}% 收益{:+.2f}%'.format(
    len(d), d['seal_buy'].mean()*100, d['ret_a'].mean()))
for f in ('tp_seal_ratio', 'amp', 'ord_amt', 'first_seal_min', 'limit_days', 'mktcap'):
    x = d[[f, 'seal_buy', 'ret_a']].dropna()
    if len(x) < 60:
        continue
    x = x.copy()
    x['q'] = pd.qcut(x[f], 4, labels=False, duplicates='drop')
    g = x.groupby('q').agg(seal=('seal_buy', 'mean'), ret=('ret_a', 'mean'), n=('seal_buy', 'size'))
    print('    %-14s %s' % (f, ' | '.join('封%.0f%% 收%+.1f%% n=%d' % (
        r['seal']*100, r['ret'], r['n']) for _, r in g.iterrows())))


print()
print('=== gap4-8% 窗口内的条件AUC (才是我方实际决策环境) ===')
g = df[(df['gap'] >= 4) & (df['gap'] <= 8) & df['seal_buy'].notna()]
print('  样本 n=%d 封板率 %.1f%%' % (len(g), g['seal_buy'].mean()*100))
res = []
for f in CAND:
    x = g[[f, 'seal_buy']].dropna()
    if len(x) < 150:
        continue
    au = roc_auc_score(x['seal_buy'], x[f])
    res.append((max(au, 1-au), f, au, 1 if au >= 0.5 else -1, len(x)))
for ab, f, au, d_, n in sorted(res, reverse=True)[:16]:
    print('  %-18s AUC %.4f  方向%s  n=%d' % (f, au, '+' if d_ > 0 else '-', n))

print()
print('=== 分歧组内细分 (gap4-8%% 且 分歧) ===')
for f in ('tp_seal_ratio', 'amp', 'ord_amt', 'vol_per_amt', 'first_seal_min',
          'limit_days', 'mktcap', 'ret5', 'prev_pct', 'turnover'):
    x = d[[f, 'seal_buy', 'ret_a']].dropna()
    if len(x) < 80:
        continue
    x = x.copy()
    x['q'] = pd.qcut(x[f], 4, labels=False, duplicates='drop')
    gg = x.groupby('q').agg(seal=('seal_buy', 'mean'), ret=('ret_a', 'mean'), n=('seal_buy', 'size'))
    print('  %-14s %s' % (f, ' | '.join('封%.0f%% 收%+.1f%%' % (r['seal']*100, r['ret']) for _, r in gg.iterrows())))
