# -*- coding: utf-8 -*-
"""V5 评分重构: A方法论定因子集 + 数据定权重
形态保持百分制加权: 总分 = Σ 归一化分(0-100) × 权重%   (权重和=100)

因子集(A方法论):
  候选事件: 连板背景(cons) + 爆量(vr) + 烂板回封(分歧质量 divergence) + 板型
  次日确认: 竞价高开(gap) + 缩量/量能(vr) + 板块效应(theme) + 封板时间(seal)
  环境:     流通市值(mktcap) + 近期涨幅(ret5) + 换手(turnover)

流程: ① 归一化表 由训练集分位封板率估计  ② 权重 由训练集搜索  ③ 验证集只做检验
"""
import json, os, sys, io, warnings, itertools, random
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
DAYSA = sorted(df['date'].unique())
df['buy_date'] = df['date'].map({d: DAYSA[i + 1] for i, d in enumerate(DAYSA) if i + 1 < len(DAYSA)})
# A方法论派生
df['heavy_vol'] = (df['vr20'] >= 2).astype(float)
df['rotten'] = (df['open_num'] >= 1).astype(float)
df['divergence'] = ((df['vr20'] >= 2) & (df['open_num'] >= 1)).astype(float)
df['div_strong'] = ((df['vr20'] >= 2) & (df['open_num'] >= 1) & (df['amp'] >= 10)).astype(float)

SPLIT = '2026-04-01'
W = df[(df['gap'] >= 4) & (df['gap'] <= 8)].copy()
tr = W[W['date'] < SPLIT]
te = W[W['date'] >= SPLIT]
print('窗口 gap4-8%%: 训练 %d (封板%.1f%%) | 验证 %d (封板%.1f%%)\n' % (
    len(tr), tr['seal_buy'].mean()*100, len(te), te['seal_buy'].mean()*100))

# ---- ① 归一化表: 训练集分位 -> 封板率 -> 线性映射到 0-100 ----
FACTORS = ['vr20', 'gap', 'cons_x', 'divergence', 'seal_x', 'theme_x', 'mktcap_x', 'ret5_x', 'turnover']
df['cons_x'] = df['limit_days']
df['seal_x'] = df['first_seal_min']
df['theme_x'] = df['theme_max']
df['mktcap_x'] = df['mktcap']
df['ret5_x'] = df['ret5']
df['turnover_x'] = df['turnover']
W = df[(df['gap'] >= 4) & (df['gap'] <= 8)].copy()
tr = W[W['date'] < SPLIT]
te = W[W['date'] >= SPLIT]

MAP = {}
NQ = 8
for f in FACTORS:
    s = tr[[f, 'seal_buy']].dropna()
    try:
        s = s.copy()
        s['q'] = pd.qcut(s[f], NQ, labels=False, duplicates='drop')
    except Exception:
        continue
    g = s.groupby('q').agg(rate=('seal_buy', 'mean'), v=('seal_buy', 'size'))
    # 分位边界
    edges = s.groupby('q')[f].max().values
    rates = g['rate'].values
    MAP[f] = (edges, rates)
    print('%-12s 训练分位封板率: %s' % (f, ' '.join('%.0f%%' % (r*100) for r in rates)))

# 把封板率映射成 0-100 (相对该因子内 min/max, 保留相对信息但压缩极端)
def norm_score(f, values):
    if f not in MAP:
        return pd.Series(50.0, index=values.index)
    edges, rates = MAP[f]
    r = rates / rates.max() * 100 if rates.max() > 0 else rates * 0
    idx = np.searchsorted(edges, values.values, side='left')
    idx = np.clip(idx, 0, len(r) - 1)
    out = r[idx]
    return pd.Series(np.where(pd.isna(values.values), np.nan, out), index=values.index)

print()
print('=' * 80)
print('【权重搜索】目标 = 训练集"每日Top1"的封板率 (A方法论: 只买1只)')
print('=' * 80)
base_order = FACTORS
N = pd.DataFrame({f: norm_score(f, W[f]) for f in FACTORS}, index=W.index)
N['date'] = W['date'].values
N['buy_date'] = W['buy_date'].values
N['seal'] = W['seal_buy'].values
N['ret'] = W['ret_a'].values
N['is_tr'] = (W['date'] < SPLIT).values

