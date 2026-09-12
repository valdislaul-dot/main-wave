# -*- coding: utf-8 -*-
"""检验 vol_per_amt(封单额/流通市值) 是不是真的有用 —— 消融 + 对照 + 分年稳定性
对照物: ord_amt(封单额原值) / mktcap(流通市值) / seal_fund(新池字段)
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
df['vpa'] = df['ord_amt'] / (df['mktcap'] * 1e8 / 100)     # 封单额/流通市值 %
df['vpa_log'] = np.log1p(df['vpa'].clip(lower=0))
df['amt_log'] = np.log1p(df['ord_amt'].clip(lower=0))
df['cap_log'] = np.log1p(df['mktcap'].clip(lower=0))
SPLIT = '2026-04-01'

W = df[(df['gap'] >= 4) & (df['gap'] <= 8)]
print('gap4-8%% 窗口 n=%d 封板率%.1f%%' % (len(W), W['seal_buy'].mean()*100))
print('vpa 有效率 %.1f%% (缺%d)' % (W['vpa'].notna().mean()*100, W['vpa'].isna().sum()))
print()

print('=== 三兄弟对比: 窗口内 AUC ===')
for f, lab in (('vpa_log', '封单额/流通市值(log)'), ('vpa', '封单额/流通市值(原值)'),
               ('amt_log', '封单额(log)'), ('ord_amt', '封单额(原值)'),
               ('cap_log', '流通市值(log)'), ('mktcap', '流通市值(原值)')):
    tr = W[(W['date'] < SPLIT)][[f, 'seal_buy']].dropna()
    te = W[(W['date'] >= SPLIT)][[f, 'seal_buy']].dropna()
    if len(tr) < 200 or len(te) < 150:
        continue
    a, b = roc_auc_score(tr['seal_buy'], tr[f]), roc_auc_score(te['seal_buy'], te[f])
    print('  %-24s 训练%.4f 验证%.4f |  验证|AUC| %.4f' % (lab, a, b, max(b, 1-b)))

print()
print('=== 分年稳定性 (窗口内, |AUC|) ===')
for f, lab in (('vpa', 'vpa'), ('ord_amt', '封单额'), ('mktcap', '流通市值')):
    xs = []
    for lo, hi in (('2025-06-01', '2025-09-30'), ('2025-10-01', '2026-01-31'),
                   ('2026-02-01', '2026-05-31'), ('2026-06-01', '2026-09-11')):
        s = W[(W['date'] >= lo) & (W['date'] <= hi)][[f, 'seal_buy']].dropna()
        if len(s) < 100:
            xs.append('%s: 少' % lo[:7]); continue
        a = roc_auc_score(s['seal_buy'], s[f])
        xs.append('%s:%.3f' % (lo[:7], max(a, 1-a)))
    print('  %-10s %s' % (lab, '  '.join(xs)))

print()
print('=== vpa 五分位 (窗口内) ===')
x = W[['vpa', 'seal_buy', 'ret_a', 'gap']].dropna()
x = x.copy()
x['q'] = pd.qcut(x['vpa'], 5, labels=False, duplicates='drop')
g = x.groupby('q').agg(vpa=('vpa', 'mean'), seal=('seal_buy', 'mean'),
                       ret=('ret_a', 'mean'),
                       win=('ret_a', lambda s: (s > 0).mean()*100), n=('vpa', 'size'))
for q, r in g.iterrows():
    print('  第%d档 vpa=%.3f%% 封板率%4.1f%% 收益%+6.2f%% 胜率%3.0f%% n=%d' % (
        q + 1, r['vpa'], r['seal']*100, r['ret'], r['win'], r['n']))

print()
print('=== 消融: v2打分 去掉 vpa 后还剩多少 ===')
SIGN = {'prev_pct': +1, 'heavy_vol': +1, 'divergence': +1, 'vpa': +1,
        'tp_seal_ratio': +1, 'limit_days': +1, 'first_seal_min': -1, 'ret5': +1}
df['heavy_vol'] = (df['vr20'] >= 2).astype(float)
df['divergence'] = ((df['vr20'] >= 2) & (df['open_num'] >= 1)).astype(float)
tr_w = df[(df['gap'] >= 4) & (df['gap'] <= 8) & (df['date'] < SPLIT)]


def build(d, SIGN):
    s = pd.Series(0.0, index=d.index); c = pd.Series(0.0, index=d.index)
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


sub = df[(df['gap'] >= 4) & (df['gap'] <= 8)].dropna(subset=['ret_a']).copy()
for lab, sg in (('v2 (含vpa)', SIGN), ('v2 去vpa', {k: v for k, v in SIGN.items() if k != 'vpa'})):
    sub['s'] = np.nan
    for mask in (sub['date'] < SPLIT, sub['date'] >= SPLIT):
        idx = sub.index[mask]
        sub.loc[idx, 's'] = build(sub.loc[idx], sg)
    for era, d in (('训练', sub[sub['date'] < SPLIT]), ('验证', sub[sub['date'] >= SPLIT])):
        d = d.dropna(subset=['s'])
        pick = d.sort_values('s').groupby('buy_date').tail(1)
        print('  %-12s %s: n=%d天 封板率%.1f%% 收益%+.2f%%' % (
            lab, era, len(pick), pick['seal_buy'].mean()*100, pick['ret_a'].mean()))
