# -*- coding: utf-8 -*-
"""临时分析(2026-09-07): 全因子 × 两维涨停概率 (用户框架)
每个因子的每个分段: P(T日涨停)=当天封板率, P(T+1涨停)=次日接力率, 串联P×
口径: T-1涨停池全样本(无选择偏差), 一年窗2025-09-01~2026-08-19
建议分: 串联概率线性映射[40,100], 与现行归一化分对照
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

# 因子分段定义(与scoring_config v4.normalize键一致)
FACTOR_DEFS = {
    'vr': lambda k, s, kw: ('<0.5' if kw['vr'] < 0.5 else '0.5-1' if kw['vr'] < 1 else '1-2' if kw['vr'] < 2 else '2-4' if kw['vr'] < 4 else '>=4'),
    'gap': lambda k, s, kw: ('<0' if kw['gap'] < 0 else '0-2' if kw['gap'] < 2 else '2-4' if kw['gap'] < 4 else '4-6' if kw['gap'] < 6 else '6-8' if kw['gap'] < 8 else '8-10' if kw['gap'] < 10 else '>=10'),
    'board_type': lambda k, s, kw: kw['bt'],
    'cons': lambda k, s, kw: ('1' if kw['cons'] == 1 else '2' if kw['cons'] == 2 else '3' if kw['cons'] == 3 else '4' if kw['cons'] == 4 else '5+'),
    'seal': lambda k, s, kw: kw['seal_b'],
    'zhaban': lambda k, s, kw: ('0' if kw['zh'] == 0 else '1' if kw['zh'] == 1 else '2' if kw['zh'] == 2 else '3+'),
    'sector': lambda k, s, kw: kw['sec_b'],
    'divergence': lambda k, s, kw: kw['div_b'],
    'dt_risk_p': lambda k, s, kw: kw['dtp_b'],
    'turnover': lambda k, s, kw: kw['to_b'],
}
# 现行归一化分(旧形状, 与U型A对照用U型A后表)
CUR = {
    'vr': {'<0.5': 100, '0.5-1': 40, '1-2': 60, '2-4': 75, '>=4': 50},
    'gap': {'<0': 15, '0-2': 45, '2-4': 60, '4-6': 80, '6-8': 90, '8-10': 60, '>=10': 100},
    'board_type': {'T字': 70, '换手': 50, '一字': 100},
    'cons': {'1': 55, '2': 65, '3': 80, '4': 60, '5+': 65},
    'seal': {'<5min': 100, '5-10min': 65, '10-30min': 70, '30-60min': 65, '>60min': 40},
    'zhaban': {'0': 70, '1': 68, '2': 75, '3+': 55},
    'sector': {'<3': 40, '3-4': 65, '5-9': 70, '>=10': 85},
    'divergence': {'非分歧': 60, '分歧': 45},
    'dt_risk_p': {'cons3+': None, 'cons2': None, 'vr>=4': None, 'vr<1': None, 'else': None},
    'turnover': {'<2': 57, '2-20': 50, '>=20': 33},
}

stat = {fac: defaultdict(lambda: {'n': 0, 't_lu': 0, 't1_lu': 0}) for fac in FACTOR_DEFS}
ths_files = sorted(fn for fn in os.listdir(THS_DIR) if fn.endswith('.json') and WS <= fn[:8] <= WE)

for fn in ths_files:
    ymd = fn.replace('.json', '')
    d = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
    with open(os.path.join(THS_DIR, fn), encoding='utf-8') as f:
        info = json.load(f)
    word_freq = defaultdict(int)
    entries = []
    for s in info:
        code = str(s.get('code', ''))
        if not code or code.startswith(('300', '301', '688', '8', '9')):
            continue
        ws2 = [w for w in str(s.get('reason_type', '')).replace('，', '+').split('+') if w.strip()]
        for w in ws2:
            word_freq[w] += 1
        entries.append((code, s, ws2))
    for code, s, ws2 in entries:
        kls = ktbl.get(code)
        if not kls:
            continue
        idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
        if idx is None or idx < 20 or idx + 2 >= len(kls):
            continue
        k, pk = kls[idx], kls[idx - 1]
        k1, k2 = kls[idx + 1], kls[idx + 2]
        if not isinstance(k1, dict) or not isinstance(k2, dict):
            continue
        t_lu = is_lu(k1, k)
        t1_lu = is_lu(k2, k1)
        # 因子原始值
        vols = [kls[t]['volume'] for t in range(max(0, idx - 20), idx) if kls[t].get('volume', 0) > 0]
        vr = k['volume'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1.0
        gap = (k['open'] - pk['close']) / pk['close'] * 100 if pk['close'] > 0 else 0
        cons = 1
        j = idx - 1
        while j >= 1:
            if is_lu(kls[j], kls[j - 1]):
                cons += 1
                j -= 1
            else:
                break
        lu_price = round(pk['close'] * 1.10, 2)
        is_yz = k['open'] >= lu_price - 0.005 and k['low'] >= lu_price - 0.005
        is_tz = k['open'] >= lu_price - 0.005 and k['close'] >= lu_price - 0.005 and k['low'] < lu_price - 0.005
        bt = '一字' if is_yz else ('T字' if is_tz else '换手')
        try:
            to = float(s.get('turnover_rate', 0) or 0)
        except Exception:
            to = 0
        to_b = '<2' if to < 2 else ('2-20' if to < 20 else '>=20')
        try:
            seal_hm = datetime.fromtimestamp(int(s.get('first_limit_up_time'))).strftime('%H%M')
        except Exception:
            seal_hm = '1500'
        seal_b = '<5min' if seal_hm <= '0935' else ('5-10min' if seal_hm <= '0940' else (
            '10-30min' if seal_hm <= '1000' else ('30-60min' if seal_hm <= '1030' else '>60min')))
        zh = int(s.get('open_num', 0) or 0)
        heat = max(word_freq[w] for w in ws2) if ws2 else 0
        sec_b = '<3' if heat < 3 else ('3-4' if heat < 5 else ('5-9' if heat < 10 else '>=10'))
        div_b = '分歧' if (zh >= 1 and vr >= 1.5) else '非分歧'
        if cons >= 3:
            dtp_b = 'cons3+'
        elif cons == 2:
            dtp_b = 'cons2'
        elif vr >= 4:
            dtp_b = 'vr>=4'
        elif vr < 1:
            dtp_b = 'vr<1'
        else:
            dtp_b = 'else'
        kw = {'vr': vr, 'gap': gap, 'bt': bt, 'cons': cons, 'seal_b': seal_b,
              'zh': zh, 'sec_b': sec_b, 'div_b': div_b, 'dtp_b': dtp_b, 'to_b': to_b}
        for fac, segfn in FACTOR_DEFS.items():
            seg = segfn(k, s, kw)
            st = stat[fac][seg]
            st['n'] += 1
            st['t_lu'] += 1 if t_lu else 0
            st['t1_lu'] += 1 if t1_lu else 0

# 输出
ORDER = {'vr': ['<0.5', '0.5-1', '1-2', '2-4', '>=4'],
         'gap': ['<0', '0-2', '2-4', '4-6', '6-8', '8-10', '>=10'],
         'board_type': ['一字', 'T字', '换手'],
         'cons': ['1', '2', '3', '4', '5+'],
         'seal': ['<5min', '5-10min', '10-30min', '30-60min', '>60min'],
         'zhaban': ['0', '1', '2', '3+'],
         'sector': ['<3', '3-4', '5-9', '>=10'],
         'divergence': ['非分歧', '分歧'],
         'dt_risk_p': ['cons3+', 'cons2', 'vr>=4', 'vr<1', 'else'],
         'turnover': ['<2', '2-20', '>=20']}

for fac in FACTOR_DEFS:
    print(f'\n── {fac} ──')
    rows = []
    for seg in ORDER[fac]:
        st = stat[fac][seg]
        if st['n'] == 0:
            print(f'  {seg:<10} 无样本')
            continue
        pt = st['t_lu'] / st['n']
        pt1 = st['t1_lu'] / st['n']
        prod = pt * pt1
        rows.append((seg, st['n'], pt, pt1, prod))
        cur = CUR[fac].get(seg)
        print(f'  {seg:<10} N={st["n"]:>5}  P(T日)={pt:>6.1%}  P(T+1)={pt1:>6.1%}  串联={prod:>6.1%}  现行分={cur}')
    if rows:
        maxp = max(r[4] for r in rows)
        minp = min(r[4] for r in rows)
        sugg = []
        for seg, n, pt, pt1, prod in rows:
            sc = 40 + (prod - minp) / (maxp - minp) * 60 if maxp > minp else 70
            sugg.append(f'{seg}:{sc:.0f}')
        print(f'  → 建议分(串联线性映射): {" / ".join(sugg)}')
