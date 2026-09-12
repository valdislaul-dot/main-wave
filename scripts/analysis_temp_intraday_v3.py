# -*- coding: utf-8 -*-
"""v3: 分批建仓模型 (贴近A实际: 边观察边买, 破了就停) + 宽松过滤对比
分批模型: 前N根m15, 每根收盘 >= 当时累计分时均线 -> 买1/N; 首次跌破 -> 停止建仓
          平均成本 = 已买入部分的均价 (完全可执行, 无前视)
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
    cum_pv = cum_v = 0.0
    vw = []
    for b in db:
        h, l, c, v = float(b[3]), float(b[4]), float(b[2]), float(b[5])
        cum_pv += (h + l + c) / 3 * v
        cum_v += v
        vw.append(cum_pv / cum_v if cum_v > 0 else None)

    def tranche(n):
        """边买边看: 每根bar收盘>=当时均线就买1/n, 破了停. 返回(均价, 买入根数)"""
        pv = v = 0.0
        bought = 0
        for i in range(min(n, len(db))):
            c = float(db[i][2])
            if vw[i] is None or c < vw[i]:
                break
            vol = 1.0 / n
            pv += c * vol
            v += vol
            bought += 1
        return (pv / v if v > 0 else None), bought

    pn, en = tranche(8)
    rows.append(dict(code=x['code'], T=x['T'], gap=x['gap'], exit=a_exit(p1),
                     open=float(p0['open']), prev_close=float(p0['close']) if False else None,
                     t8=pn, t8n=en,
                     low60=min(float(b[4]) for b in db[:4]),
                     close60=float(db[3][2]), open_px=float(p0['open'])))

sel = [r for r in rows if 4 <= r['gap'] <= 8]
print('样本: 全部 %d | gap4-8%% %d\n' % (len(rows), len(sel)))


def rep(lab, arr, key):
    a = [r for r in arr if r.get(key)]
    vs = [(r['exit'] - r[key]) / r[key] * 100 for r in a]
    if len(vs) < 15:
        print('  %-38s n=%d 不足' % (lab, len(vs)))
        return
    se = st.pstdev(vs) / (len(vs) ** 0.5)
    print('  %-38s n=%4d 均%+6.2f%% 胜率%3.0f%% t=%5.2f' % (
        lab, len(vs), st.mean(vs),
        sum(1 for v in vs if v > 0) / len(vs) * 100, st.mean(vs) / se))


print('=== 分批建仓 (8根=2小时观察窗, 破了停) ===')
rep('开盘价买 (对照)', sel, 'open_px')
rep('分批建仓均价 (gap4-8%)', sel, 't8')
rep('同上 (全池)', rows, 't8')

print('\n=== 宽松过滤对比 (10:30收盘价成交) ===')
for r in sel:
    r['F_0line'] = r['low60'] >= r['open_px'] * 0.98      # 前1小时没跌破开盘-2%
    r['F_open'] = r['close60'] >= r['open_px']            # 10:30价 >= 开盘价
    r['F_prev'] = r['close60'] >= r['open_px'] * 1.0      # 同上
rep('不过滤, 10:30买', sel, 'close60')
rep('前1小时最低于开盘-2%内 -> 10:30买', [r for r in sel if r['F_0line']], 'close60')
rep('10:30价>=开盘价 -> 10:30买', [r for r in sel if r['F_open']], 'close60')

print('\n=== 通过率 ===')
for k, lab in (('F_0line', '前1小时跌幅<2%'), ('F_open', '10:30价>=开盘')):
    p = sum(1 for r in sel if r[k])
    print('  %-24s %d/%d = %.0f%%' % (lab, p, len(sel), p / len(sel) * 100))
p8 = sum(1 for r in sel if r['t8'])
print('  %-24s %d/%d = %.0f%%' % ('分批建仓有成交', p8, len(sel), p8 / len(sel) * 100))
json.dump(rows, open('data/_intraday_v3.json', 'w', encoding='utf-8'), ensure_ascii=False)
