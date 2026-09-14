# -*- coding: utf-8 -*-
"""我方时代(08-20~09-11, 有全字段) 池内特征扫描 — 与A时代结论交叉验证
口径: 竞价快照gap(无K线依赖) + 板型/换手/市值/封单 当日值, 看 D+1(买入日) 封板率
"""
import json, os, sys, io, statistics as st
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def rd(p):
    try: return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError: return json.load(open(p, encoding='gbk'))
newp = {}
for f in sorted(os.listdir('data/zt_pool')):
    if not f.endswith('.json') or f == 'stock_index.json': continue
    ymd = f[:-5]; d = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
    data = rd('data/zt_pool/' + f)
    rs = data if isinstance(data, list) else data.get('stocks', [])
    newp[d] = {str(x.get('code','')).zfill(6): x for x in rs if x.get('code')}
NP = sorted(newp)

rows = []
for f in sorted(os.listdir('data/auction')):
    if not f.endswith('.json') or '_' in f: continue
    day = f[:-5]
    if day not in newp: continue
    prev = [x for x in NP if x < day]
    if not prev: continue
    d0 = prev[-1]
    if not newp[d0] or not all('board_type' in v for v in newp[d0].values()): continue
    auc = json.load(open('data/auction/'+f, encoding='utf-8'))
    for s in auc.get('stocks', []):
        c = str(s.get('code','')).zfill(6)
        x0 = newp.get(d0, {}).get(c)
        if not x0: continue
        g = s.get('gap_pct')
        if g is None and s.get('open') and s.get('prev_close'):
            g = (s['open']-s['prev_close'])/s['prev_close']*100
        if g is None or not (4 <= float(g) <= 8): continue
        fs = x0.get('first_seal') or ''
        try: fsm = int(fs[:2])*60 + int(fs[3:5])
        except Exception: fsm = None
        rows.append(dict(code=c, seal=1 if c in newp[day] else 0,
                         bt=x0.get('board_type'), to=x0.get('turnover'),
                         fc=(x0.get('float_cap') or 0)/1e8, fund=x0.get('seal_fund'),
                         brk=x0.get('break_times'), sr=x0.get('seal_rate'),
                         ld=x0.get('limit_days'), fs=fsm))
base = sum(r['seal'] for r in rows)/len(rows)*100
print(f'我方时代 gap4-8% n={len(rows)}  基率 {base:.1f}%\n')

def scan(key, label, k=4):
    vals = sorted(v for v in (r[key] for r in rows) if v is not None)
    if len(vals) < 60: print(f'{label:20s} 样本不足({len(vals)})'); return
    edges = [vals[int(len(vals)*i/k)] for i in range(1, k)]
    e = [min(vals)] + edges + [max(vals)+1e-9]
    out = []
    for i in range(len(e)-1):
        a = [r for r in rows if r[key] is not None and e[i] <= r[key] < e[i+1]]
        if len(a) < 12: continue
        out.append((len(a), sum(r['seal'] for r in a)/len(a)*100))
    if len(out) < 2: print(f'{label:20s} 分档不足'); return
    sp = max(o[1] for o in out) - min(o[1] for o in out)
    print(f'{label:20s} 极差{sp:5.1f}pt  ' + ' '.join(f'{o[1]:.0f}%(n={o[0]})' for o in out) + ('  ★★' if sp>=20 else '  ★' if sp>=12 else ''))

print('--- 数值 ---')
for k, lab in (('to','换手率'),('fc','流通市值(亿)'),('fund','封单额'),('brk','炸板次数'),
               ('sr','封板成功率'),('ld','连板数'),('fs','首封时间(分)')):
    scan(k, lab)
print('\n--- 分类 ---')
for k, lab in (('bt','板型'),):
    for v in sorted({r[k] for r in rows if r[k]}, key=str):
        a = [r for r in rows if r[k] == v]
        if len(a) < 10: continue
        print(f'  {lab} {str(v):8s} n={len(a):4d}  封板率 {sum(r["seal"] for r in a)/len(a)*100:5.1f}%')