trN = N[N['is_tr']].copy()
teN = N[~N['is_tr']].dropna(subset=['ret']).copy()


def evaluate(w, d):
    w = np.array(w, dtype=float)
    if w.sum() <= 0:
        return 0, 0
    cols = [c for c in base_order]
    sc = (d[cols].fillna(d[cols].median()) * (w / w.sum())).sum(axis=1)
    d = d.assign(_s=sc)
    pick = d.sort_values('_s').groupby('buy_date').tail(1)
    return pick['seal'].mean() * 100, pick['ret'].mean()


rng = random.Random(7)
best = None
for it in range(3000):
    w = np.array([rng.choice([0, 1, 2, 3, 4, 6, 8, 10, 12, 15, 20]) for _ in base_order], dtype=float)
    if w.sum() == 0:
        continue
    s, r = evaluate(w, trN)
    score = s * 0.6 + r * 20          # 封板率为主, 收益为辅
    if best is None or score > best[0]:
        best = (score, w.copy(), s, r)
print('最优权重(训练): 封板率%.1f%% 收益%+.2f%%' % (best[2], best[3]))
w_best = best[1] / best[1].sum() * 100
print('  ' + '  '.join('%s=%.1f%%' % (f, v) for f, v in zip(base_order, w_best) if v > 0.5))

print()
print('=' * 80)
print('【训练 vs 验证】权重搜索只在训练集做过')
print('=' * 80)
s_tr, r_tr = evaluate(best[1], trN)
s_te, r_te = evaluate(best[1], teN)
bt = trN.groupby('buy_date').agg(s=('seal', 'mean'), r=('ret', 'mean'))
be = teN.groupby('buy_date').agg(s=('seal', 'mean'), r=('ret', 'mean'))
print('  V5 每日Top1  训练: 封板率%.1f%% 收益%+.2f%% (n=%d天) | 同日全池 %0.1f%%/%+.2f%%' % (
    s_tr, r_tr, len(bt), bt['s'].mean()*100, bt['r'].mean()))
print('  V5 每日Top1  验证: 封板率%.1f%% 收益%+.2f%% (n=%d天) | 同日全池 %0.1f%%/%+.2f%%' % (
    s_te, r_te, len(be), be['s'].mean()*100, be['r'].mean()))

# 等权对照
eq = np.ones(len(base_order))
print('  等权对照     训练: %.1f%%/%+.2f%% | 验证: %.1f%%/%+.2f%%' % (
    *evaluate(eq, trN), *evaluate(eq, teN)))

print()
print('=' * 80)
print('【同期实盘对照】')
print('=' * 80)
for lo, hi, lab in (('2026-08-10', '2026-08-25', 'V3时代'), ('2026-08-26', '2026-09-10', 'V4时代')):
    d = N[(N['buy_date'] >= lo) & (N['buy_date'] <= hi)].dropna(subset=['ret'])
    if len(d) < 10:
        continue
    cols = base_order
    sc = (d[cols].fillna(d[cols].median()) * (best[1] / best[1].sum())).sum(axis=1)
    d = d.assign(_s=sc)
    pick = d.sort_values('_s').groupby('buy_date').tail(1)
    print('  [%s] 全池 封板%.1f%% 收益%+.2f%% | V5每日Top1 封板%.1f%% 收益%+.2f%%' % (
        lab, d['seal'].mean()*100, d['ret'].mean(),
        pick['seal'].mean()*100, pick['ret'].mean()))

json.dump({'factors': base_order, 'weights': w_best.tolist(),
           'map': {k: [v[0].tolist(), v[1].tolist()] for k, v in MAP.items()}},
          open('data/_v5_weights.json', 'w', encoding='utf-8'), ensure_ascii=False)
print('\n已存 data/_v5_weights.json')
