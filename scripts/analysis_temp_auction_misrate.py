# -*- coding: utf-8 -*-
"""临时分析(任务4): 竞价信号误伤率 (2026-09-07)
- auction_state.json 46天竞价gap分布 → 每日池均gap近似
- 当日涨停数: zt_pool_history_ths(至08-19) + data/zt_pool/(07-24起)
- 检验: 池均gap≤-0.5%降档规则误伤率(当日转强比例) + 池均gap分档对当日涨停数/次日赚效的区分度
"""
import json, os, sys, re
sys.stdout.reconfigure(encoding='utf-8')

def pool_count(fn_dir, fn):
    p = os.path.join(fn_dir, fn)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return None
    if isinstance(d, list):
        return len(d)
    if isinstance(d, dict):
        for k in ('stocks', 'pool', 'data'):
            if isinstance(d.get(k), list):
                return len(d[k])
    return None

def parse_hd(hd):
    m = re.search(r'(\d+)板', str(hd))
    return int(m.group(1)) if m else 1

def pool_max_board(fn_dir, fn):
    p = os.path.join(fn_dir, fn)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return None
    lst = d if isinstance(d, list) else (d.get('stocks') or d.get('pool') or [])
    return max((parse_hd(x.get('high_days')) for x in lst), default=0)

# 当日涨停数合并源
def zt_count(date):
    fn = date + '.json'
    c = pool_count('data/zt_pool', fn)
    if c is None:
        c = pool_count('data/zt_pool_history_ths', fn)
    return c

def zt_maxb(date):
    fn = date + '.json'
    m = pool_max_board('data/zt_pool', fn)
    if not m:
        m = pool_max_board('data/zt_pool_history_ths', fn)
    return m

# 竞价gap分布 → 均gap近似
BUCKETS = [('<-3%', -4.0), ('-3-0%', -1.5), ('0-2%', 1.0), ('2-5%', 3.5), ('5-9%', 7.0), ('9%+', 10.0)]
def mean_gap(dist):
    tot, s = 0, 0.0
    for k, mid in BUCKETS:
        n = dist.get(k, 0)
        s += n * mid
        tot += n
    return s / tot if tot else None

with open('data/auction_state.json', encoding='utf-8') as f:
    auc = json.load(f)

rows = []
for h in auc['history']:
    d = h['date'].replace('-', '')
    mg = mean_gap(h.get('gap_distribution', {}))
    rows.append((d, h['total'], h.get('buyable'), mg, zt_count(d), zt_maxb(d)))

# 赚效(池日期口径): ME[date] = 该日池在次日表现
with open('data/money_effect_series.json', encoding='utf-8') as f:
    me = {x['date'].replace('-', ''): x['me'] for x in json.load(f)}

print(f"{'日期':<10}{'池均gap':>8}{'竞价涨停数':>8}{'buyable':>8}{'赚效(次)':>10}")
data = []
for d, tot, buy, mg, cnt, mb in rows:
    me_val = me.get(d)
    data.append((d, mg, cnt, mb, me_val))
    print(f'{d:<10}{mg if mg is None else f"{mg:+.2f}%":>8}{cnt if cnt else "-":>8}{buy if buy else "-":>8}{me_val if me_val is not None else "-":>10}')

# 1. 误伤率: 池均gap<=-0.5% → 当日涨停数>=60 的比例
print('\n=== 1. 降档规则(池均gap<=-0.5%)误伤率 ===')
triggered = [(d, mg, cnt) for d, mg, cnt, mb, me in data if mg is not None and mg <= -0.5 and cnt]
if triggered:
    for d, mg, cnt in triggered:
        tag = '★当日转强(>=60)' if cnt >= 60 else ('温(40-59)' if cnt >= 40 else '冷(<40)')
        print(f'  {d} 均gap{mg:+.2f}% → 当日涨停{cnt}只 {tag}')
    strong = sum(1 for _, _, c in triggered if c >= 60)
    cold = sum(1 for _, _, c in triggered if c < 40)
    print(f'  触发{len(triggered)}天: 转强{strong}天({strong/len(triggered):.0%}) 冷{cold}天({cold/len(triggered):.0%})')
else:
    print('  无触发日')

# 2. 池均gap分档 vs 当日涨停数/次日赚效
print('\n=== 2. 池均gap分档 区分度 ===')
def tier(mg):
    if mg is None: return None
    if mg < -1.0: return 'gap<-1%'
    if mg < 0: return 'gap -1~0%'
    if mg < 2: return 'gap 0~2%'
    if mg < 4: return 'gap 2~4%'
    return 'gap>=4%'
from collections import defaultdict
g = defaultdict(list)
for d, mg, cnt, mb, me in data:
    t = tier(mg)
    if t is None: continue
    if cnt: g[t].append(('cnt', cnt))
    if me is not None: g[t].append(('me', me))
for t in ['gap<-1%', 'gap -1~0%', 'gap 0~2%', 'gap 2~4%', 'gap>=4%']:
    v = g[t]
    cnts = [x for k, x in v if k == 'cnt']
    mes = [x for k, x in v if k == 'me']
    cs = f'涨停数均{sum(cnts)/len(cnts):.0f}(N={len(cnts)})' if cnts else '涨停数无数据'
    es = f'赚效均{sum(mes)/len(mes):+.2f}%(N={len(mes)})' if mes else '赚效无数据'
    print(f'  {t:<12} {cs:<24} {es}')

# 3. 池均gap与当日涨停数的相关性(斯皮尔曼)
def spearman(xs, ys):
    n = len(xs)
    if n < 3: return None, n
    rx = {v: i + 1 for i, v in enumerate(sorted(set(xs)))}
    ry = {v: i + 1 for i, v in enumerate(sorted(set(ys)))}
    import statistics
    xr = [rx[x] for x in xs]; yr = [ry[y] for y in ys]
    mx, my = sum(xr)/n, sum(yr)/n
    cov = sum((a-mx)*(b-my) for a, b in zip(xr, yr))
    sx = (sum((a-mx)**2 for a in xr)) ** .5
    sy = (sum((b-my)**2 for b in yr)) ** .5
    return cov/(sx*sy) if sx*sy else None, n
xs = [mg for d, mg, cnt, mb, me in data if mg is not None and cnt]
ys = [cnt for d, mg, cnt, mb, me in data if mg is not None and cnt]
r, n = spearman(xs, ys)
print(f'\n=== 3. 池均gap vs 当日涨停数 斯皮尔曼 ===')
print(f'  r={r:+.3f} (N={n})')
xs2 = [mg for d, mg, cnt, mb, me in data if mg is not None and me is not None]
ys2 = [me for d, mg, cnt, mb, me in data if mg is not None and me is not None]
r2, n2 = spearman(xs2, ys2)
print(f'  池均gap vs 次日赚效(当日池): r={r2:+.3f} (N={n2})')
