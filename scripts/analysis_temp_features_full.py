# -*- coding: utf-8 -*-
"""池内特征全量扫描: 哪些字段真的能预测 D+1 封板?
样本: A时代(2026-03~07) gap4-8% 的 T-1涨停股
"""
import json, os, sys, io, datetime, statistics as st
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def rd(p):
    try: return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError: return json.load(open(p, encoding='gbk'))

hist = {}
for f in sorted(os.listdir('data/zt_pool_history_ths')):
    if not f.endswith('.json'): continue
    ymd = f[:-5]; d = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
    data = rd('data/zt_pool_history_ths/' + f)
    rows = data if isinstance(data, list) else data.get('stocks', [])
    hist[d] = {str(x.get('code','')).zfill(6): x for x in rows if x.get('code')}
DAYS = sorted(hist)
def nextday(d):
    nx = [x for x in DAYS if x > d]
    return nx[0] if nx else None

def hhmm(ts):
    try:
        t = datetime.datetime.fromtimestamp(int(ts)); return t.hour*60 + t.minute
    except Exception: return None

def tp_feats(tp):
    """分时涨跌幅序列(80点) → 封板稳定性特征"""
    if not tp or len(tp) < 20: return None
    v = [float(x) for x in tp]
    hi = max(v)
    thr = 9.5 if hi > 9.5 else hi * 0.95
    sealed = [1 if x >= thr else 0 for x in v]
    ratio = sum(sealed)/len(sealed)
    opens = sum(1 for i in range(1, len(sealed)) if sealed[i-1] == 1 and sealed[i] == 0)
    first = next((i for i, s in enumerate(sealed) if s), None)
    return dict(tp_seal_ratio=ratio, tp_opens=opens, tp_final=sealed[-1],
                tp_first=first/len(sealed) if first is not None else None)

rows = []
for d in DAYS:
    if not ('2026-03-01' <= d <= '2026-07-31'): continue
    n1 = nextday(d)
    if not n1: continue
    for c, x in hist[d].items():
        p = f'data/kline_data/{c}.json'
        if not os.path.exists(p): continue
        raw = rd(p); rr = raw.get('data', raw) if isinstance(raw, dict) else raw
        m = {b['date']: b for b in rr if b.get('date')}
        b0, b1 = m.get(d), m.get(n1)
        if not b0 or not b1 or not b0.get('close') or not b1.get('open'): continue
        g = (b1['open']-b0['close'])/b0['close']*100
        if not (4 <= g <= 8): continue
        r = dict(code=c, d=d, gap=g, seal=1 if c in hist[n1] else 0)
        r['turnover'] = x.get('turnover_rate')
        r['open_num'] = x.get('open_num')
        r['fs'] = hhmm(x.get('first_limit_up_time'))
        r['ls'] = hhmm(x.get('last_limit_up_time'))
        r['seal_span'] = (r['ls']-r['fs']) if (r['ls'] and r['fs']) else None
        r['suc_rate'] = x.get('limit_up_suc_rate')
        r['mktcap'] = (x.get('currency_value') or 0)/1e8
        r['ord_amt'] = x.get('order_amount')
        r['ord_vol'] = x.get('order_volume')
        r['btype'] = x.get('limit_up_type')
        r['ctag'] = x.get('change_tag')
        r['mtype'] = x.get('market_type')
        r['again'] = x.get('is_again_limit')
        r['hdv'] = x.get('high_days_value')
        f = tp_feats(x.get('time_preview'))
        if f: r.update(f)
        rows.append(r)

base = sum(r['seal'] for r in rows)/len(rows)*100
print(f'A时代 gap4-8% 样本 {len(rows)} | 基率 {base:.1f}%\n')

def buckets(vals, k=5):
    v = sorted(v for v in vals if v is not None)
    if len(v) < 50: return None
    return [v[int(len(v)*i/k)] for i in range(1, k)]

def scan(key, label, k=5, fmt='%.2f'):
    vals = [r[key] for r in rows if r.get(key) is not None]
    if len(vals) < 100: print(f'{label:22s} 有效样本不足({len(vals)})'); return
    qs = buckets(vals, k)
    if not qs: return
    edges = [min(vals)] + qs + [max(vals)+1e-9]
    out = []
    for i in range(len(edges)-1):
        a = [r for r in rows if r.get(key) is not None and edges[i] <= r[key] < edges[i+1]]
        if len(a) < 25: out.append(None); continue
        out.append((len(a), sum(r['seal'] for r in a)/len(a)*100))
    ss = [o for o in out if o]
    if len(ss) < 2: print(f'{label:22s} 分档样本不足'); return
    spread = max(o[1] for o in ss) - min(o[1] for o in ss)
    txt = ' '.join(f'{o[1]:.0f}%(n={o[0]})' for o in ss)
    mark = '  ★★' if spread >= 20 else ('  ★' if spread >= 12 else '')
    print(f'{label:22s} 极差{spread:5.1f}pt  {txt}{mark}')

print('--- 数值特征 (五分位, 封板率) ---')
for k, lab in (('turnover','换手率'),('open_num','开板次数(open_num)'),('fs','首封时间'),
               ('ls','末封时间'),('seal_span','首末封间隔(分)'),('suc_rate','涨停封板成功率'),
               ('mktcap','流通市值(亿)'),('ord_amt','封单额(元)'),('ord_vol','封单量(手)'),
               ('tp_seal_ratio','分时封板时间占比'),('tp_opens','分时开板次数'),
               ('tp_first','分时首封位置')):
    scan(k, lab)

print('\n--- 分类特征 ---')
for k, lab in (('btype','板型'),('ctag','change_tag'),('mtype','市场'),('again','是否连板'),
               ('tp_final','尾盘是否封住')):
    vs = sorted({r.get(k) for r in rows if r.get(k) is not None}, key=str)
    print(f'  [{lab}]')
    for v in vs:
        a = [r for r in rows if r.get(k) == v]
        if len(a) < 15: continue
        print(f'    {str(v):14s} n={len(a):4d}  封板率 {sum(r["seal"] for r in a)/len(a)*100:5.1f}%')
