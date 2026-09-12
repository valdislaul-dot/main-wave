# -*- coding: utf-8 -*-
"""跨期行情体制对照 (2026-09-12)
问题: 模型 vs A 的差距, 以及 8月起"买了就跌"的成因 — 用数据对照, 不推测
口径: 设 D=涨停日, D+1=次日(我们模型的买入日, 竞价高开4-8%窗口), D+2=卖出参考日
数据源: data/zt_pool_history_ths (<=2026-08-19) + data/zt_pool (>=2026-08-20) + data/kline_data
"""
import json, os, sys, io, glob
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KLINE = 'data/kline_data'
THS = 'data/zt_pool_history_ths'
ZTP = 'data/zt_pool'
START, END = '2026-02-01', '2026-09-11'

_cache = {}
def kline(code):
    """code -> {date: (open,high,low,close,pct,vol)}  仅保留 START~END 段"""
    if code in _cache:
        return _cache[code]
    p = os.path.join(KLINE, code + '.json')
    out = None
    if os.path.exists(p):
        try:
            raw = json.load(open(p, encoding='utf-8'))
        except UnicodeDecodeError:
            raw = json.load(open(p, encoding='gbk'))
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        out = {}
        for b in rows:
            d = str(b.get('date', ''))
            if START <= d <= END:
                out[d] = (b.get('open'), b.get('high'), b.get('low'),
                          b.get('close'), b.get('pct_change'), b.get('volume'))
    _cache[code] = out
    return out

def load_pools():
    """date -> [codes]  (ths 优先的历史段 + zt_pool 近期段)"""
    pools = {}
    for f in sorted(os.listdir(THS)):
        if not f.endswith('.json'):
            continue
        d = f[:-5]
        d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        if not (START <= d <= END):
            continue
        try:
            data = json.load(open(os.path.join(THS, f), encoding='utf-8'))
        except Exception:
            continue
        rows = data if isinstance(data, list) else data.get('stocks', [])
        pools[d] = [str(x.get('code', '')).zfill(6) for x in rows if x.get('code')]
    for f in sorted(os.listdir(ZTP)):
        if not f.endswith('.json') or f == 'stock_index.json':
            continue
        d = f[:-5]
        d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        if not (START <= d <= END):
            continue
        try:
            data = json.load(open(os.path.join(ZTP, f), encoding='utf-8'))
        except Exception:
            continue
        rows = data if isinstance(data, list) else data.get('stocks', [])
        pools[d] = [str(x.get('code', '')).zfill(6) for x in rows if x.get('code')]
    return pools

def daterange(pools):
    return sorted(pools.keys())

def main():
    pools = load_pools()
    days = daterange(pools)
    print(f'池覆盖: {len(days)} 个交易日  {days[0]} ~ {days[-1]}')

    # 每天: 对 D 池每只股, 用 D+1/D+2 的K线算次日表现
    rows = []
    miss = 0
    for i, d in enumerate(days[:-2]):
        codes = pools[d]
        d1, d2 = days[i + 1], days[i + 2]
        recs = []
        for c in codes:
            kl = kline(c)
            if not kl:
                miss += 1
                continue
            k0, k1, k2 = kl.get(d), kl.get(d1), kl.get(d2)
            if not k0 or not k1 or not k2:
                miss += 1
                continue
            if not k0[3] or not k1[0] or not k1[3] or not k2[3]:
                continue
            gap1 = (k1[0] - k0[3]) / k0[3] * 100
            d1_ret = (k1[3] - k1[0]) / k1[0] * 100          # D+1开盘买入 -> D+1收盘
            d1_close_ret = (k1[3] - k0[3]) / k0[3] * 100    # D收盘 -> D+1收盘 (接力期望)
            d2_ret = (k2[3] - k1[0]) / k1[0] * 100          # D+1开盘买入 -> D+2收盘 (持有1天)
            d2_gap = (k2[0] - k1[3]) / k1[3] * 100
            lu1 = (k1[4] or 0) >= 9.8
            lu2 = (k2[4] or 0) >= 9.8
            amp1 = (k1[1] - k1[2]) / k0[3] * 100 if k1[1] and k1[2] else 0
            recs.append(dict(code=c, gap1=gap1, d1_ret=d1_ret, d1_close_ret=d1_close_ret,
                             d2_ret=d2_ret, d2_gap=d2_gap, lu1=lu1, lu2=lu2, amp1=amp1))
        if not recs:
            continue
        rows.append(dict(date=d, n=len(codes), got=len(recs), recs=recs))

    print(f'可用样本日: {len(rows)} | 缺K线跳过: {miss}')
    json.dump(rows, open('data/_regime_rows.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print('已存 data/_regime_rows.json')

if __name__ == '__main__':
    main()
