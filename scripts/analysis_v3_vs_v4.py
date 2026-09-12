# -*- coding: utf-8 -*-
"""V3时代 vs V4时代 实盘推荐画像对比 + V3评分复现检验"""
import json, os, sys, io, warnings, statistics as st
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
df['code'] = df['code'].astype(str).str.zfill(6)
# 数据集 date = 涨停日D; 买入日 = D 的下一交易日
DAYS = sorted(df['date'].unique())
NX = {d: DAYS[i + 1] for i, d in enumerate(DAYS) if i + 1 < len(DAYS)}
df['buy_date'] = df['date'].map(NX)

rev = json.load(open('logs/recommendation_review.json', encoding='utf-8'))['reviews']
picks = []
for d, r in rev.items():
    for s in r['stocks']:
        picks.append(dict(buy_date=d, rank=s.get('rank'),
                          name=s.get('name'), code=str(s.get('code')).zfill(6),
                          rec_score=s.get('score'), seal=bool(s.get('T', {}).get('limit_up')),
                          pnl=s.get('pnl_pct'), gap=s.get('rec_gap')))
p = pd.DataFrame(picks)
m = p.merge(df, on=['code', 'buy_date'], how='left', suffixes=('', '_ds'))
print('推荐匹配到特征: %d/%d' % (m['vr20'].notna().sum(), len(m)))

V4 = '2026-08-26'
FE = ['vr20', 'limit_days', 'open_num', 'first_seal_min', 'theme_max', 'amp',
      'turnover', 'mktcap', 'ord_amt', 'pos20', 'ret5', 'zt_n', 'seal_buy']
print()
print('%s' % ('=' * 84))
print('【V3时代 vs V4时代: 选中票的特征画像】')
print('=' * 84)
print('%-22s %10s %10s %9s' % ('特征', 'V3时代均值', 'V4时代均值', '差异'))
for f in FE:
    a = m[(m['buy_date'] < V4)][f].dropna()
    b = m[(m['buy_date'] >= V4)][f].dropna()
    if len(a) < 5 or len(b) < 5:
        continue
    d = b.mean() - a.mean()
    flag = '  ←' if abs(d) > 0.3 * (abs(a.mean()) + 1e-9) else ''
    print('%-22s %10.2f %10.2f %+9.2f%s' % (f, a.mean(), b.mean(), d, flag))

print()
print('【同期全市场池(对照组)】')
allr = df[df['buy_date'].notna()]
for f in ('vr20', 'limit_days', 'open_num', 'first_seal_min', 'theme_max', 'amp'):
    a = allr[(allr['buy_date'] >= '2026-08-10') & (allr['buy_date'] < V4)][f].dropna()
    b = allr[(allr['buy_date'] >= V4) & (allr['buy_date'] <= '2026-09-11')][f].dropna()
    print('%-22s %10.2f %10.2f %+9.2f' % (f, a.mean(), b.mean(), b.mean() - a.mean()))

print()
print('=' * 84)
print('【V3评分复现】用V3的因子表给全样本打分, 看排序效果')
print('=' * 84)
cfg = json.load(open('backup/scoring_config_v3全段_20260826.json', encoding='utf-8'))
vr_t = cfg['tables']['v3']['vr_tiers']
cons_s = cfg['cons_score']
seal_t = cfg['seal_time_tiers']
sec_t = cfg['sector_tiers']
div = cfg['divergence']


def tier(v, table):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return 0
    for lim, sc in table:
        if v <= lim:
            return sc
    return table[-1][1]


def v3_score(r):
    if pd.isna(r['vr20']) or pd.isna(r['first_seal_min']):
        return np.nan
    s = tier(r['vr20'], vr_t)
    ld = int(r['limit_days']) if not pd.isna(r['limit_days']) else 1
    s += (-2 if ld <= 1 else {2: 6, 3: 14, 4: 22, 5: 26}.get(ld, 30))
    s += tier(r['first_seal_min'], seal_t)
    if r['board_type'] == '一字板':
        s += 20
    elif r['board_type'] == 'T字板':
        s += 10
    tm = r['theme_max'] if not pd.isna(r['theme_max']) else 0
    s += 12 if tm >= 5 else 6 if tm >= 3 else 2 if tm >= 2 else 0
    # 分歧质量: 爆量 + 炸板回封 + 涨停
    if (not pd.isna(r['vr20'])) and r['vr20'] >= div['prev_day_vol_min'] and \
       (not pd.isna(r['open_num'])) and r['open_num'] >= 1:
        s += div['bonus'] if tm >= 2 else div['no_sector_bonus']
    return s


sub = df[(df['buy_date'] >= '2026-08-10') & (df['buy_date'] <= '2026-09-11')].copy()
sub['v3'] = sub.apply(v3_score, axis=1)
sub['v4score_rank'] = sub.groupby('buy_date')['v3'].rank(ascending=False)
# 每日取 V3 第一名 (gap4-8% 且非一字)
elig = sub[(sub['gap'] >= 4) & (sub['gap'] <= 8) & (sub['board_type'] != '一字板')].copy()
elig['r'] = elig.groupby('buy_date')['v3'].rank(ascending=False, method='first')
top = elig[elig['r'] <= 3]
print('每日V3打分Top3 (gap4-8%%): n=%d' % len(top))
print('  封板率 %.1f%%  ret_a均 %+.2f%%' % (top['seal_buy'].mean()*100, top['ret_a'].mean()))
print('  同期全池 gap4-8%%: 封板率 %.1f%%  ret_a均 %+.2f%%  (n=%d)' % (
    elig['seal_buy'].mean()*100, elig['ret_a'].mean(), len(elig)))

print()
print('  V3分五档 (gap4-8%内):')
e2 = elig.dropna(subset=['ret_a']).copy()
e2['q'] = pd.qcut(e2['v3'], 5, labels=False, duplicates='drop')
g = e2.groupby('q').agg(v3=('v3', 'mean'), seal=('seal_buy', 'mean'),
                        ret=('ret_a', 'mean'), n=('seal_buy', 'size'))
for q, r in g.iterrows():
    print('    第%d档 V3分%.1f 封板率%.0f%% 收益%+.2f%% n=%d' % (
        q + 1, r['v3'], r['seal']*100, r['ret'], r['n']))
