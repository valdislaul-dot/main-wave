# -*- coding: utf-8 -*-
"""精确口径: 买入日(D+1)封板率 = |D池 ∩ (D+1)池| / |D池|
池文件=当日全市场涨停名单 → 无K线缺失/幸存者偏差问题, 全期可比
"""
import json, os, sys, io, statistics as st
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def rd(p):
    try: return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError: return json.load(open(p, encoding='gbk'))

pools = {}
for base in ('data/zt_pool_history_ths', 'data/zt_pool'):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json') or f == 'stock_index.json': continue
        ymd = f[:-5]; d = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
        data = rd(os.path.join(base, f))
        rows = data if isinstance(data, list) else data.get('stocks', [])
        pools[d] = {str(x.get('code', '')).zfill(6) for x in rows if x.get('code')}

days = sorted(d for d in pools if '2025-06-01' <= d <= '2026-09-11')
print(f'池 {len(days)} 天  {days[0]} ~ {days[-1]}')

daily = []
for i, d in enumerate(days[:-1]):
    d1 = days[i + 1]
    cur, nxt = pools[d], pools[d1]
    if len(cur) < 10: continue
    cont = cur & nxt
    daily.append(dict(date=d, n=len(cur), n1=len(nxt), cont=len(cont),
                      rate=len(cont) / len(cur) * 100))

bym = defaultdict(list)
for r in daily: bym[r['date'][:7]].append(r)
print('\n%-9s %6s %8s %9s %10s %10s' % ('月份','天数','D池均','D+1池均','晋级率','晋级/池比'))
for m in sorted(bym):
    a = bym[m]
    print('%-9s %6d %8.1f %9.1f %9.1f%% %9.2f' % (
        m, len(a), st.mean([r['n'] for r in a]), st.mean([r['n1'] for r in a]),
        st.mean([r['rate'] for r in a]), st.mean([r['n1'] for r in a]) / st.mean([r['n'] for r in a])))

print('\n=== 时代汇总 ===')
for lab, lo, hi in (('A时代 2026-03~07','2026-03-01','2026-07-31'),
                    ('我方 2026-08~09','2026-08-01','2026-09-11'),
                    ('2025-06~2026-02(参照)','2025-06-01','2026-02-28')):
    a = [r for r in daily if lo <= r['date'] <= hi]
    if not a: continue
    print(f'  {lab}: {len(a)}天 | D池均 {st.mean([r["n"] for r in a]):5.1f}只 | '
          f'次日池均 {st.mean([r["n1"] for r in a]):5.1f}只 | 晋级率 {st.mean([r["rate"] for r in a]):5.1f}%')

json.dump(daily, open('data/_pool_seal_daily.json', 'w', encoding='utf-8'), ensure_ascii=False)
