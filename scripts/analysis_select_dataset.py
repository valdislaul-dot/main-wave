# -*- coding: utf-8 -*-
"""选股研究数据集: D日涨停股的全部可用特征 -> D+1(买入日) 封板/收益
特征源: ths历史池(298天,2025-06~2026-08-19) + zt_pool(2026-07-24~09-11) + K线
输出: data/_select_dataset.csv
"""
import json, os, sys, io, math, datetime
import numpy as np
import pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))


# ---- 池 ----
pools = {}     # date -> {code: row}
src = {}       # date -> 'ths' | 'new'
for base, tag in (('data/zt_pool_history_ths', 'ths'), ('data/zt_pool', 'new')):
    for f in sorted(os.listdir(base)):
        if not f.endswith('.json') or f == 'stock_index.json':
            continue
        ymd = f[:-5]
        d = ymd[:4] + '-' + ymd[4:6] + '-' + ymd[6:8]
        data = rd(os.path.join(base, f))
        rows = data if isinstance(data, list) else data.get('stocks', [])
        if tag == 'new' and d in pools and src[d] == 'ths':
            pass
        pools[d] = {str(x.get('code', '')).zfill(6): x for x in rows if x.get('code')}
        src[d] = tag
DAYS = sorted(pools)

# ---- K线缓存 ----
KL = {}


def kline(c):
    if c in KL:
        return KL[c]
    p = 'data/kline_data/' + c + '.json'
    out = []
    if os.path.exists(p):
        raw = rd(p)
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        out = [b for b in rows if b.get('date')]
    KL[c] = out
    return out


AUG = json.load(open('data/_regime_klines_aug.json', encoding='utf-8'))


def augmap(c):
    return {b['date']: b for b in (AUG.get(c) or [])}


def hhmm(ts):
    try:
        t = datetime.datetime.fromtimestamp(int(ts))
        return t.hour * 60 + t.minute
    except Exception:
        return None


def tp_feats(tp):
    if not tp or len(tp) < 20:
        return {}
    try:
        v = [float(x) for x in tp if x is not None]
    except (TypeError, ValueError):
        return {}
    if len(v) < 20:
        return {}
    mx = max(v)
    thr = mx - 0.15 if mx > 5 else mx * 0.98
    sealed = [1 if x >= thr else 0 for x in v]
    n = len(sealed)
    first = next((i for i, s in enumerate(sealed) if s), None)
    opens = sum(1 for i in range(1, n) if sealed[i - 1] == 1 and sealed[i] == 0)
    after = v[first:] if first is not None else v
    return {
        'tp_seal_ratio': sum(sealed) / n,
        'tp_opens': float(opens),
        'tp_first_pos': (first / n) if first is not None else 1.0,
        'tp_final_sealed': float(sealed[-1]),
        'tp_close_pct': v[-1],
        'tp_min_after': (min(after) - mx) if after else 0.0,
        'tp_amp': mx - min(v),
        'tp_last30_min': min(v[int(n * 0.62):]) if n >= 20 else min(v),
    }


