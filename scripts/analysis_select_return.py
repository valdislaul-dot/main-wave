# -*- coding: utf-8 -*-
"""选股(收益口径): 哪些特征预测 A式收益 —— 这才是买入决策该优化的目标
训练 2025-06~2026-03 | 验证 2026-04~2026-09
"""
import json, os, sys, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
FEATS = ['turnover', 'open_num', 'suc_rate', 'mktcap', 'ord_amt', 'limit_days',
         'first_seal_min', 'last_seal_min', 'theme_max', 'vr20', 'prev_pct', 'amp',
         'is_yizi', 'pos20', 'ret5', 'ret10', 'ret20', 'zt_n', 'max_cons_day',
         'tp_seal_ratio', 'tp_opens', 'tp_first_pos', 'tp_final_sealed',
         'tp_close_pct', 'tp_min_after', 'tp_amp', 'tp_last30_min']
df['board_type_num'] = df['board_type'].map({'一字板': 3, 'T字板': 2, '换手板': 1})
FEATS.append('board_type_num')
SPLIT = '2026-04-01'
tr, te = df[df['date'] < SPLIT], df[df['date'] >= SPLIT]
dte = te.dropna(subset=['ret_a'])
dtr = tr.dropna(subset=['ret_a'])
print('验证集 %d 行 | A式收益 均值 %+.2f%% 中位 %+.2f%%\n' % (
    len(dte), dte['ret_a'].mean(), dte['ret_a'].median()))

print('=' * 82)
print('【单特征扫描】A式收益 (验证集十分位, 均值%)')
print('=' * 82)
res = []
for f in FEATS:
    d = dte[['ret_a', f]].dropna()
    if len(d) < 300:
        continue
    try:
        d = d.copy()
        d['b'] = pd.qcut(d[f], 10, labels=False, duplicates='drop')
    except Exception:
        continue
    g = d.groupby('b')['ret_a'].mean()
    if len(g) < 5:
        continue
    res.append((g.max() - g.min(), f, g.values, len(d)))
for spread, f, g, n in sorted(res, reverse=True)[:14]:
    print('%-16s 极差%6.2fpt  %s (n=%d)' % (f, spread, ' '.join('%+4.1f' % x for x in g), n))

print()
print('=' * 82)
print('【模型】直接预测 A式收益 (验证集十分位)')
print('=' * 82)
reg = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_depth=4,
                                    l2_regularization=1.0, random_state=42)
reg.fit(dtr[FEATS].astype(float), np.clip(dtr['ret_a'], -30, 30))
tt = dte.copy()
tt['p'] = reg.predict(dte[FEATS].astype(float))
tt['b'] = pd.qcut(tt['p'], 10, labels=False, duplicates='drop')
g = tt.groupby('b').agg(p=('p', 'mean'), ret=('ret_a', 'mean'),
                        win=('ret_a', lambda s: (s > 0).mean()*100),
                        seal=('seal', 'mean'), gap=('gap', 'mean'), n=('ret_a', 'size'))
print(' %3s %8s %9s %7s %8s %8s %6s' % ('档', '预测', '实际收益', '胜率', '封板率', '买入gap', 'n'))
for b, r in g.iterrows():
    print(' %3d %+8.2f %+8.2f%% %6.0f%% %7.0f%% %+7.2f%% %6d' % (
        b + 1, r['p'], r['ret'], r['win'], r['seal']*100, r['gap'], r['n']))

print()
print('=' * 82)
print('【特征重要度】验证集置换 (对收益预测R²的影响)')
print('=' * 82)
from sklearn.metrics import r2_score
base = r2_score(dte['ret_a'], tt['p'])
rng = np.random.default_rng(0)
imp = []
Xte = dte[FEATS].astype(float)
for f in FEATS:
    Xp = Xte.copy()
    Xp[f] = rng.permutation(Xp[f].values)
    imp.append((base - r2_score(dte['ret_a'], reg.predict(Xp)), f))
for v, f in sorted(imp, reverse=True)[:14]:
    print('  %-16s %+.4f' % (f, v))

print()
print('=' * 82)
print('【组合: 模型分 × 现有gap窗 4-8%】')
print('=' * 82)
sub = tt[(tt['gap'] >= 4) & (tt['gap'] <= 8)].copy()
if len(sub) > 100:
    sub['q'] = pd.qcut(sub['p'], 4, labels=False, duplicates='drop')
    gg = sub.groupby('q').agg(p=('p', 'mean'), ret=('ret_a', 'mean'),
                              win=('ret_a', lambda s: (s > 0).mean()*100),
                              seal=('seal', 'mean'), n=('ret_a', 'size'))
    print('  gap4-8% 内按模型分四档:')
    for q, r in gg.iterrows():
        print('    第%d档 预测%+.2f 实际%+.2f%% 胜率%.0f%% 封板率%.0f%% n=%d' % (
            q + 1, r['p'], r['ret'], r['win'], r['seal']*100, r['n']))
    print('  未筛选 gap4-8% 全体: 实际%+.2f%% 胜率%.0f%% n=%d' % (
        sub['ret_a'].mean(), (sub['ret_a'] > 0).mean()*100, len(sub)))
