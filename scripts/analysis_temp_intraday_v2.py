# -*- coding: utf-8 -*-
"""盘中防线实测 v2 — 消除前视偏差
每个入场价只用"当时已知"的信息:
  E0 开盘价          : 9:30 就能成交
  E5 前30分收盘价     : 10:00 观察完再买
  E6 前60分收盘价     : 10:30 观察完再买
  E7 前30分VWAP      : 把买单摊在前30分钟(等价于按均价成交)
  E8 前60分VWAP      : 摊在前60分钟
过滤同样只用当时信息, 且成交价必须是观察窗结束后的价格:
  F30 = 前30分钟收盘价全部 >= 累计分时均线  -> 10:00 按当时价买入
  F60 = 同理在 10:30
"""
import json, os, sys, io, statistics as st
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
M15 = 'data/m15_live'


def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))


CACHE = json.load(open('data/_regime_klines_aug.json', encoding='utf-8'))
_loc = {}


def kl(c):
    if c in _loc:
        return _loc[c]
    p = 'data/kline_data/' + c + '.json'
    m = None
    if os.path.exists(p):
        raw = rd(p)
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        m = {b['date']: b for b in rows if b.get('date')}
    _loc[c] = m
    return m


def bar(c, d):
    m = kl(c)
    if m and d in m:
        return m[d]
    for r in (CACHE.get(c) or []):
        if r.get('date') == d:
            return r
    return None


pools = {}
for base in ('data/zt_pool_history_ths', 'data/zt_pool'):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json') or f == 'stock_index.json':
            continue
        ymd = f[:-5]
        d = ymd[:4] + '-' + ymd[4:6] + '-' + ymd[6:8]
        data = rd(os.path.join(base, f))
        rows = data if isinstance(data, list) else data.get('stocks', [])
        pools[d] = {str(x.get('code', '')).zfill(6): x for x in rows if x.get('code')}
DAYS = sorted(pools)


def nxt(d, k=1):
    nx = [x for x in DAYS if x > d]
    return nx[k - 1] if len(nx) >= k else None


auc = {}
for f in sorted(os.listdir('data/auction')):
    if not f.endswith('.json') or '_' in f:
        continue
    dd = json.load(open('data/auction/' + f, encoding='utf-8'))
    auc[f[:-5]] = {str(s.get('code', '')).zfill(6): s for s in dd.get('stocks', [])}

START, END = '2026-08-17', '2026-09-10'
cands = []
for T in DAYS:
    if not (START <= T <= END) or T not in auc:
        continue
    prev = [x for x in DAYS if x < T]
    if not prev:
        continue
    T1 = nxt(T)
    if not T1:
        continue
    for c in pools[prev[-1]]:
        if c.startswith(('300', '301', '688', '8', '9')):
            continue
        s = auc[T].get(c)
        if not s:
            continue
        g = s.get('gap_pct')
        if g is None and s.get('open') and s.get('prev_close'):
            g = (s['open'] - s['prev_close']) / s['prev_close'] * 100
        if g is None:
            continue
        cands.append(dict(T=T, T1=T1, code=c, gap=float(g)))


def a_exit(p1):
    lu = (p1.get('pct_change') or 0) >= 9.8
    if lu:
        return p1['close']
    return 0.7 * (p1['high'] + p1['open']) / 2 + 0.3 * p1['close']


rows = []
for x in cands:
    f = os.path.join(M15, x['code'] + '.json')
    if not os.path.exists(f):
        continue
    bars = json.load(open(f, encoding='utf-8'))
    db = [b for b in bars if str(b[0]).startswith(x['T'].replace('-', ''))]
    if len(db) < 16:
        continue
    p0 = bar(x['code'], x['T'])
    p1 = bar(x['code'], x['T1'])
    if not p0 or not p1:
        continue
    # 累计分时均线 (典型价加权)
    cum_pv = cum_v = 0.0
    vw = []
    for b in db:
        h, l, c, v = float(b[3]), float(b[4]), float(b[2]), float(b[5])
        cum_pv += (h + l + c) / 3 * v
        cum_v += v
        vw.append(cum_pv / cum_v if cum_v > 0 else None)
    # 摊单均价 (前30/60分钟的成交量加权)
    def vwap_n(n):
        pv = v = 0.0
        for b in db[:n]:
            h, l, c, vol = float(b[3]), float(b[4]), float(b[2]), float(b[5])
            pv += (h + l + c) / 3 * vol
            v += vol
        return pv / v if v > 0 else None
    e = {
        'E0_开盘': float(p0['open']),
        'E5_前30分收盘': float(db[1][2]),
        'E6_前60分收盘': float(db[3][2]),
        'E7_前30分均价': vwap_n(2),
        'E8_前60分均价': vwap_n(4),
    }
    # 过滤: 观察窗内每根bar收盘 >= 当时的累计均线
    f30 = all(float(db[i][2]) >= vw[i] for i in range(2) if vw[i])
    f60 = all(float(db[i][2]) >= vw[i] for i in range(4) if vw[i])
    rows.append(dict(code=x['code'], T=x['T'], gap=x['gap'], e=e, f30=f30, f60=f60,
                     exit=a_exit(p1)))

sel = [r for r in rows if 4 <= r['gap'] <= 8]
print('样本: 全部 %d 票次 | gap4-8%% %d 票次\n' % (len(rows), len(sel)))


def rep(lab, arr, ekey, filt=None):
    a = [r for r in arr if (filt is None or r[filt]) and r['e'].get(ekey)]
    vs = [(r['exit'] - r['e'][ekey]) / r['e'][ekey] * 100 for r in a]
    if len(vs) < 15:
        print('  %-36s n=%d 样本不足' % (lab, len(vs)))
        return None
    se = st.pstdev(vs) / (len(vs) ** 0.5)
    print('  %-36s n=%4d 均%+6.2f%% 胜率%3.0f%% t=%5.2f' % (
        lab, len(vs), st.mean(vs),
        sum(1 for v in vs if v > 0) / len(vs) * 100, st.mean(vs) / se))
    return st.mean(vs)


print('=== (1) 无过滤, 不同入场价 (全部可执行) ===')
for k in ('E0_开盘', 'E5_前30分收盘', 'E6_前60分收盘', 'E7_前30分均价', 'E8_前60分均价'):
    rep(k, sel, k)

print('\n=== (2) 均线过滤 + 观察结束后成交 ===')
rep('无过滤, 开盘价买', sel, 'E0_开盘')
rep('前30分站均线 -> 10:00买', sel, 'E5_前30分收盘', 'f30')
rep('前60分站均线 -> 10:30买', sel, 'E6_前60分收盘', 'f60')
rep('前30分站均线 -> 按前30分均价', sel, 'E7_前30分均价', 'f30')
rep('前60分站均线 -> 按前60分均价', sel, 'E8_前60分均价', 'f60')

print('\n=== (3) 对照: 被过滤掉的票 (开盘价买会怎样) ===')
for r in sel:
    r['__not30'] = not r['f30']
    r['__not60'] = not r['f60']
rep('前30分站不上均线 (开盘价买)', sel, 'E0_开盘', '__not30')
rep('前60分站不上均线 (开盘价买)', sel, 'E0_开盘', '__not60')

print('\n=== (4) 全池(不限gap) 同口径 ===')
allr = rows
rep('无过滤, 开盘价买', allr, 'E0_开盘')
rep('前60分站均线 -> 10:30买', allr, 'E6_前60分收盘', 'f60')
json.dump(rows, open('data/_intraday_v2.json', 'w', encoding='utf-8'), ensure_ascii=False)
