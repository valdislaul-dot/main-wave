# -*- coding: utf-8 -*-
"""选股模型: 哪些特征能预测 D+1 封板 / A式收益
训练 2025-06~2026-03 | 验证 2026-04~2026-09 (时间外推, 不随机切分)
"""
import json, os, sys, io
import numpy as np
import pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score

df = pd.read_csv('data/_select_dataset.csv')
FEATS = ['turnover', 'open_num', 'suc_rate', 'mktcap', 'ord_amt', 'limit_days',
         'first_seal_min', 'last_seal_min', 'theme_max', 'vr20', 'prev_pct', 'amp',
         'is_yizi', 'pos20', 'ret5', 'ret10', 'ret20', 'zt_n', 'max_cons_day',
         'tp_seal_ratio', 'tp_opens', 'tp_first_pos', 'tp_final_sealed',
         'tp_close_pct', 'tp_min_after', 'tp_amp', 'tp_last30_min']
df['board_type_num'] = df['board_type'].map({'一字板': 3, 'T字板': 2, '换手板': 1})
FEATS.append('board_type_num')

SPLIT = '2026-04-01'
tr = df[df['date'] < SPLIT]
te = df[df['date'] >= SPLIT]
print('训练 %d 行 (%s~%s) | 验证 %d 行 (%s~%s)' % (
    len(tr), tr['date'].min(), tr['date'].max(), len(te), te['date'].min(), te['date'].max()))
print('训练封板率 %.1f%% | 验证封板率 %.1f%%\n' % (tr['seal'].mean()*100, te['seal'].mean()*100))

print('=' * 78)
print('【单特征扫描】封板率 (验证集, 十分位)')
print('=' * 78)
print('%-16s %8s  %s' % ('特征', '极差', '十分位封板率(低->高)'))
res = []
for f in FEATS:
    d = te[['seal', f]].dropna()
    if len(d) < 300:
        continue
    try:
        d['b'] = pd.qcut(d[f], 10, labels=False, duplicates='drop')
    except Exception:
        continue
    g = d.groupby('b')['seal'].mean() * 100
    if len(g) < 5:
        continue
    spread = g.max() - g.min()
    res.append((spread, f, g.values, len(d)))
for spread, f, g, n in sorted(res, reverse=True):
    bar = ' '.join('%2.0f' % x for x in g)
    print('%-16s %7.1fpt  %s (n=%d)' % (f, spread, bar, n))

print()
print('=' * 78)
print('【模型】预测 D+1 封板 (HistGradientBoosting, 时间外推)')
print('=' * 78)
Xtr, ytr = tr[FEATS].astype(float), tr['seal']
Xte, yte = te[FEATS].astype(float), te['seal']
clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                     max_depth=4, l2_regularization=1.0,
                                     random_state=42)
clf.fit(Xtr, ytr)
p_tr = clf.predict_proba(Xtr)[:, 1]
p_te = clf.predict_proba(Xte)[:, 1]
print('  AUC 训练 %.4f | 验证 %.4f  (基准=随机0.5)' % (
    roc_auc_score(ytr, p_tr), roc_auc_score(yte, p_te)))

# 按预测分位看实际封板率
tt = te.copy()
tt['p'] = p_te
tt['b'] = pd.qcut(tt['p'], 10, labels=False, duplicates='drop')
g = tt.groupby('b').agg(p=('p', 'mean'), seal=('seal', 'mean'), ret=('ret_a', 'mean'), n=('seal', 'size'))
print('\n  验证集按模型分十分位:')
print('  %4s %8s %9s %9s %7s' % ('档', '预测分', '实际封板率', 'A式收益', 'n'))
for b, r in g.iterrows():
    print('  %4d %8.3f %8.1f%% %+8.2f%% %7d' % (b + 1, r['p'], r['seal']*100, r['ret'], r['n']))

print()
print('=' * 78)
print('【模型】直接预测 A式收益 (回归)')
print('=' * 78)
dtr = tr.dropna(subset=['ret_a'])
dte = te.dropna(subset=['ret_a'])
reg = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, max_depth=4,
                                    l2_regularization=1.0, random_state=42)
reg.fit(dtr[FEATS].astype(float), np.clip(dtr['ret_a'], -30, 30))
r_te = reg.predict(dte[FEATS].astype(float))
tt2 = dte.copy()
tt2['p'] = r_te
tt2['b'] = pd.qcut(tt2['p'], 10, labels=False, duplicates='drop')
g2 = tt2.groupby('b').agg(p=('p', 'mean'), ret=('ret_a', 'mean'),
                          win=('ret_a', lambda s: (s > 0).mean()*100), n=('ret_a', 'size'))
print('  %4s %9s %10s %8s %7s' % ('档', '预测', '实际A式收益', '胜率', 'n'))
for b, r in g2.iterrows():
    print('  %4d %+9.2f %+9.2f%% %7.0f%% %7d' % (b + 1, r['p'], r['ret'], r['win'], r['n']))

# 特征重要性 (置换)
print()
print('=' * 78)
print('【特征重要性】验证集置换重要度 (对封板AUC的影响)')
print('=' * 78)
base = roc_auc_score(yte, p_te)
rng = np.random.default_rng(0)
imp = []
for f in FEATS:
    Xp = Xte.copy()
    Xp[f] = rng.permutation(Xp[f].values)
    imp.append((base - roc_auc_score(yte, clf.predict_proba(Xp)[:, 1]), f))
for v, f in sorted(imp, reverse=True)[:15]:
    print('  %-16s %+.4f' % (f, v))
