# -*- coding: utf-8 -*-
"""选股模型终测: 预测D+1封板 -> 看实际可执行收益(T+1口径)
对比 gap-only vs 全特征, 并在 gap4-8% 窗内做最终检验
"""
import json, os, sys, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
FEATS = ['turnover', 'open_num', 'suc_rate', 'mktcap', 'ord_amt', 'limit_days',
         'first_seal_min', 'last_seal_min', 'theme_max', 'vr20', 'prev_pct', 'amp',
         'is_yizi', 'pos20', 'ret5', 'ret10', 'ret20', 'zt_n', 'max_cons_day',
         'tp_seal_ratio', 'tp_opens', 'tp_first_pos', 'tp_final_sealed',
         'tp_close_pct', 'tp_min_after', 'tp_amp', 'tp_last30_min']
df['board_type_num'] = df['board_type'].map({'一字板': 3, 'T字板': 2, '换手板': 1})
FEATS.append('board_type_num')
df = df.dropna(subset=['gap'])
SPLIT = '2026-04-01'
tr, te = df[df['date'] < SPLIT], df[df['date'] >= SPLIT]
Xtr, Xte = tr[FEATS].astype(float), te[FEATS].astype(float)
print('训练 %d | 验证 %d\n' % (len(tr), len(te)))

models = {
    'gap only': (tr[['gap']], te[['gap']]),
    '全特征': (Xtr, Xte),
    '全特征+gap': (Xtr.assign(gap=tr['gap']), Xte.assign(gap=te['gap'])),
}
scores = {}
for name, (a, b) in models.items():
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_depth=4,
                                       l2_regularization=1.0, random_state=42).fit(a, tr['seal'])
    p = m.predict_proba(b)[:, 1]
    scores[name] = p
    print('%-12s 验证AUC(预测封板) = %.4f' % (name, roc_auc_score(te['seal'], p)))

te = te.copy()
for k, v in scores.items():
    te['p_' + k] = v

sub = te[(te['gap'] >= 4) & (te['gap'] <= 8)].dropna(subset=['ret_a']).copy()
print('\n' + '=' * 78)
print('【最终检验】gap4-8%% 窗口内按模型分五档 (n=%d, 全体收益 %+.2f%%)' % (
    len(sub), sub['ret_a'].mean()))
print('=' * 78)
for name in models:
    sub['q'] = pd.qcut(sub['p_' + name], 5, labels=False, duplicates='drop')
    g = sub.groupby('q').agg(p=('p_' + name, 'mean'), seal=('seal', 'mean'),
                             ret=('ret_a', 'mean'),
                             win=('ret_a', lambda s: (s > 0).mean()*100), n=('seal', 'size'))
    line = ' | '.join('%+.2f%%(封%.0f%%)' % (r['ret'], r['seal']*100) for _, r in g.iterrows())
    print('%-12s %s' % (name, line))
    print('%-12s 五档n=%s' % ('', '/'.join(str(int(r['n'])) for _, r in g.iterrows())))

print('\n【全样本(不限gap)按模型分十档】')
for name in models:
    te['q'] = pd.qcut(te['p_' + name], 10, labels=False, duplicates='drop')
    g = te.groupby('q').agg(ret=('ret_a', 'mean'), seal=('seal', 'mean'), gap=('gap', 'mean'))
    print('%-12s %s' % (name, ' '.join('%+.1f' % r['ret'] for _, r in g.iterrows())))
    print('%-12s %s' % (' 封板率', ' '.join('%.0f%%' % (r['seal']*100) for _, r in g.iterrows())))

print('\n【只看有ret_a的样本(AUC会在有收益样本上重算)】')
d2 = te.dropna(subset=['ret_a'])
for name in models:
    print('  %-12s AUC=%.4f  top20%%收益 %+.2f%%  全体 %+.2f%%' % (
        name, roc_auc_score(d2['seal'], d2['p_' + name]),
        d2.nlargest(int(len(d2) * 0.2), 'p_' + name)['ret_a'].mean(),
        d2['ret_a'].mean()))
