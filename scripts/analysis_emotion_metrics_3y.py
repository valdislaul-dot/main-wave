"""
情绪指标 3年K线重建验证 v2 (2026-08-31)
核心问题: 晋级率/连板溢价/情绪分 对「次日买入期望」的预测力, 能否补强温度开关?
目标口径: 次日买入期望 = T日竞价4-8%窗买入T-1涨停股, T+1收盘相对T开盘的均值
          (与定稿「赚钱效应斯皮尔曼+0.403最强」同一目标口径)
局限: 炸板率K线不可算(官方API炸板池可补); ST/5%板被9.5阈值排除; 无池级题材/封单。
"""
import json, os, sys
from statistics import mean, median
from scipy.stats import spearmanr

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KL_DIR = os.path.join(BASE, 'data', 'kline_data')
START = '2023-08-31'
END = '2026-08-31'

def zt_pct(bar, prev_close):
    pc = bar.get('pct_change')
    if pc is None and prev_close and bar.get('close'):
        pc = (bar['close'] - prev_close) / prev_close * 100
    if pc is None or not (9.5 <= pc <= 31):
        return None
    if bar.get('high') and bar.get('close') and bar['close'] < bar['high'] * 0.999:
        return None
    return pc

# ── pass 1: 涨停日重建 ──
day_zt = {}      # date -> {code: streak}
day_pct = {}     # date -> {code: 当日涨幅}
files = [f for f in os.listdir(KL_DIR) if f.endswith('.json')]
for fi, fn in enumerate(files):
    code = fn[:-5]
    try:
        with open(os.path.join(KL_DIR, fn), encoding='utf-8') as f:
            raw = json.load(f)
        kl = raw.get('data', raw) if isinstance(raw, dict) else raw
    except Exception:
        continue
    streak = 0
    for i, bar in enumerate(kl):
        d = bar.get('date', '')
        if not (START <= d <= END):
            continue
        prev_close = kl[i-1].get('close') if i > 0 else None
        pc = zt_pct(bar, prev_close)
        if bar.get('close') and prev_close:
            ret = pc if pc is not None else (bar['close'] - prev_close) / prev_close * 100
            day_pct.setdefault(d, {})[code] = ret
        if pc is not None:
            streak += 1
            day_zt.setdefault(d, {})[code] = streak
        else:
            streak = 0
    if fi % 800 == 0:
        print(f'  pass1 {fi}/{len(files)}', file=sys.stderr)

dates = sorted(day_zt)
print(f'涨停日: {len(dates)} ({dates[0]} ~ {dates[-1]})', file=sys.stderr)
date_idx = {d: i for i, d in enumerate(dates)}

# ── pass 2: 每个涨停日的 次日开盘gap + 次次日收盘收益 (买入口径) ──
zt_codes = set()
for d in dates:
    zt_codes |= set(day_zt[d])
day_gap = {}      # 买入日 -> {code: 竞价gap%}
day_buyout = {}   # 买入日 -> {code: T+1收盘 vs T开盘%}
for fi, code in enumerate(zt_codes):
    try:
        with open(os.path.join(KL_DIR, f'{code}.json'), encoding='utf-8') as f:
            raw = json.load(f)
        kl = raw.get('data', raw) if isinstance(raw, dict) else raw
    except Exception:
        continue
    idx = {b.get('date'): i for i, b in enumerate(kl)}
    for d in dates:
        if code not in day_zt.get(d, {}):
            continue
        di = date_idx[d]
        # 买入日 = 涨停次日
        if di + 1 >= len(dates):
            continue
        buy_d = dates[di + 1]
        i1 = idx.get(buy_d)
        i2 = idx.get(dates[di + 2]) if di + 2 < len(dates) else None
        if i1 is None or i1 <= 0:
            continue
        bar1 = kl[i1]; bar0 = kl[i1 - 1]
        if not (bar0.get('close') and bar1.get('open')):
            continue
        gap = (bar1['open'] - bar0['close']) / bar0['close'] * 100
        day_gap.setdefault(buy_d, {})[code] = gap
        if i2 is not None and bar1.get('open'):
            ret = (kl[i2]['close'] - bar1['open']) / bar1['open'] * 100
            day_buyout.setdefault(buy_d, {})[code] = ret
    if fi % 800 == 0:
        print(f'  pass2 {fi}/{len(zt_codes)}', file=sys.stderr)

