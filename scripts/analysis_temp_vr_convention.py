# -*- coding: utf-8 -*-
"""按 scoring.py 真实口径重算 vr 分布 (2026-09-23)

口径必须与 scoring 一致, 否则分档结论无意义:
  vol_ma5  = mean(v[i-4..i])  ← 分母含当日!
  vol_ma20 = mean(v[i-19..i]) ← 分母含当日!
  vol_ratio5  数学上限 ≈ 5   (当日占分母 1/5)
  vol_ratio20 数学上限 ≈ 20
  vr = vol_ratio5 if cons_lu_before >= 2 else vol_ratio20

对照两组:
  A   = A 实际买入的 67 笔(信号日=买入日D的前一天)
  池  = 同区间全市场涨停事件
"""
import json, os, sys, io, collections, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = 'data/kline_data'
POOL_LO, POOL_HI = '2026-03-01', '2026-07-31'
A_LO, A_HI = '2026-03-01', '2026-07-31'

TIERS = [[0.2, 40], [0.3, 34], [0.4, 27], [0.5, 20], [0.6, 14], [0.7, 8],
         [0.85, 3], [1.2, -1], [2.5, -2], [5.0, -1], [99, 0]]


def rd(p):
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            raw = json.load(open(p, encoding=enc))
            return raw.get('data', raw) if isinstance(raw, dict) else raw
        except Exception:
            continue
    return None


def vr_and_cons(kl, idx):
    """返回 (vr, cons) — 与 scoring.precompute_klines 同口径"""
    if idx < 20:
        return None, None
    v = kl[idx]['volume']
    ma5 = sum(kl[j]['volume'] for j in range(idx - 4, idx + 1)) / 5
    ma20 = sum(kl[j]['volume'] for j in range(idx - 19, idx + 1)) / 20
    r5 = v / ma5 if ma5 > 0 else 1
    r20 = v / ma20 if ma20 > 0 else 1
    cons = 0
    j = idx
    while j >= 1:
        pk = kl[j - 1]['close']
        if pk > 0 and (kl[j]['close'] - pk) / pk >= 0.098:
            cons += 1
            j -= 1
        else:
            break
    cons_before = max(cons - 1, 0)
    return (r5 if cons_before >= 2 else r20), cons


def tier_of(vr):
    for b, s in TIERS:
        if vr < b:
            return b, s
    return 99, 0


# ---- A 的成交 ----
ts = json.load(open('backup/_a_trades_recon.json', encoding='utf-8'))
a_rows = []
for t in ts:
    kl = rd(os.path.join(BASE, t['code'] + '.json'))
    if not kl:
        continue
    idx = next((i for i, k in enumerate(kl) if k.get('date') == t['D']), None)
    if idx is None or idx - 1 < 20:
        continue
    vr, cons = vr_and_cons(kl, idx - 1)      # 信号日
    if vr is None:
        continue
    a_rows.append((t, vr, cons))

print('=' * 88)
print('按 scoring 真实口径(vr=vol_ratio5 if cons>=2 else vol_ratio20)重算')
print('=' * 88)
print()
print('A 实际买入 n=%d 的信号日 vr 分布:' % len(a_rows))
ab = collections.Counter()
for t, vr, cons in a_rows:
    ab[tier_of(vr)[0]] += 1
for b, s in TIERS:
    n = ab.get(b, 0)
    print('  vr<%-5s (分%+3d): %3d 笔  %5.1f%%' % (b, s, n, n / len(a_rows) * 100))
print()
print('  → 有命中的档位:', sorted({b for b in ab if b != 99}))
print('  → vr>=5 档(分0)命中:', ab.get(99, 0), '笔')
print()

# ---- 全市场涨停池基线 ----
pool = collections.Counter()
npool = 0
for fn in os.listdir(BASE):
    if not fn.endswith('.json'):
        continue
    code = fn[:-5]
    if code.startswith(('300', '301', '688', '8', '9')):
        continue
    kl = rd(os.path.join(BASE, fn))
    if not kl:
        continue
    for i in range(20, len(kl)):
        d = kl[i].get('date', '')
        if not (POOL_LO <= d <= POOL_HI):
            continue
        pk = kl[i - 1]['close']
        if pk <= 0 or (kl[i]['close'] - pk) / pk < 0.098:
            continue
        vr, cons = vr_and_cons(kl, i)
        if vr is None:
            continue
        pool[tier_of(vr)[0]] += 1
        npool += 1
print('全市场涨停事件基线 n=%d:' % npool)
for b, s in TIERS:
    n = pool.get(b, 0)
    print('  vr<%-5s (分%+3d): %6d 次  %5.1f%%' % (b, s, n, n / npool * 100))
print()
print('=== A 超额倍数 (A占比 / 基线占比) ===')
print('  %-10s %8s %10s %8s' % ('档位', 'A占比', '基线占比', '倍数'))
for b, s in TIERS:
    a_ = ab.get(b, 0) / len(a_rows) * 100
    p_ = pool.get(b, 0) / npool * 100
    r = ('%6.2fx' % (a_ / p_)) if p_ > 0 else '     n/a'
    print('  vr<%-7s %7.1f%% %9.1f%% %8s' % (b, a_, p_, r))
print()
print('=== A 各档实际盈亏 ===')
d = collections.defaultdict(list)
for t, vr, cons in a_rows:
    if t.get('pnl') is not None:
        d[tier_of(vr)[0]].append(t['pnl'])
for b, s in TIERS:
    v = d.get(b, [])
    if v:
        print('  vr<%-7s (分%+3d): n=%2d 均%+7.2f%% 中位%+6.2f%%' % (b, s, len(v), statistics.mean(v), statistics.median(v)))
