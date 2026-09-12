# -*- coding: utf-8 -*-
"""5分钟粒度: A式入场(竞价后即买) vs 短观察窗, 出场统一A式
样本: 东财klt=5, 约31个交易日 (07-31~09-11)
全部可执行: 任何入场价只用该时点之前的信息
"""
import json, os, sys, io, statistics as st
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
M5 = 'data/m5_live'


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

START, END = '2026-08-01', '2026-09-11'
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
    f = os.path.join(M5, x['code'] + '.json')
    if not os.path.exists(f):
        continue
    try:
        bars = json.load(open(f, encoding='utf-8'))
    except Exception:
        continue
    ymd = x['T'].replace('-', '')
    db = [b for b in bars if str(b[0]).replace('-', '')[:8].startswith(ymd)]
    if len(db) < 40:
        continue
    p0 = bar(x['code'], x['T'])
    p1 = bar(x['code'], x['T1'])
    if not p0 or not p1:
        continue
    # klines: "2026-07-31 09:35,开,收,高,低,量,额,涨幅"
    def fld(b, i):
        p = str(b).split(',')
        return float(p[i])
    o0 = fld(db[0], 1)          # 9:35 开盘 = 当日开盘价
    c1 = fld(db[0], 2)          # 9:35 收盘
    c3 = fld(db[2], 2)          # 9:45 收盘
    c6 = fld(db[5], 2)          # 10:05 收盘
    lo1 = fld(db[0], 4)
    # 累计VWAP(用收盘价*量 近似)
    pv = v = 0.0
    vw = []
    for b in db:
        cl = fld(b, 2); vol = fld(b, 5)
        pv += cl * vol; v += vol
        vw.append(pv / v if v > 0 else None)
    e = {
        'E0_开盘': o0,
        'E5_9:35': c1,
        'E15_9:45': c3,
        'E35_10:05': c6,
        'E0_首5分低': lo1,
    }
    f5 = c1 >= o0                       # 首5分钟收盘不低于开盘
    f5v = c1 >= vw[0] if vw[0] else False
    f15v = all(fld(db[i], 2) >= vw[i] for i in range(3) if vw[i])
    rows.append(dict(code=x['code'], T=x['T'], gap=x['gap'], e=e, exit=a_exit(p1),
                     f5=f5, f5v=f5v, f15v=f15v))

print('可用样本 %d 票次 (窗口 %s~%s)' % (len(rows), START, END))
sel = [r for r in rows if 4 <= r['gap'] <= 8]
print('gap4-8%%: %d\n' % len(sel))

TRAIN = [r for r in sel if r['T'] <= '2026-08-31']
TEST = [r for r in sel if r['T'] >= '2026-09-01']


def rep(lab, arr, ekey, filt=None, show_t=False):
    a = [r for r in arr if (filt is None or r[filt]) and r['e'].get(ekey)]
    vs = [(r['exit'] - r['e'][ekey]) / r['e'][ekey] * 100 for r in a]
    if len(vs) < 12:
        return None
    se = st.pstdev(vs) / (len(vs) ** 0.5)
    t = st.mean(vs) / se if se > 0 else 0
    print('  %-34s n=%4d 均%+6.2f%% 胜率%3.0f%% t=%5.2f' % (
        lab, len(vs), st.mean(vs),
        sum(1 for v in vs if v > 0) / len(vs) * 100, t))
    return st.mean(vs)


print('=== A式入场 (竞价后即按开盘价买) + A式出场 ===')
rep('全部 gap4-8%', sel, 'E0_开盘')
print('  训练窗(08-01~08-31):')
rep('    开盘价买', TRAIN, 'E0_开盘')
print('  验证窗(09-01~09-11):')
rep('    开盘价买', TEST, 'E0_开盘')

print('\n=== 短观察窗入场 (可执行) ===')
for k, lab in (('E5_9:35', '等到9:35按当时价买'),
               ('E15_9:45', '等到9:45按当时价买'),
               ('E35_10:05', '等到10:05按当时价买')):
    rep(lab + ' [全]', sel, k)
    rep(lab + ' [训练]', TRAIN, k)
    rep(lab + ' [验证]', TEST, k)

print('\n=== 短过滤 (最贴近"盘中观察次数很少") ===')
rep('首5分收盘>=开盘 -> 9:35买', sel, 'E5_9:35', 'f5')
rep('首5分站上VWAP -> 9:35买', sel, 'E5_9:35', 'f5v')
rep('前15分全站VWAP -> 9:45买', sel, 'E15_9:45', 'f15v')
print('  --- 训练/验证 ---')
rep('首5分>=开盘 [训练]', TRAIN, 'E5_9:35', 'f5')
rep('首5分>=开盘 [验证]', TEST, 'E5_9:35', 'f5')

print('\n=== 被过滤的票 (按开盘价买会怎样) ===')
for r in sel:
    r['nf5'] = not r['f5']
    r['nf15v'] = not r['f15v']
rep('首5分跌破开盘 -> 开盘买', sel, 'E0_开盘', 'nf5')
rep('前15分未全站VWAP -> 开盘买', sel, 'E0_开盘', 'nf15v')

print('\n=== 通过率 ===')
for k, lab in (('f5', '首5分>=开盘'), ('f5v', '首5分站上VWAP'), ('f15v', '前15分全站VWAP')):
    p = sum(1 for r in sel if r[k])
    print('  %-20s %d/%d = %.0f%%' % (lab, p, len(sel), p / len(sel) * 100))
json.dump(rows, open('data/_m5_entry.json', 'w', encoding='utf-8'), ensure_ascii=False)
