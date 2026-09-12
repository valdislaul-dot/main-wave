# -*- coding: utf-8 -*-
"""决定性检验: 剔除 gap 之后, 池内特征还有没有选股alpha?
方法: ① 只用gap预测封板(基准) ② 全特征预测封板 → 残差 = 全特征分 - gap基准分
      残差高的票 = "比它的gap所隐含的更可能封板" = 真alpha候选
      再看这些票的实际封板率与收益
"""
import json, os, sys, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score

df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
FEATS = ['turnover', 'open_num', 'suc_rate', 'mktcap', 'ord_amt', 'limit_days',
         'first_seal_min', 'last_seal_min', 'theme_max', 'vr20', 'prev_pct', 'amp',
         'is_yizi', 'pos20', 'ret5', 'ret10', 'ret20', 'zt_n', 'max_cons_day',
         'tp_seal_ratio', 'tp_opens', 'tp_first_pos', 'tp_final_sealed',
         'tp_close_pct', 'tp_min_after', 'tp_amp', 'tp_last30_min']
df['board_type_num'] = df['board_type'].map({'一字板': 3, 'T字板': 2, '换手板': 1})
FEATS.append('board_type_num')

df = df.dropna(subset=['gap', 'seal'])
SPLIT = '2026-04-01'
tr, te = df[df['date'] < SPLIT], df[df['date'] >= SPLIT]
print('训练 %d | 验证 %d (封板率 %.1f%%)\n' % (len(tr), len(te), te['seal'].mean()*100))

# ① gap 基准
g_tr = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, max_depth=3,
                                      random_state=1).fit(tr[['gap']], tr['seal'])
g_te = g_tr.predict_proba(te[['gap']])[:, 1]
print('① 只用gap预测封板: AUC = %.4f' % roc_auc_score(te['seal'], g_te))

# ② 全特征
f_tr = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_depth=4,
                                      l2_regularization=1.0, random_state=42
                                      ).fit(tr[FEATS].astype(float), tr['seal'])
f_te = f_tr.predict_proba(te[FEATS].astype(float))[:, 1]
print('② 全特征预测封板:   AUC = %.4f' % roc_auc_score(te['seal'], f_te))

# ③ 残差
tt = te.copy()
tt['p_gap'] = g_te
tt['p_all'] = f_te
tt['resid'] = tt['p_all'] - tt['p_gap']
print('   gap基率AUC 0.5基准外, 全特征增量: %+.4f\n' % (
    roc_auc_score(te['seal'], f_te) - roc_auc_score(te['seal'], g_te)))

print('=' * 80)
print('【残差分组】全部样本: 残差高的票 (比gap隐含更能封板)')
print('=' * 80)
tt['q'] = pd.qcut(tt['resid'], 5, labels=False, duplicates='drop')
g = tt.groupby('q').agg(resid=('resid', 'mean'), p_all=('p_all', 'mean'),
                        p_gap=('p_gap', 'mean'), seal=('seal', 'mean'),
                        ret=('ret_a', 'mean'), gap=('gap', 'mean'), n=('seal', 'size'))
print(' %3s %9s %8s %8s %9s %9s %9s %7s' % (
    '档', '残差', '全特征分', 'gap分', '实际封板', 'A式收益', '买入gap', 'n'))
for q, r in g.iterrows():
    print(' %3d %+9.3f %8.3f %8.3f %8.1f%% %+8.2f%% %+8.2f%% %7d' % (
        q + 1, r['resid'], r['p_all'], r['p_gap'], r['seal']*100, r['ret'], r['gap'], r['n']))

print()
print('=' * 80)
print('【同上, 但限定 gap 4-8% (我们实际的买入窗)】')
print('=' * 80)
sub = tt[(tt['gap'] >= 4) & (tt['gap'] <= 8)].copy()
print('  样本 %d, 全体A式收益 %+.2f%% 封板率 %.1f%%' % (
    len(sub), sub['ret_a'].mean(), sub['seal'].mean()*100))
sub['q'] = pd.qcut(sub['p_all'], 5, labels=False, duplicates='drop')
g2 = sub.groupby('q').agg(p=('p_all', 'mean'), seal=('seal', 'mean'),
                          ret=('ret_a', 'mean'),
                          win=('ret_a', lambda s: (s > 0).mean()*100), n=('seal', 'size'))
for q, r in g2.iterrows():
    print('    全特征分第%d档 预测%.3f 封板率%.0f%% 收益%+.2f%% 胜率%.0f%% n=%d' % (
        q + 1, r['p'], r['seal']*100, r['ret'], r['win'], r['n']))
sub['q2'] = pd.qcut(sub['resid'], 5, labels=False, duplicates='drop')
g3 = sub.groupby('q2').agg(r_=('resid', 'mean'), seal=('seal', 'mean'),
                           ret=('ret_a', 'mean'),
                           win=('ret_a', lambda s: (s > 0).mean()*100), n=('seal', 'size'))
print('  --- 按残差分组 ---')
for q, r in g3.iterrows():
    print('    残差第%d档 %+.3f 封板率%.0f%% 收益%+.2f%% 胜率%.0f%% n=%d' % (
        q + 1, r['r_'], r['seal']*100, r['ret'], r['win'], r['n']))

print()
print('=' * 80)
print('【直接回归收益: 残差口径】')
print('=' * 80)
dtr = tr.dropna(subset=['ret_a']); dte = te.dropna(subset=['ret_a'])
r_gap = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, max_depth=3,
                                      random_state=1).fit(dtr[['gap']], np.clip(dtr['ret_a'], -30, 30))
r_all = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, max_depth=4,
                                      l2_regularization=1.0, random_state=42
                                      ).fit(dtr[FEATS].astype(float), np.clip(dtr['ret_a'], -30, 30))
from sklearn.metrics import r2_score
print('  R²  只用gap %.4f | 全特征 %.4f' % (
    r2_score(dte['ret_a'], r_gap.predict(dte[['gap']])),
    r2_score(dte['ret_a'], r_all.predict(dte[FEATS].astype(float)))))
