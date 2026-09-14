# -*- coding: utf-8 -*-
"""干净口径: 买入日(D+1)封板率 + 收益 — A时代 vs 我方时代
数据: D<=08-19 用本地K线(搜狐历史快照, 无幸存者偏差); D>=08-20 用补拉缓存(腾讯qfq)
"""
import json, os, sys, io, statistics as st
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE = json.load(open('data/_regime_klines_aug.json', encoding='utf-8'))
_k = {}
def kl(code):
    if code in _k: return _k[code]
    p = f'data/kline_data/{code}.json'
    out = None
    if os.path.exists(p):
        try: raw = json.load(open(p, encoding='utf-8'))
        except UnicodeDecodeError: raw = json.load(open(p, encoding='gbk'))
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        out = {b['date']: b for b in rows if b.get('date')}
    _k[code] = out
    return out

def aug(code):
    rows = CACHE.get(code) or []
    return {b['date']: b for b in rows if b.get('date')}

def rd(p):
    try: return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError: return json.load(open(p, encoding='gbk'))

def load_pools():
    pools = {}
    for f in sorted(os.listdir('data/zt_pool_history_ths')):
        if f.endswith('.json'):
            d = f[:-5]; d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
            data = rd('data/zt_pool_history_ths/' + f)
            rows = data if isinstance(data, list) else data.get('stocks', [])
            pools[d] = {str(x.get('code','')).zfill(6): x for x in rows if x.get('code')}
    for f in sorted(os.listdir('data/zt_pool')):
        if f.endswith('.json') and f != 'stock_index.json':
            d = f[:-5]; d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
            data = rd('data/zt_pool/' + f)
            rows = data if isinstance(data, list) else data.get('stocks', [])
            pools[d] = {str(x.get('code','')).zfill(6): x for x in rows if x.get('code')}
    return pools

pools = load_pools()
days = sorted(d for d in pools if '2026-03-01' <= d <= '2026-09-11')
print(f'池 {len(days)} 天 {days[0]}~{days[-1]}')

rows = []
for i, d in enumerate(days[:-2]):
    d1 = days[i+1]
    use_aug = d >= '2026-08-18'   # 该段起本地K线不可信
    for c, prow in pools[d].items():
        if use_aug:
            k0 = aug(c).get(d); k1 = aug(c).get(d1)
        else:
            k0 = kl(c).get(d) if kl(c) else None
            k1 = kl(c).get(d1) if kl(c) else None
        if not k0 or not k1: continue
        pc, o1, c1 = k0.get('close'), k1.get('open'), k1.get('close')
        if not pc or not o1 or not c1: continue
        gap = (o1 - pc) / pc * 100
        rows.append(dict(date=d, code=c, gap=gap,
                         seal=1 if (k1.get('pct_change') or 0) >= 9.8 else 0,
                         oc=(c1 - o1) / o1 * 100,
                         board=int(prow.get('limit_days', 1) or 1)))
print(f'样本 {len(rows)} 池股次')

def seg(name, sel):
    rs = [r for r in rows if sel(r)]
    if len(rs) < 10:
        print(f'  {name}: n={len(rs)} 样本不足'); return
    seal = [r for r in rs if r['seal']]
    print(f'  {name:22s} n={len(rs):5d} | 封板率 {len(seal)/len(rs)*100:5.1f}% | '
          f'开盘买入→收盘 {st.mean([r["oc"] for r in rs]):+6.2f}% | '
          f'封板笔均 {st.mean([r["oc"] for r in seal]):+6.2f}%' if seal else '')

print('\n=== 买入窗 gap 4-8% ===')
for lo, hi, lab in ((('2026-03-01','2026-07-31'), None, 'A时代 2026-03~07'),
                    (('2026-08-01','2026-09-11'), None, '我方时代 2026-08~09')):
    seg(lab, lambda r, a=lo: a[0] <= r['date'] <= a[1] and 4 <= r['gap'] <= 8)

print('\n=== 全部池股 ===')
seg('A时代 2026-03~07', lambda r: '2026-03-01' <= r['date'] <= '2026-07-31')
seg('我方时代 2026-08~09', lambda r: '2026-08-01' <= r['date'] <= '2026-09-11')

print('\n=== 按月 (gap4-8%) ===')
bym = defaultdict(list)
for r in rows:
    if 4 <= r['gap'] <= 8: bym[r['date'][:7]].append(r)
print('%-9s %6s %8s %10s %10s' % ('月份','样本','封板率','开→收','封板笔均'))
for m in sorted(bym):
    a = bym[m]; s = [r for r in a if r['seal']]
    print('%-9s %6d %7.1f%% %+9.2f%% %+9.2f%%' % (
        m, len(a), len(s)/len(a)*100, st.mean([r['oc'] for r in a]),
        st.mean([r['oc'] for r in s]) if s else 0))
json.dump(rows, open('data/_sealrate_rows.json','w',encoding='utf-8'), ensure_ascii=False)
