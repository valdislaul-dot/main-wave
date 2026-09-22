"""gap窗口分档实证 (2026-09-22)

回答: 现行硬边界 [4%, 8%] 是否最优? 下移到 [3,8] / [2,8] / [0,8] 会不会更好?
样本: data/auction/*.json (40个交易日竞价池) join data/daily_close (全票OHLC, 已回填)
口径: T日开盘买入 → T日收盘 / T+1日收盘。竞价池=昨涨停股, 即"昨涨停票次日表现"。
"""
import json, os, re, glob, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUC = os.path.join(BASE, 'data', 'auction')
DC = os.path.join(BASE, 'data', 'daily_close')


def load(fp, d=None):
    try:
        with open(fp, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return d


days = {}
for f in sorted(glob.glob(os.path.join(AUC, '*.json'))):
    m = re.search(r'(\d{4}-\d{2}-\d{2})\.json$', f)
    if not m:
        continue
    a = load(f)
    if not a:
        continue
    rows = a.get('stocks', a) if isinstance(a, dict) else a
    if isinstance(rows, dict):
        rows = list(rows.values())
    d = {}
    for r in (rows or []):
        if isinstance(r, dict) and r.get('code'):
            d[str(r['code']).zfill(6)] = r
    if d:
        days[m.group(1)] = d

snaps = {}
for d in sorted(days):
    s = load(os.path.join(DC, d, 'daily_data.json'))
    if s:
        snaps[d] = s

dates = sorted(snaps)
print(f'竞价池 {len(days)} 天 | 收盘快照 {len(snaps)} 天 ({dates[0]} ~ {dates[-1]})')

recs = []
for i, d in enumerate(dates):
    nxt = dates[i + 1] if i + 1 < len(dates) else None
    S = snaps[d]
    N = snaps.get(nxt) if nxt else None
    for code, r in days.get(d, {}).items():
        cur = S.get(code)
        gap = r.get('gap_pct')
        if not cur or not cur.get('open') or gap is None:
            continue
        e = cur['open']
        day = (cur['close'] / e - 1) * 100 if cur.get('close') else None
        nxt_r = None
        if N and N.get(code) and N[code].get('close'):
            nxt_r = (N[code]['close'] / e - 1) * 100
        # 封板 = 收盘触及今日涨停价 (auction.limit_up = prev_close×1.1, 已核实)
        lim = r.get('limit_up')
        lu = bool(lim and cur.get('close') and cur['close'] >= lim - 0.005)
        # 近似"可买"过滤: 排除一字板 / 300·688 / 4板以上
        ok = (not r.get('one_line')) and not code.startswith(('300', '301', '688')) \
            and int(r.get('limit_days') or 1) <= 3
        recs.append({'d': d, 'code': code, 'name': r.get('name', ''), 'gap': gap,
                     'score': r.get('score'), 'buyable': bool(r.get('buyable')),
                     'ok': ok, 'lu': lu, 'day': day, 'next': nxt_r})

print(f'样本 {len(recs)} 票次 | 当日收盘 {sum(1 for x in recs if x["day"] is not None)}'
      f' | 次日收盘 {sum(1 for x in recs if x["next"] is not None)}')

BANDS = [(-11, -9.5), (-9.5, -8), (-8, -6), (-6, -4), (-4, -2), (-2, 0),
         (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (9, 11)]


def band_table(rows, title):
    print(f'\n=== {title} ===')
    print(f'{"gap档":>9} {"n":>5} {"封板率":>7} {"当日均":>8} {"次日均":>8} {"当日胜":>7}')
    for lo, hi in BANDS:
        g = [x for x in rows if lo <= x['gap'] < hi]
        if not g:
            continue
        lu = sum(1 for x in g if x['lu']) / len(g) * 100
        dd = [x['day'] for x in g if x['day'] is not None]
        nn = [x['next'] for x in g if x['next'] is not None]
        wr = sum(1 for v in dd if v > 0) / len(dd) * 100 if dd else 0
        print(f'{lo:>4}~{hi:<4} {len(g):>5} {lu:>6.1f}% {sum(dd)/len(dd) if dd else 0:>7.2f}%'
              f' {sum(nn)/len(nn) if nn else 0:>7.2f}% {wr:>6.1f}%')


band_table(recs, 'gap 分档 (全竞价池) 开盘买→当日收 / →次日收')
band_table([x for x in recs if x['ok']], 'gap 分档 (排除一字/300·688/4板+, ≈可买域)')


def win(rows, lo, hi, key):
    g = [x for x in rows if lo <= x['gap'] <= hi and x.get(key) is not None]
    if not g:
        return None
    v = [x[key] for x in g]
    return len(g), sum(v) / len(v), sum(1 for a in v if a > 0) / len(v) * 100, \
        sum(1 for x in g if x['lu']) / len(g) * 100


WINDOWS = [(4, 8), (3, 8), (2, 8), (1, 8), (0, 8), (3, 9), (4, 9), (5, 8), (4, 6), (6, 8)]
okr = [x for x in recs if x['ok']]
for tag, rows in [('全池', recs), ('≈可买域', okr)]:
    print(f'\n=== 窗口对比 ({tag}, 开盘买→当日收) ===')
    print(f'{"窗口":>12} {"n":>5} {"均收益":>8} {"胜率":>7} {"封板率":>7}')
    for lo, hi in WINDOWS:
        w = win(rows, lo, hi, 'day')
        if w:
            print(f'[{lo}%,{hi}%]'.rjust(12) + f' {w[0]:>5} {w[1]:>7.2f}% {w[2]:>6.1f}% {w[3]:>6.1f}%')

print('\n=== 窗口对比 (开盘买→次日收, 含隔夜) ===')
for tag, rows in [('全池', recs), ('≈可买域', okr)]:
    for lo, hi in [(4, 8), (3, 8), (2, 8), (0, 8), (-4, 8)]:
        w = win(rows, lo, hi, 'next')
        if w:
            print(f'  {tag} [{lo}%,{hi}%]'.ljust(20)
                  + f' n={w[0]:>4} 均{w[1]:>6.2f}% 胜{w[2]:>5.1f}% 封板{w[3]:>5.1f}%')

print('\n=== 每日窗口内票数 (能否凑齐 Top3) ===')
for label, (lo, hi) in [('[4,8]', (4, 8)), ('[3,8]', (3, 8)), ('[0,8]', (0, 8))]:
    cnt = {}
    for x in recs:
        if lo <= x['gap'] <= hi:
            cnt[x['d']] = cnt.get(x['d'], 0) + 1
    vals = [cnt.get(d, 0) for d in dates]
    med = sorted(vals)[len(vals) // 2]
    print(f'  {label}: <3只的天数 {sum(1 for v in vals if v < 3)}/{len(vals)}'
          f' | 中位 {med} | 最小 {min(vals)} | 最大 {max(vals)}')
print('  逐日 [4,8] 只数: ' + ', '.join(
    f'{d[5:]}:{sum(1 for x in recs if x["d"] == d and 4 <= x["gap"] <= 8)}' for d in dates))

sc = [x for x in recs if x['score'] is not None and x['day'] is not None]
if sc:
    sc.sort(key=lambda x: -x['score'])
    print('\n=== 评分分档 (仅当日收有值) ===')
    for i in range(0, min(len(sc), 400), 50):
        g = sc[i:i + 50]
        if not g:
            continue
        v = [x['day'] for x in g]
        print(f'  第{i+1:>3}-{i+len(g):<3}名 分{sc[i]["score"]:>6.1f}~{g[-1]["score"]:>6.1f}'
              f' n={len(g):>3} 均{sum(v)/len(v):>6.2f}% 胜{sum(1 for a in v if a>0)/len(v)*100:>5.1f}%')

# 真实口径: 每个窗口每日只买评分 Top3 (窗口均值 ≠ 只买Top3, 排序压力随候选数放大)
print('\n=== 每窗口 每日评分Top3 (≈可买域, 真实买入口径) ===')
ok_pool = [x for x in recs if x['ok'] and x['score'] is not None]
print(f'{"窗口":>10} {"有票日":>7} {"笔数":>5} {"当日均":>8} {"当日胜":>7}'
      f' {"次日均":>8} {"次日胜":>7} {"封板率":>7}')
for lo, hi in [(-4, 8), (0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (4, 6), (6, 8)]:
    byd = {}
    for x in ok_pool:
        if lo <= x['gap'] <= hi:
            byd.setdefault(x['d'], []).append(x)
    picks = []
    for d, rows in byd.items():
        rows.sort(key=lambda x: (-x['score'], x['code']))
        picks += rows[:3]
    dd = [x['day'] for x in picks if x['day'] is not None]
    nn = [x['next'] for x in picks if x['next'] is not None]
    if not dd:
        continue
    f = lambda v: f'{sum(v)/len(v):>6.2f}% {sum(1 for a in v if a>0)/len(v)*100:>5.1f}%'
    lu = sum(1 for x in picks if x['lu']) / len(picks) * 100
    print(f'[{lo}%,{hi}%]'.rjust(10) + f' {len(byd):>5}/40 {len(picks):>5}'
          f' {f(dd)} {f(nn) if nn else "     -":>14} {lu:>6.1f}%')

mid = len(dates) // 2
print(f'\n=== 跨期检验 (训练段 {dates[0]}~{dates[mid-1]} / 检验段 {dates[mid]}~{dates[-1]}) ===')
print(f'{"窗口":>10} {"训练段当日":>11} {"检验段当日":>11} {"训练段次日":>11} {"检验段次日":>11}')
for lo, hi in [(4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]:
    res = []
    for seg in (dates[:mid], dates[mid:]):
        byd = {}
        for x in ok_pool:
            if lo <= x['gap'] <= hi and x['d'] in seg:
                byd.setdefault(x['d'], []).append(x)
        picks = []
        for d, rows in byd.items():
            rows.sort(key=lambda x: (-x['score'], x['code']))
            picks += rows[:3]
        dd = [x['day'] for x in picks if x['day'] is not None]
        nn = [x['next'] for x in picks if x['next'] is not None]
        res.append((sum(dd) / len(dd) if dd else 0, sum(nn) / len(nn) if nn else 0))
    print(f'[{lo}%,{hi}%]'.rjust(10)
          + f' {res[0][0]:>9.2f}% {res[1][0]:>9.2f}% {res[0][1]:>9.2f}% {res[1][1]:>9.2f}%')

print('\n=== 候选数与排序压力 ===')
for lo, hi in [(4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]:
    byd = [len([x for x in ok_pool if x['d'] == d and lo <= x['gap'] <= hi]) for d in dates]
    med = sorted(byd)[len(byd) // 2]
    print(f'  [{lo}%,{hi}%] 每日候选 中位{med:>3} 最大{max(byd):>3}'
          f' | 需从 {med} 只中选出 Top3 (选择率 {3/med*100 if med else 0:.0f}%)')