rows = []
for i, D in enumerate(DAYS):
    if i + 1 >= len(DAYS):
        continue
    D1 = DAYS[i + 1]
    nxt = pools[D1]
    # 当日池统计
    zt_n = len(pools[D])
    try:
        max_cons = max(int(x.get('limit_days', 1) or 1) for x in pools[D].values())
    except Exception:
        max_cons = 1
    # 题材计数
    theme_cnt = {}
    for c, x in pools[D].items():
        rs = str(x.get('reason_type') or x.get('industry') or '')
        for t in [s for s in rs.replace('+', '|').split('|') if s]:
            theme_cnt[t] = theme_cnt.get(t, 0) + 1

    for c, x in pools[D].items():
        if c.startswith(('300', '301', '688', '8', '9')):
            continue
        row = {'date': D, 'code': c, 'src': src[D], 'zt_n': zt_n, 'max_cons_day': max_cons}
        # 池字段 (两源归一)
        row['turnover'] = x.get('turnover_rate') if x.get('turnover_rate') is not None else x.get('turnover')
        row['open_num'] = x.get('open_num') if x.get('open_num') is not None else x.get('break_times')
        row['board_type'] = x.get('limit_up_type') or x.get('board_type')
        row['suc_rate'] = x.get('limit_up_suc_rate') if x.get('limit_up_suc_rate') is not None else x.get('seal_rate')
        cv = x.get('currency_value') if x.get('currency_value') is not None else x.get('float_cap')
        row['mktcap'] = (cv / 1e8) if cv else None
        row['ord_amt'] = x.get('order_amount') if x.get('order_amount') is not None else x.get('seal_fund')
        ld = x.get('limit_days')
        if ld is None:
            hd = str(x.get('high_days') or '')
            import re
            m = re.search(r'(\d+)板', hd)
            ld = int(m.group(1)) if m else 1
        row['limit_days'] = int(ld or 1)
        fs = x.get('first_limit_up_time')
        row['first_seal_min'] = hhmm(fs) if fs else (int(str(x['first_seal'])[:2]) * 60 + int(str(x['first_seal'])[3:5]) if x.get('first_seal') else None)
        ls = x.get('last_limit_up_time')
        row['last_seal_min'] = hhmm(ls) if ls else (int(str(x['last_seal'])[:2]) * 60 + int(str(x['last_seal'])[3:5]) if x.get('last_seal') else None)
        row['ctag'] = x.get('change_tag')
        rs = str(x.get('reason_type') or x.get('industry') or '')
        row['theme_max'] = max([theme_cnt.get(t, 0) for t in rs.replace('+', '|').split('|')] or [0])
        row.update(tp_feats(x.get('time_preview')))

        # K线特征
        use_aug = D >= '2026-08-18'
        m = augmap(c) if use_aug else {b['date']: b for b in kline(c)}
        if not m or D not in m:
            continue
        ds = sorted(m)
        di = ds.index(D)
        if di < 21:
            continue
        k = m[D]
        pk = m[ds[di - 1]]
        if not k.get('close') or not pk.get('close'):
            continue
        vols = [m[q]['volume'] for q in ds[max(0, di - 20):di] if m[q].get('volume')]
        row['vr20'] = (k['volume'] / (sum(vols) / len(vols))) if vols and k.get('volume') else None
        row['prev_pct'] = pk.get('pct_change')
        row['amp'] = ((k.get('high', 0) - k.get('low', 0)) / pk['close'] * 100) if pk['close'] else None
        row['is_yizi'] = 1.0 if (k.get('high') == k.get('low')) else 0.0
        hi20 = max(m[q]['high'] for q in ds[max(0, di - 19):di + 1])
        row['pos20'] = (k['close'] / hi20 * 100) if hi20 else None
        for w in (5, 10, 20):
            if di - w >= 0 and m[ds[di - w]].get('close'):
                row['ret%d' % w] = (k['close'] / m[ds[di - w]]['close'] - 1) * 100
        # 结果
        seal = 1 if c in nxt else 0
        row['seal'] = seal
        if D1 in m:
            b1 = m[D1]
        else:
            b1 = None
            for r in (AUG.get(c) or []):
                if r.get('date') == D1:
                    b1 = r
                    break
        if b1 and b1.get('open') and k.get('close'):
            gap = (b1['open'] - k['close']) / k['close'] * 100
            row['gap'] = gap
            row['seal_buy'] = seal          # 买入日(D+1)是否封板
            # ⚠ T+1制度: 买入日不可卖, 最早次日(D+2)出场 → 用 D+2 的A式规则
            D2 = DAYS[i + 2] if i + 2 < len(DAYS) else None
            b2 = None
            if D2:
                mm = augmap(c) if D2 >= '2026-08-18' else {b['date']: b for b in kline(c)}
                b2 = mm.get(D2)
            if b2 and b2.get('open') and b2.get('close'):
                row['seal_exit'] = 1 if c in pools[D2] else 0
                lu2 = (b2.get('pct_change') or 0) >= 9.8
                ex = b2['close'] if lu2 else 0.7 * (b2['high'] + b2['open']) / 2 + 0.3 * b2['close']
                row['ret_a'] = (ex - b1['open']) / b1['open'] * 100
                row['ret_b1'] = (b1['close'] - b1['open']) / b1['open'] * 100  # 参考: 买入日当天(不可执行)
        rows.append(row)

df = pd.DataFrame(rows)
df.to_csv('data/_select_dataset.csv', index=False, encoding='utf-8-sig')
print('行数', len(df), '| 日期', df['date'].min(), '~', df['date'].max())
print('封板率', df['seal'].mean() * 100)
print('有ret_a的', df['ret_a'].notna().sum())
print('\n每列非空率:')
for c in df.columns:
    print('  %-18s %5.1f%%' % (c, df[c].notna().mean() * 100))
