"""
情绪指标体系评估 (2026-08-31, 基于 vibe-astock 开源公式)
目标: 用本地6个月涨停池历史, 计算 晋级率/连板溢价/炸板率/情绪分/赚钱效应(均值vs中位数),
      检验各指标与「次日赚钱效应」「次日涨停家数」的相关性, 评估能否补强温度开关。
公式来源: simonlin1212/vibe-astock duanxian/emotion_metrics.py (Apache-2.0)
数据: data/zt_pool_history/ + data/zt_pool/ 涨停池快照 + data/kline_data/ 全库K线
"""
import json, os, sys
from statistics import mean, median
from scipy.stats import spearmanr, pearsonr

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_pool(fp):
    try:
        with open(fp, encoding='utf-8') as f:
            pool = json.load(f)
    except UnicodeDecodeError:
        with open(fp, encoding='gbk') as f:
            pool = json.load(f)
    return pool if isinstance(pool, list) else pool.get('stocks', [])

# ── 1. 加载全部涨停池(按日) ──
pools = {}
for sub in ('zt_pool_history', 'zt_pool'):
    d = os.path.join(BASE, 'data', sub)
    if not os.path.isdir(d):
        continue
    for fn in sorted(os.listdir(d)):
        if fn.endswith('.json'):
            date = f'{fn[:4]}-{fn[4:6]}-{fn[6:8]}'
            pools[date] = load_pool(os.path.join(d, fn))
dates = sorted(pools)
print(f'涨停池天数: {len(dates)} ({dates[0]} ~ {dates[-1]})')

# ── 2. K线 pct 映射 (只加载池内出现过的代码) ──
codes_used = set()
for d in dates:
    for s in pools[d]:
        codes_used.add(str(s.get('code', '')).zfill(6))
print(f'涉及代码数: {len(codes_used)}, 加载K线...')

pct_map = {}  # code -> {date: pct}
for code in codes_used:
    kp = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
    if not os.path.exists(kp):
        continue
    try:
        with open(kp, encoding='utf-8') as f:
            raw = json.load(f)
        kl = raw.get('data', raw) if isinstance(raw, dict) else raw
    except Exception:
        continue
    m = {}
    for i, bar in enumerate(kl):
        pc = bar.get('pct_change')
        if pc is None and i > 0 and bar.get('close') and kl[i-1].get('close') and kl[i-1]['close'] > 0:
            pc = (bar['close'] - kl[i-1]['close']) / kl[i-1]['close'] * 100
        if pc is not None:
            m[bar.get('date', '')] = pc
    pct_map[code] = m
print(f'K线加载完成: {len(pct_map)}只')

# ── 3. 逐日指标 ──
rows = []  # {date, zt_n, max_cons, broken_rate, promo1, promo2, promo3, promo_all,
           #  premium, me_mean, me_median, me_pos, me_again}
for i, d in enumerate(dates):
    pool = pools[d]
    if not pool:
        continue
    zt_n = len(pool)
    max_cons = max((int(s.get('limit_days', 1) or 1) for s in pool), default=1)
    n_br = sum(1 for s in pool if int(s.get('break_times', 0) or 0) > 0)
    broken_rate = n_br / zt_n
    cur_codes = {str(s.get('code', '')).zfill(6) for s in pool}

    row = {'date': d, 'zt_n': zt_n, 'max_cons': max_cons, 'broken_rate': broken_rate}

    if i > 0:
        prev = pools[dates[i-1]]
        prev_codes = {str(s.get('code', '')).zfill(6): int(s.get('limit_days', 1) or 1) for s in prev}
        # 晋级率
        buckets = {1: [], 2: [], 3: []}
        for c, b in prev_codes.items():
            key = 1 if b == 1 else (2 if b == 2 else 3)
            buckets[key].append(c in cur_codes)
        row['promo1'] = sum(buckets[1]) / len(buckets[1]) if buckets[1] else None
        row['promo2'] = sum(buckets[2]) / len(buckets[2]) if buckets[2] else None
        row['promo3'] = sum(buckets[3]) / len(buckets[3]) if buckets[3] else None
        allv = buckets[1] + buckets[2] + buckets[3]
        row['promo_all'] = sum(allv) / len(allv) if allv else None
        # 连板溢价: 昨2板+今日涨幅(均值)
        hi = [c for c, b in prev_codes.items() if b >= 2]
        rets = [pct_map.get(c, {}).get(d) for c in hi]
        rets = [r for r in rets if r is not None]
        row['premium'] = mean(rets) if rets else None
        # 赚钱效应: 昨全部涨停股今日涨幅
        rets_all = [pct_map.get(c, {}).get(d) for c in prev_codes]
        rets_all = [r for r in rets_all if r is not None]
        if rets_all:
            row['me_mean'] = mean(rets_all)
            row['me_median'] = median(rets_all)
            row['me_pos'] = sum(1 for r in rets_all if r > 0) / len(rets_all)
            row['me_again'] = sum(1 for c in prev_codes if c in cur_codes) / len(rets_all)
    rows.append(row)

# ── 4. 情绪分 (vibe公式, 10日窗 minmax: (n_zt + n_hc + (1-炸板率))/3) ──
def minmax_norm(vals):
    lo, hi = min(vals), max(vals)
    return [0.5] * len(vals) if hi == lo else [(v - lo) / (hi - lo) for v in vals]

for i, r in enumerate(rows):
    if i < 9:
        r['emotion'] = None
        continue
    win = rows[i-9:i+1]
    n_zt = minmax_norm([float(x['zt_n']) for x in win])
    n_hc = minmax_norm([float(x['max_cons']) for x in win])
    brs = [x['broken_rate'] for x in win]
    n_br = minmax_norm([1 - float(b) for b in brs])
    r['emotion'] = (n_zt[-1] + n_hc[-1] + n_br[-1]) / 3

# ── 5. 相关性检验: 指标(t) vs 次日赚钱效应(t+1) / 次日涨停数(t+1) ──
indicators = ['zt_n', 'max_cons', 'broken_rate', 'promo_all', 'promo1', 'promo2', 'promo3',
              'premium', 'me_mean', 'me_median', 'me_pos', 'me_again', 'emotion']
targets = {'次日赚钱效应均值': 'me_mean', '次日赚钱效应中位数': 'me_median', '次日涨停家数': 'zt_n'}

print()
print('=' * 74)
print('  斯皮尔曼相关: 指标(t) vs 次日(t+1)  (样本=可用日数, ~6个月)')
print('=' * 74)
print(f'{"指标":<14}{"次日ME均值":>12}{"次日ME中位":>12}{"次日涨停数":>12}{"样本":>7}')
for ind in indicators:
    line = f'{ind:<16}'
    for tgt in targets.values():
        xs, ys = [], []
        for i, r in enumerate(rows[:-1]):
            if r.get(ind) is None or rows[i+1].get(tgt) is None:
                continue
            xs.append(r[ind]); ys.append(rows[i+1][tgt])
        if len(xs) >= 15:
            rho, _ = spearmanr(xs, ys)
            line += f'{rho:>+12.2f}'
        else:
            line += f'{"n/a":>12}'
    line += f'{len(xs):>7}'
    print(line)
print()
print('注: 斯皮尔曼+0.403(赚钱效应均值)是现行最强校准指标; 阈值参考: |ρ|>0.2 值得关注, >0.3 强')
