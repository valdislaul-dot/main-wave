# -*- coding: utf-8 -*-
"""抓 5 分钟K线 (东财 klt=5, 约31个交易日 07-31~09-11) -> data/m5_live/
东财有限流, 1.8s/只 + 失败退避重试; 断点续传(已缓存跳过)
"""
import json, os, sys, io, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0'
OUT = 'data/m5_live'
os.makedirs(OUT, exist_ok=True)


def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))


def secid(code):
    return ('1.' if code.startswith(('5', '6', '9')) else '0.') + code


def fetch(code, lmt=1500):
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get'
           '?secid=' + secid(code) +
           '&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53,f54,f55,f56,f57,f58'
           '&klt=5&fqt=1&beg=0&end=20500101&lmt=' + str(lmt))
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    raw = urllib.request.urlopen(req, timeout=15).read().decode('utf-8')
    d = json.loads(raw)
    return (d.get('data') or {}).get('klines') or []


# 候选代码: T-1涨停池 ∩ 竞价快照, 窗口内
pools = {}
for base in ('data/zt_pool_history_ths', 'data/zt_pool'):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json') or f == 'stock_index.json':
            continue
        ymd = f[:-5]
        d = ymd[:4] + '-' + ymd[4:6] + '-' + ymd[6:8]
        data = rd(os.path.join(base, f))
        rows = data if isinstance(data, list) else data.get('stocks', [])
        pools[d] = {str(x.get('code', '')).zfill(6) for x in rows if x.get('code')}
DAYS = sorted(pools)
auc = {}
for f in sorted(os.listdir('data/auction')):
    if not f.endswith('.json') or '_' in f:
        continue
    auc[f[:-5]] = {str(s.get('code', '')).zfill(6)
                   for s in json.load(open('data/auction/' + f, encoding='utf-8')).get('stocks', [])}

codes = set()
for T in DAYS:
    if not ('2026-08-01' <= T <= '2026-09-11') or T not in auc:
        continue
    prev = [x for x in DAYS if x < T]
    if not prev:
        continue
    for c in pools[prev[-1]]:
        if c.startswith(('300', '301', '688', '8', '9')):
            continue
        if c in auc[T]:
            codes.add(c)
codes = sorted(codes)
todo = [c for c in codes if not os.path.exists(os.path.join(OUT, c + '.json'))]
print('候选 %d 只 | 待抓 %d 只' % (len(codes), len(todo)), flush=True)

ok = fail = 0
for i, c in enumerate(todo):
    got = None
    for attempt in range(3):
        try:
            got = fetch(c)
            break
        except Exception as e:
            time.sleep(2.5 * (attempt + 1))
    if got:
        json.dump(got, open(os.path.join(OUT, c + '.json'), 'w', encoding='utf-8'))
        ok += 1
    else:
        fail += 1
    if (i + 1) % 40 == 0:
        print('  %d/%d ok=%d fail=%d' % (i + 1, len(todo), ok, fail), flush=True)
    time.sleep(1.8)
print('完成 ok=%d fail=%d' % (ok, fail), flush=True)
