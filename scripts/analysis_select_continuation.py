# -*- coding: utf-8 -*-
"""最后一块: 封板之后能不能继续封?
样本: D+1封板的票 -> D+2是否再封 / 持有多一天的收益
训练 2025-06~2026-03 | 验证 2026-04~09
"""
import json, os, sys, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

df = pd.read_csv('data/_select_dataset.csv', low_memory=False)
df['code'] = df['code'].astype(str).str.zfill(6)
FEATS = ['turnover', 'open_num', 'suc_rate', 'mktcap', 'ord_amt', 'limit_days',
         'first_seal_min', 'last_seal_min', 'theme_max', 'vr20', 'prev_pct', 'amp',
         'is_yizi', 'pos20', 'ret5', 'ret10', 'ret20', 'zt_n', 'max_cons_day',
         'tp_seal_ratio', 'tp_opens', 'tp_first_pos', 'tp_final_sealed',
         'tp_close_pct', 'tp_min_after', 'tp_amp', 'tp_last30_min']
df['board_type_num'] = df['board_type'].map({'一字板': 3, 'T字板': 2, '换手板': 1})
FEATS.append('board_type_num')

# ---- 需要 D+2 信息: 重新扫池 ----
def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))


pools = {}
for base in ('data/zt_pool_history_ths', 'data/zt_pool'):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json') or f == 'stock_index.json':
            continue
        ymd = f[:-5]
        d = ymd[:4] + '-' + ymd[4:6] + '-' + ymd[6:8]
        data = rd(os.path.join(base, f))
        rows = data if isinstance(data, list) else data.get('stocks', [])
        pools[d] = {str(x.get('code', '')).zfill(6) for x in rows if x.get('code')}
DAYS = sorted(pools)
nxt2 = {}
for i, d in enumerate(DAYS):
    if i + 1 < len(DAYS):
        nxt2[d] = DAYS[i + 1]

AUG = json.load(open('data/_regime_klines_aug.json', encoding='utf-8'))
KL = {}


def kline(c):
    if c in KL:
        return KL[c]
    p = 'data/kline_data/' + c + '.json'
    out = {}
    if os.path.exists(p):
        raw = rd(p)
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        out = {b['date']: b for b in rows if b.get('date')}
    KL[c] = out
    return out


def kb(c, d):
    m = kline(c)
    if d in m:
        return m[d]
    for r in (AUG.get(c) or []):
        if r.get('date') == d:
            return r
    return None


rows = []
for _, r in df.iterrows():
    if r['seal'] != 1:
        continue
    D1 = nxt2.get(r['date'])
    if not D1:
        continue
    D2 = nxt2.get(D1)
    if not D2:
        continue
    b1, b2 = kb(r['code'], D1), kb(r['code'], D2)
    if not b1 or not b2 or not b1.get('close') or not b2.get('open'):
        continue
    seal2 = 1 if r['code'] in pools.get(D2, set()) else 0
    # 口径: D+1收盘买(涨停价) -> D+2 按A式出
    e = b1['close']
    lu2 = (b2.get('pct_change') or 0) >= 9.8
    ex = b2['close'] if lu2 else 0.7 * (b2['high'] + b2['open']) / 2 + 0.3 * b2['close']
    d = r.to_dict()
    d['seal2'] = seal2
    d['ret_hold'] = (ex - e) / e * 100
    rows.append(d)

h = pd.DataFrame(rows)
print('D+1封板样本 %d 行 | D+2再封率 %.1f%% | 持有一天均收益 %+.2f%% (胜率%.0f%%)\n' % (
    len(h), h['seal2'].mean()*100, h['ret_hold'].mean(),
    (h['ret_hold'] > 0).mean()*100))

SPLIT = '2026-04-01'
tr, te = h[h['date'] < SPLIT], h[h['date'] >= SPLIT]
print('训练 %d (再封率 %.1f%%) | 验证 %d (再封率 %.1f%%)\n' % (
    len(tr), tr['seal2'].mean()*100, len(te), te['seal2'].mean()*100))

print('=' * 80)
print('【什么预测 D+2 再封】训练集排序 -> 验证集')
print('=' * 80)
res = []
for f in FEATS:
    a = tr[[f, 'seal2']].dropna()
    if len(a) < 300:
        continue
    try:
        a = a.copy()
        a['b'] = pd.qcut(a[f], 5, labels=False, duplicates='drop')
    except Exception:
        continue
    g = a.groupby('b')['seal2'].mean()
    if len(g) < 4:
        continue
    res.append((g.max() - g.min(), f, g.values))
print('%-16s %10s %10s %11s' % ('特征', '训练极差', '验证极差', '验证方向'))
for sp, f, g in sorted(res, reverse=True)[:12]:
    b = te[[f, 'seal2']].dropna()
    try:
        b = b.copy()
        b['b'] = pd.qcut(b[f], 5, labels=False, duplicates='drop')
        g2 = b.groupby('b')['seal2'].mean()
    except Exception:
        continue
    if len(g2) < 4:
        continue
    keep = '保持' if (g[-1] - g[0]) * (g2.values[-1] - g2.values[0]) > 0 else '反转'
    print('%-16s %9.1fpt %9.1fpt   %s  %s' % (
        f, sp*100, (g2.max()-g2.min())*100, keep,
        ' '.join('%.0f' % (x*100) for x in g2.values)))

print()
print('=' * 80)
print('【持有日收益】哪些特征预测 "多持一天" 的收益')
print('=' * 80)
res2 = []
for f in FEATS:
    a = tr[[f, 'ret_hold']].dropna()
    if len(a) < 300:
        continue
    try:
        a = a.copy()
        a['b'] = pd.qcut(a[f], 5, labels=False, duplicates='drop')
    except Exception:
        continue
    g = a.groupby('b')['ret_hold'].mean()
    if len(g) < 4:
        continue
    res2.append((g.max() - g.min(), f, g.values))
print('%-16s %11s %11s' % ('特征', '训练极差', '验证极差'))
for sp, f, g in sorted(res2, reverse=True)[:10]:
    b = te[[f, 'ret_hold']].dropna()
    try:
        b = b.copy()
        b['b'] = pd.qcut(b[f], 5, labels=False, duplicates='drop')
        g2 = b.groupby('b')['ret_hold'].mean()
    except Exception:
        continue
    print('%-16s %9.2fpt %9.2fpt  %s' % (
        f, sp, g2.max()-g2.min(), ' '.join('%+4.1f' % x for x in g2.values)))