# ── 逐日指标 ──
rows = []
for d in dates:
    zt = day_zt[d]
    row = {'date': d, 'zt_n': len(zt), 'max_cons': max(zt.values())}
    if rows:
        p = rows[-1]
        prev_zt = day_zt[p['date']]
        prev_pct = day_pct.get(d, {})
        buckets = {1: [], 2: [], 3: []}
        for c, b in prev_zt.items():
            buckets[1 if b == 1 else (2 if b == 2 else 3)].append(c in zt)
        row['promo1'] = sum(buckets[1]) / len(buckets[1]) if buckets[1] else None
        row['promo2'] = sum(buckets[2]) / len(buckets[2]) if buckets[2] else None
        row['promo3'] = sum(buckets[3]) / len(buckets[3]) if buckets[3] else None
        allv = buckets[1] + buckets[2] + buckets[3]
        row['promo_all'] = sum(allv) / len(allv) if allv else None
        hi = [prev_pct.get(c) for c, b in prev_zt.items() if b >= 2]
        hi = [r for r in hi if r is not None]
        row['premium'] = mean(hi) if hi else None
        rets = [prev_pct.get(c) for c in prev_zt]
        rets = [r for r in rets if r is not None]
        if rets:
            row['me_mean'] = mean(rets)
            row['me_median'] = median(rets)
            row['me_pos'] = sum(1 for r in rets if r > 0) / len(rets)
            row['me_again'] = sum(1 for c in prev_zt if c in zt) / len(rets)
    # 池均gap(竞价二次确认口径) 与 买入期望(4-8%窗)
    gaps = day_gap.get(d, {})
    if gaps:
        row['pool_gap'] = mean(gaps.values())
        outs = [day_buyout.get(d, {}).get(c) for c, g in gaps.items() if 4.0 <= g <= 8.0]
        outs = [r for r in outs if r is not None]
        row['buy_exp'] = mean(outs) if len(outs) >= 3 else None
        row['buy_n'] = len(outs)
    rows.append(row)

# ── 情绪分 (2因子: zt_n + max_cons, 10日窗minmax) ──
def mm(vals):
    lo, hi = min(vals), max(vals)
    return [0.5] * len(vals) if hi == lo else [(v - lo) / (hi - lo) for v in vals]

for i, r in enumerate(rows):
    if i < 9:
        r['emotion'] = None
        continue
    win = rows[i-9:i+1]
    a = mm([float(x['zt_n']) for x in win])
    b = mm([float(x['max_cons']) for x in win])
    r['emotion'] = (a[-1] + b[-1]) / 2

# ── 斯皮尔曼: 指标(t) vs 次日(t+1) 买入期望 / 赚钱效应 ──
indicators = ['zt_n', 'max_cons', 'promo_all', 'promo1', 'promo2', 'promo3',
              'premium', 'me_mean', 'me_median', 'me_pos', 'me_again', 'emotion', 'pool_gap']
targets = [('次日买入期望', 'buy_exp'), ('次日赚钱效应均值', 'me_mean'),
           ('次日涨停家数', 'zt_n'), ('次日最高板', 'max_cons')]
print()
print('=' * 92)
print('  斯皮尔曼相关: 指标(t) vs 次日(t+1) — 3年K线重建 (~726交易日)')
print('=' * 92)
print(f'{"指标":<14}' + ''.join(f'{t[0]:>15}' for t in targets) + f'{"样本":>7}')
for ind in indicators:
    line = f'{ind:<16}'
    n = 0
    for _, tgt in targets:
        xs, ys = [], []
        for i, r in enumerate(rows[:-1]):
            if r.get(ind) is None or rows[i+1].get(tgt) is None:
                continue
            xs.append(r[ind]); ys.append(rows[i+1][tgt])
        if len(xs) >= 30:
            rho, _ = spearmanr(xs, ys)
            line += f'{rho:>+15.2f}'
            n = max(n, len(xs))
        else:
            line += f'{"n/a":>15}'
    line += f'{n:>7}'
    print(line)
print()
print('注: 定稿口径中 赚钱效应(均值)对次日买入期望斯皮尔曼+0.403 为最强基准;')
print('    K线重建口径与实盘池略有差异, 看相对强弱, 不看绝对值。')
