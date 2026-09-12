# -*- coding: utf-8 -*-
"""正确协议: 训练集(2025-06~2026-03)先选特征 -> 验证集(2026-04~09)只做检验
对比: 训练集上看起来有效的特征, 到验证集还剩多少
"""
import json, os, sys, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def scan(d, target):
    out = {}
    for f in FEATS:
        s = d[[target, f]].dropna()
        if len(s) < 400:
            continue
        try:
            s = s.copy()
            s['b'] = pd.qcut(s[f], 10, labels=False, duplicates='drop')
        except Exception:
            continue
        g = s.groupby('b')[target].mean()
        if len(g) < 6:
            continue
        out[f] = (g.max() - g.min(), g.values, len(s))
    return out


print('=' * 84)
print('【封板率】训练集特征排序 -> 验证集表现 (中位差 = 前3档均值 - 后3档均值)')
print('=' * 84)
s_tr = scan(tr, 'seal')
s_te = scan(te, 'seal')
rank = sorted(s_tr.items(), key=lambda kv: -kv[1][0])[:12]
print('%-16s %10s %10s %11s %11s' % ('特征', '训练极差', '验证极差', '训练中位差', '验证中位差'))
for f, (sp, g, n) in rank:
    if f not in s_te:
        print('%-16s %9.1fpt  (验证无样本)' % (f, sp * 100))
        continue
    sp2, g2, n2 = s_te[f]
    m1 = (g[-3:].mean() - g[:3].mean()) * 100
    m2 = (g2[-3:].mean() - g2[:3].mean()) * 100
    keep = '  ← 保持' if (m1 > 0) == (m2 > 0) and abs(m2) > 5 else ''
    print('%-16s %9.1fpt %9.1fpt %+10.1fpt %+10.1fpt%s' % (
        f, sp * 100, sp2 * 100, m1, m2, keep))

print()
print('=' * 84)
print('【A式收益】同样协议')
print('=' * 84)
r_tr = scan(tr.dropna(subset=['ret_a']), 'ret_a')
r_te = scan(te.dropna(subset=['ret_a']), 'ret_a')
rank2 = sorted(r_tr.items(), key=lambda kv: -kv[1][0])[:12]
print('%-16s %10s %10s %11s %11s' % ('特征', '训练极差', '验证极差', '训练中位差', '验证中位差'))
for f, (sp, g, n) in rank2:
    if f not in r_te:
        print('%-16s %9.2fpt  (验证无样本)' % (f, sp))
        continue
    sp2, g2, n2 = r_te[f]
    m1 = g[-3:].mean() - g[:3].mean()
    m2 = g2[-3:].mean() - g2[:3].mean()
    keep = '  ← 保持' if (m1 > 0) == (m2 > 0) and abs(m2) > 0.5 else ''
    print('%-16s %9.2fpt %9.2fpt %+10.2fpt %+10.2fpt%s' % (
        f, sp, sp2, m1, m2, keep))

print()
print('=' * 84)
print('【关键: 训练集上"最像A"的组合, 验证集还剩多少】')
print('=' * 84)
# A画像: 早封(first_seal_min小) + 缩量(vr20小) + 大振幅分歧(amp大) + 2-3板
def mk(d):
    return pd.DataFrame({
        'early': 1 - d['first_seal_min'].rank(pct=True),
        'shrink': 1 - d['vr20'].rank(pct=True),
        'amp': d['amp'].rank(pct=True),
        'board': d['limit_days'].between(2, 3).astype(float),
    }, index=d.index)


for name, d in (('训练', tr), ('验证', te)):
    m = mk(d)
    d2 = d.assign(score=m.sum(axis=1))
    d2 = d2.dropna(subset=['score', 'ret_a'])
    d2['q'] = pd.qcut(d2['score'], 5, labels=False, duplicates='drop')
    g = d2.groupby('q').agg(ret=('ret_a', 'mean'), seal=('seal', 'mean'),
                            win=('ret_a', lambda s: (s > 0).mean()*100), n=('seal', 'size'))
    print('  [%s集] A画像打分五档:' % name)
    for q, r in g.iterrows():
        print('    第%d档 收益%+.2f%% 封板率%.0f%% 胜率%.0f%% n=%d' % (
            q + 1, r['ret'], r['seal']*100, r['win'], r['n']))
