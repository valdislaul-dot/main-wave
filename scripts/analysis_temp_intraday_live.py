# -*- coding: utf-8 -*-
"""盘中防线实测 (实盘窗口): 腾讯m15(320根≈20交易日)覆盖 08-17~09-11
三种用法分开测:
  ① 入场价变体: 开盘 / 等N分钟低点 / 两笔均价   (A: 等低点买 or 加仓)
  ② 入场过滤: 前N分钟站不上分时均线 -> 不买
  ③ 组合
"""
import json, os, sys, io, time, urllib.request, statistics as st
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
M15 = 'data/m15_live'
os.makedirs(M15, exist_ok=True)


def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))


def fetch_m15(code):
    f = os.path.join(M15, code + '.json')
    if os.path.exists(f):
        try:
            return json.load(open(f, encoding='utf-8'))
        except Exception:
            pass
    pre = 'sh' if code.startswith(('5', '6', '9')) else 'sz'
    url = ('https://ifzq.gtimg.cn/appstock/app/kline/mkline?param='
           + pre + code + ',m15,,320&_var=result')
    req = urllib.request.Request(url, headers={'User-Agent': UA,
                                               'Referer': 'https://gu.qq.com/'})
    for _ in range(3):
        try:
            raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk')
            d = json.loads(raw.split('=', 1)[1].strip())
            bars = d.get('data', {}).get(pre + code, {}).get('m15', [])
            if bars:
                json.dump(bars, open(f, 'w', encoding='utf-8'))
                return bars
        except Exception:
            time.sleep(0.6)
    json.dump([], open(f, 'w', encoding='utf-8'))
    return []


def day_bars(bars, ymd):
    return [b for b in bars if str(b[0]).startswith(ymd)]


def vwap_series(bars):
    cum_pv = cum_v = 0.0
    out = []
    for b in bars:
        try:
            o, c, h, l, v = (float(b[1]), float(b[2]), float(b[3]),
                             float(b[4]), float(b[5]))
        except Exception:
            out.append(None)
            continue
        tp = (h + l + c) / 3
        cum_pv += tp * v
        cum_v += v
        out.append(cum_pv / cum_v if cum_v > 0 else None)
    return out


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
    D = prev[-1]
    T1 = nxt(T)
    if not T1:
        continue
    for c in pools[D]:
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
codes = sorted({x['code'] for x in cands})
print('候选 %d 票次 / %d 只 | 窗口 %s~%s' % (len(cands), len(codes), START, END))

todo = [c for c in codes if not os.path.exists(os.path.join(M15, c + '.json'))]
print('待抓m15: %d 只' % len(todo))
for i, c in enumerate(todo):
    fetch_m15(c)
    if (i + 1) % 50 == 0:
        print('  %d/%d' % (i + 1, len(todo)), flush=True)
    time.sleep(0.12)
m15 = {c: fetch_m15(c) for c in codes}
ok = sum(1 for c in codes if m15[c])
print('m15就绪 %d/%d\n' % (ok, len(codes)))


def a_exit(p1):
    lu = (p1.get('pct_change') or 0) >= 9.8
    if lu:
        return p1['close']
    return 0.7 * (p1['high'] + p1['open']) / 2 + 0.3 * p1['close']


rows = []
for x in cands:
    b = m15.get(x['code'])
    if not b:
        continue
    db = day_bars(b, x['T'].replace('-', ''))
    if len(db) < 16:
        continue
    p0 = bar(x['code'], x['T'])
    p1 = bar(x['code'], x['T1'])
    if not p0 or not p1:
        continue
    vw = vwap_series(db)
    lows = [float(z[4]) for z in db]
    entry = {
        'E0_kai': float(p0['open']),
        'E1_d15': float(db[0][4]),
        'E2_d30': min(lows[:2]),
        'E3_d60': min(lows[:4]),
        'E4_avg': (float(p0['open']) + float(db[0][4])) / 2,
    }
    f15 = all(float(z[2]) >= vw[i] for i, z in enumerate(db[:1]) if vw[i])
    f30 = all(float(z[2]) >= vw[i] for i, z in enumerate(db[:2]) if vw[i])
    f60 = all(float(z[2]) >= vw[i] for i, z in enumerate(db[:4]) if vw[i])
    rows.append(dict(code=x['code'], T=x['T'], T1=x['T1'], gap=x['gap'],
                     entry=entry, f15=f15, f30=f30, f60=f60, exit=a_exit(p1)))

print('可用样本 %d 票次' % len(rows))
sel = [r for r in rows if 4 <= r['gap'] <= 8]
print('其中 gap4-8%%: %d\n' % len(sel))


def rep(lab, arr, ekey, filt=None):
    a = [r for r in arr if (filt is None or r[filt])]
    vs = [(r['exit'] - r['entry'][ekey]) / r['entry'][ekey] * 100 for r in a]
    if len(vs) < 15:
        print('  %-32s n=%d 样本不足' % (lab, len(vs)))
        return
    se = st.pstdev(vs) / (len(vs) ** 0.5)
    print('  %-32s n=%4d 均%+6.2f%% 胜率%3.0f%% t=%5.2f' % (
        lab, len(vs), st.mean(vs),
        sum(1 for v in vs if v > 0) / len(vs) * 100, st.mean(vs) / se))


print('=== (1) 入场价变体 (出场=A式, 不过滤) ===')
for k, lab in (('E0_kai', '开盘价'), ('E1_d15', '等15分钟低点'),
               ('E2_d30', '等30分钟低点'), ('E3_d60', '等60分钟低点'),
               ('E4_avg', '开盘+15分低 均价(两笔)')):
    rep(lab, sel, k)
print('\n=== (2) 入场过滤 (入场=开盘价) ===')
rep('不过滤', sel, 'E0_kai')
rep('前15分站上分时均线', sel, 'E0_kai', 'f15')
rep('前30分站上分时均线', sel, 'E0_kai', 'f30')
rep('前60分站上分时均线', sel, 'E0_kai', 'f60')
print('\n=== (3) 组合 ===')
rep('等30分低点 + 前30分站均线', sel, 'E2_d30', 'f30')
rep('开盘价 + 前60分站均线', sel, 'E0_kai', 'f60')
json.dump(rows, open('data/_intraday_live.json', 'w', encoding='utf-8'), ensure_ascii=False)
