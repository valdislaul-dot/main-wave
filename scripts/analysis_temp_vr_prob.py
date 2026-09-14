# -*- coding: utf-8 -*-
"""临时分析(2026-09-07): vr段 × 两维涨停概率 (用户提出的框架)
维度1: P(T日涨停 | vr段) — 买入当天封板率(当天安全关口)
维度2: P(T+1日涨停 | vr段) — 次日接力涨停率(溢价维度)
口径: T-1涨停池全样本(无选择偏差), 一年窗2025-09-01~2026-08-19
两层: 全样本(含一字) + 去一字(竞价可买口径)
综合分: 串联概率 P_T×P_T1 与 等权平均, 映射0-100
只读数据, 不写回任何配置。
"""
import json, os, sys
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
WS, WE = '20250901', '20260819'

klines_cache = {}
def get_klines(code):
    if code in klines_cache:
        return klines_cache[code]
    for enc in ('utf-8', 'gbk'):
        try:
            with open(os.path.join(KLINE_DIR, f'{code}.json'), encoding=enc) as f:
                raw = json.load(f)
            kls = raw.get('data', raw) if isinstance(raw, dict) else raw
            klines_cache[code] = kls
            return kls
        except Exception:
            continue
    klines_cache[code] = None
    return None

def is_lu(k, pk):
    if k.get('pct_change') is not None:
        return k['pct_change'] >= 9.8
    return bool(pk) and pk['close'] > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098

def is_yz(k, pk):
    """一字板: 开=低=涨停价"""
    if not pk or pk['close'] <= 0:
        return False
    lu = round(pk['close'] * 1.10, 2)
    return k['open'] >= lu - 0.005 and k['low'] >= lu - 0.005

def vr_seg(vr):
    return '<0.5' if vr < 0.5 else '0.5-1' if vr < 1 else '1-2' if vr < 2 else '2-4' if vr < 4 else '>=4'

SEGS = ['<0.5', '0.5-1', '1-2', '2-4', '>=4']

# 预载K线
ktbl = {}
for fn in os.listdir(KLINE_DIR):
    if not fn.endswith('.json') or fn.startswith('._'):
        continue
    code = fn.replace('.json', '')
    if code.startswith(('300', '301', '688', '8', '9')):
        continue
    kls = get_klines(code)
    if kls:
        ktbl[code] = kls
print(f'K线: {len(ktbl)}只')

ths_files = sorted(fn for fn in os.listdir(THS_DIR) if fn.endswith('.json') and WS <= fn[:8] <= WE)
print(f'池天数: {len(ths_files)}')

# 统计: seg -> {'n_all': 样本数, 't_lu': T日涨停数, 't1_lu': T+1涨停数, 'n_no_yz': 去一字样本, ...}
stat = {s: {'n': 0, 't_lu': 0, 't1_lu': 0, 'n_noyz': 0, 't_lu_noyz': 0, 't1_lu_noyz': 0} for s in SEGS}
skipped = 0

for fn in ths_files:
    ymd = fn.replace('.json', '')
    d = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
    with open(os.path.join(THS_DIR, fn), encoding='utf-8') as f:
        info = json.load(f)
    for s in info:
        code = str(s.get('code', ''))
        if not code or code.startswith(('300', '301', '688', '8', '9')):
            continue
        kls = ktbl.get(code)
        if not kls:
            continue
        idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
        if idx is None or idx < 20 or idx + 2 >= len(kls):
            skipped += 1
            continue
        k, pk = kls[idx], kls[idx - 1]
        vols = [kls[t]['volume'] for t in range(max(0, idx - 20), idx) if kls[t].get('volume', 0) > 0]
        if not vols or sum(vols) <= 0:
            continue
        vr = k['volume'] / (sum(vols) / len(vols))
        seg = vr_seg(vr)
        st = stat[seg]
        st['n'] += 1
        # T日与T+1日bar (K线需覆盖T+1)
        k1 = kls[idx + 1] if isinstance(kls[idx + 1], dict) else None
        k2 = kls[idx + 2] if isinstance(kls[idx + 2], dict) else None
        if k1 is None or k2 is None:
            continue
        t_lu = is_lu(k1, k)
        t1_lu = is_lu(k2, k1)
        st['t_lu'] += 1 if t_lu else 0
        st['t1_lu'] += 1 if t1_lu else 0
        yz = is_yz(k1, k)
        if not yz:
            st['n_noyz'] += 1
            st['t_lu_noyz'] += 1 if t_lu else 0
            st['t1_lu_noyz'] += 1 if t1_lu else 0

print(f'\n===== vr段 × 两维涨停概率 (一年窗 T-1池全样本, 跳过{skipped}只K线不足) =====')
print(f'{"vr段":<8}{"样本":>6}{"P(T日涨停)":>12}{"P(T+1涨停)":>12}{"串联P×":>10}{"等权均":>10}  {"去一字: 样本/PT/PT1"}')
rows = []
for s in SEGS:
    st = stat[s]
    if st['n'] == 0:
        continue
    pt = st['t_lu'] / st['n']
    pt1 = st['t1_lu'] / st['n']
    prod = pt * pt1
    avg = (pt + pt1) / 2
    rows.append((s, st['n'], pt, pt1, prod, avg))
    noyz = f'{st["n_noyz"]}/{st["t_lu_noyz"]/max(st["n_noyz"],1)*100:.0f}%/{st["t1_lu_noyz"]/max(st["n_noyz"],1)*100:.0f}%'
    print(f'{s:<8}{st["n"]:>6}{pt:>11.1%}{pt1:>11.1%}{prod:>9.1%}{avg:>9.1%}  {noyz}')

# 综合分映射方案 (等权平均 → 0-100线性映射: 最高段100, 最低段按相对值)
print('\n===== 综合打分建议 (基于串联概率, 线性映射) =====')
maxp = max(r[4] for r in rows)
minp = min(r[4] for r in rows)
for s, n, pt, pt1, prod, avg in rows:
    if maxp > minp:
        score = 40 + (prod - minp) / (maxp - minp) * 60
    else:
        score = 70
    print(f'  {s:<8} 串联{prod:.1%} → 建议分{score:.0f}')
