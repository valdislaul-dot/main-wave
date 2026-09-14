# -*- coding: utf-8 -*-
"""买入打分: 只用"训练集验证过、验证集保持"的特征, 在 gap4-8% 窗口内排序
特征(按验证集中位差排序, 方向已确认):
  分时封板占比+ / 首封时间- / 末封时间- / 分时首封位置- / 振幅- / 近5日涨幅+ / 前日涨幅+ / 封单额+
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
SIGN = {'tp_seal_ratio': +1, 'first_seal_min': -1, 'last_seal_min': -1,
        'tp_first_pos': -1, 'amp': -1, 'ret5': +1, 'prev_pct': +1, 'ord_amt': +1}
FEATS = list(SIGN)

# 只用训练集拟合分位映射(避免验证集信息泄漏)
SPLIT = '2026-04-01'
tr = df[df['date'] < SPLIT]


def build_score(d):
    """每个特征 -> 训练集分位(0-1), 按方向累加"""
    s = pd.Series(0.0, index=d.index)
    cnt = pd.Series(0.0, index=d.index)
    for f, sg in SIGN.items():
        base = tr[f].dropna()
        if len(base) < 500:
            continue
        q = base.rank(pct=True)
        # 用训练集的分位断点映射
        cuts = base.quantile(np.linspace(0, 1, 21)).values
        v = d[f]
        r = np.searchsorted(cuts, v.values, side='right') / 20.0
        r = np.clip(r, 0, 1)
        r = np.where(pd.isna(v.values), np.nan, r)
        s = s + pd.Series(np.where(np.isnan(r), 0, (r if sg > 0 else 1 - r)), index=d.index)
        cnt = cnt + pd.Series(np.where(np.isnan(r), 0, 1), index=d.index)
    return s / cnt.replace(0, np.nan)


df['buy_score'] = np.nan
for lo, hi, lab in ((None, SPLIT, '训练'), (SPLIT, None, '验证')):
    idx = df.index[df['date'] < SPLIT] if hi else df.index[df['date'] >= SPLIT]
    df.loc[idx, 'buy_score'] = build_score(df.loc[idx])

sub = df[(df['gap'] >= 4) & (df['gap'] <= 8)].dropna(subset=['ret_a', 'buy_score']).copy()
print('gap4-8%% 有效样本 n=%d\n' % len(sub))
for lab, d in (('训练 2025-06~2026-03', sub[sub['date'] < SPLIT]),
               ('验证 2026-04~09', sub[sub['date'] >= SPLIT])):
    if len(d) < 60:
        continue
    print('【%s】n=%d  全体封板率 %.1f%% 收益 %+.2f%%' % (
        lab, len(d), d['seal_buy'].mean()*100, d['ret_a'].mean()))
    d = d.copy()
    d['q'] = pd.qcut(d['buy_score'], 5, labels=False, duplicates='drop')
    g = d.groupby('q').agg(sc=('buy_score', 'mean'), seal=('seal_buy', 'mean'),
                           ret=('ret_a', 'mean'),
                           win=('ret_a', lambda s: (s > 0).mean()*100), n=('ret_a', 'size'))
    for q, r in g.iterrows():
        print('   第%d档 分%.3f 封板率%3.0f%% 收益%+6.2f%% 胜率%3.0f%% n=%d' % (
            q + 1, r['sc'], r['seal']*100, r['ret'], r['win'], r['n']))
    top20 = d.nlargest(max(20, int(len(d) * 0.2)), 'buy_score')
    print('   Top20%%: 封板率%.0f%% 收益%+.2f%%' % (
        top20['seal_buy'].mean()*100, top20['ret_a'].mean()))
    print()

print('=== 每日只买打分最高1只 (最贴近实盘) ===')
for lab, d in (('训练', sub[sub['date'] < SPLIT]), ('验证', sub[sub['date'] >= SPLIT])):
    if len(d) < 60:
        continue
    pick = d.sort_values('buy_score').groupby('buy_date').tail(1)
    print('  %s: n=%d天  封板率%.1f%%  均收益%+.2f%%  胜率%.0f%%' % (
        lab, len(pick), pick['seal_buy'].mean()*100, pick['ret_a'].mean(),
        (pick['ret_a'] > 0).mean()*100))
    base = d.groupby('buy_date').agg(s=('seal_buy', 'mean'), r=('ret_a', 'mean'))
    print('    同日全池基准: 封板率%.1f%%  均收益%+.2f%%' % (
        base['s'].mean()*100, base['r'].mean()))

print()
print('=' * 78)
print('【同期对照】新打分 vs 实际推荐')
print('=' * 78)
for lo, hi, lab in (('2026-08-10', '2026-08-25', 'V3时代 08-10~08-25'),
                    ('2026-08-26', '2026-09-10', 'V4时代 08-26~09-10')):
    d = sub[(sub['buy_date'] >= lo) & (sub['buy_date'] <= hi)]
    if len(d) < 10:
        continue
    pick = d.sort_values('buy_score').groupby('buy_date').tail(1)
    print('【%s】' % lab)
    print('   新打分每日Top1: n=%d天 封板率%.1f%% 均收益%+.2f%% 胜率%.0f%%' % (
        len(pick), pick['seal_buy'].mean()*100, pick['ret_a'].mean(),
        (pick['ret_a'] > 0).mean()*100))
    print('   同期全池:        封板率%.1f%% 均收益%+.2f%%' % (
        d['seal_buy'].mean()*100, d['ret_a'].mean()))
    rev = json.load(open('logs/recommendation_review.json', encoding='utf-8'))['reviews']
    rows = [s for dt, r in rev.items() if lo <= dt <= hi for s in r['stocks']]
    seal = sum(1 for x in rows if x.get('T', {}).get('limit_up'))
    pn = [x['pnl_pct'] for x in rows if x.get('pnl_pct') is not None]
    print('   实际推荐:        n=%d 封板率%.1f%% 均收益%+.2f%%' % (
        len(rows), seal / len(rows) * 100, sum(pn) / len(pn)))
    print()
