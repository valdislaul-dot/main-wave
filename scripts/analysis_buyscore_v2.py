# -*- coding: utf-8 -*-
"""买入打分 v2: 在 gap4-8% 窗口内重新选特征(条件AUC), 恢复分歧质量
对比 v1(全样本AUC选的8特征) vs v2(窗口内条件AUC选的)
"""
import json, os, sys, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sklearn.metrics import roc_auc_score

df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
DAYSA = sorted(df['date'].unique())
df['buy_date'] = df['date'].map({d: DAYSA[i + 1] for i, d in enumerate(DAYSA) if i + 1 < len(DAYSA)})
df['vol_per_amt'] = df['ord_amt'] / (df['mktcap'] * 1e8 / 100)
df['heavy_vol'] = (df['vr20'] >= 2).astype(float)
df['rotten'] = (df['open_num'] >= 1).astype(float)
df['divergence'] = ((df['heavy_vol'] == 1) & (df['rotten'] == 1)).astype(float)
df['prev_heavy'] = (df['prev_pct'] >= 5).astype(float)

SPLIT = '2026-04-01'
SIGN_V1 = {'tp_seal_ratio': +1, 'first_seal_min': -1, 'last_seal_min': -1,
           'tp_first_pos': -1, 'amp': -1, 'ret5': +1, 'prev_pct': +1, 'ord_amt': +1}
SIGN_V2 = {'prev_pct': +1, 'heavy_vol': +1, 'divergence': +1, 'vol_per_amt': +1,
           'tp_seal_ratio': +1, 'limit_days': +1, 'first_seal_min': -1, 'ret5': +1}

window = df[(df['gap'] >= 4) & (df['gap'] <= 8)]
tr_w = window[window['date'] < SPLIT]


def build(d, SIGN):
    s = pd.Series(0.0, index=d.index)
    c = pd.Series(0.0, index=d.index)
    for f, sg in SIGN.items():
        base = tr_w[f].dropna()
        if len(base) < 300:
            continue
        cuts = base.quantile(np.linspace(0, 1, 21)).values
        r = np.clip(np.searchsorted(cuts, d[f].values, side='right') / 20.0, 0, 1)
        r = np.where(pd.isna(d[f].values), np.nan, r)
        s = s + pd.Series(np.where(np.isnan(r), 0, (r if sg > 0 else 1 - r)), index=d.index)
        c = c + pd.Series(np.where(np.isnan(r), 0, 1), index=d.index)
    return s / c.replace(0, np.nan)


for nm, SIGN in (('v1', SIGN_V1), ('v2', SIGN_V2)):
    df['sc_' + nm] = np.nan
    for mask in (df['date'] < SPLIT, df['date'] >= SPLIT):
        idx = df.index[mask]
        df.loc[idx, 'sc_' + nm] = build(df.loc[idx], SIGN)

sub = df[(df['gap'] >= 4) & (df['gap'] <= 8)].dropna(subset=['ret_a']).copy()
print('gap4-8%% n=%d\n' % len(sub))
for nm in ('v1', 'v2'):
    print('=' * 74)
    print('【打分 %s】' % nm)
    for lab, d in (('训练', sub[sub['date'] < SPLIT]), ('验证', sub[sub['date'] >= SPLIT])):
        d = d.dropna(subset=['sc_' + nm])
        if len(d) < 60:
            continue
        pick = d.sort_values('sc_' + nm).groupby('buy_date').tail(1)
        base = d.groupby('buy_date').agg(s=('seal_buy', 'mean'), r=('ret_a', 'mean'))
        print('  %s: n=%d天 每日Top1 封板率%.1f%% 收益%+.2f%% 胜率%.0f%% | 同日全池 封板%.1f%% 收益%+.2f%%' % (
            lab, len(pick), pick['seal_buy'].mean()*100, pick['ret_a'].mean(),
            (pick['ret_a'] > 0).mean()*100, base['s'].mean()*100, base['r'].mean()))
        top = d.nlargest(max(20, int(len(d)*0.2)), 'sc_' + nm)
        print('     Top20%%: 封板率%.1f%% 收益%+.2f%%' % (
            top['seal_buy'].mean()*100, top['ret_a'].mean()))
    print()

print('=' * 74)
print('【同期实盘对照 (08-10~09-10)】')
for lo, hi, lab in (('2026-08-10', '2026-08-25', 'V3时代'), ('2026-08-26', '2026-09-10', 'V4时代')):
    d = sub[(sub['buy_date'] >= lo) & (sub['buy_date'] <= hi)]
    if len(d) < 10:
        continue
    print('  [%s] 全池: 封板率%.1f%% 收益%+.2f%%' % (
        lab, d['seal_buy'].mean()*100, d['ret_a'].mean()))
    for nm in ('v1', 'v2'):
        pick = d.dropna(subset=['sc_' + nm]).sort_values('sc_' + nm).groupby('buy_date').tail(1)
        print('     %s 每日Top1: 封板率%.1f%% 收益%+.2f%%' % (
            nm, pick['seal_buy'].mean()*100, pick['ret_a'].mean()))
