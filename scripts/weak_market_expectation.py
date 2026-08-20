"""竞价4-8%买入的完整期望链: T日开盘买→收盘, T+1开盘买→收盘, 按环境分层"""
import json, os
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIRS = [os.path.join(BASE, 'data', 'kline_data'),
              os.path.join(BASE, 'data', 'backtest_kline')]
START, END = '2023-08-19', '2026-08-19'


def is_lu(pct, name):
    if pct is None:
        return False
    if 'ST' in (name or ''):
        return pct >= 4.85
    return pct >= 9.8


def load_all():
    tbl = {}
    for d in KLINE_DIRS:
        for fn in os.listdir(d):
            if not fn.endswith('.json') or fn.startswith('._'):
                continue
            code = fn.replace('.json', '')
            if code.startswith(('300', '301', '688', '8', '9')):
                continue
            j = None
            for enc in ('utf-8', 'gbk'):
                try:
                    with open(os.path.join(d, fn), encoding=enc) as f:
                        j = json.load(f)
                    break
                except Exception:
                    continue
            if j is None:
                continue
            name = (j.get('metadata') or {}).get('name', '')
            rows = j.get('data', j) if isinstance(j, dict) else j
            t = {}
            pc = None
            for r in rows:
                if not isinstance(r, dict):
                    continue
                date = r.get('date', '')
                if not (START <= date <= END):
                    continue
                cl = float(r.get('close', 0) or 0)
                op = float(r.get('open', 0) or 0)
                gap = (op - pc) / pc * 100 if pc and pc > 0 and op > 0 else None
                t[date] = {'open': op, 'close': cl, 'gap': gap,
                           'pct': r.get('pct_change')}
                pc = cl
            if t:
                tbl[code] = (name, t)
    return tbl


def main():
    print('加载K线...')
    tbl = load_all()
    print(f'{len(tbl)}只')

    pool = defaultdict(set)
    for code, (name, t) in tbl.items():
        for date, r in t.items():
            if is_lu(r['pct'], name):
                pool[date].add(code)
    days = sorted(pool.keys())

    rows = defaultdict(list)
    for i, d in enumerate(days):
        n = len(pool[d])
        env = '弱市' if n < 40 else ('强势' if n >= 70 else '正常')
        for code in tbl:
            name, t = tbl[code]
            r = t.get(d)
            if not r or r['gap'] is None or not (4.0 <= r['gap'] <= 8.0):
                continue
            ret_t = (r['close'] - r['open']) / r['open'] * 100
            lu_t = is_lu(r['pct'], name)
            ret_t1 = None
            if i + 1 < len(days):
                d1 = days[i + 1]
                r1 = t.get(d1)
                if r1 and r1['open'] > 0:
                    ret_t1 = (r1['close'] - r1['open']) / r1['open'] * 100
            rows[env].append({'ret_t': ret_t, 'lu_t': lu_t, 'ret_t1': ret_t1})

    print()
    print('竞价4-8%买入 完整期望链 (T日开盘买入):')
    print('环境     样本   当日封板率   当日均收益   当日炸板均亏   次日均收益   T开盘→T+1收盘期望')
    for env in ('弱市', '正常', '强势'):
        items = rows[env]
        if len(items) < 100:
            continue
        lu_rate = sum(1 for x in items if x['lu_t']) / len(items) * 100
        ret_t_mean = sum(x['ret_t'] for x in items) / len(items)
        zb = [x for x in items if not x['lu_t']]
        zb_mean = sum(x['ret_t'] for x in zb) / len(zb) if zb else 0
        with_t1 = [x for x in items if x['ret_t1'] is not None]
        ret_t1_mean = sum(x['ret_t1'] for x in with_t1) / len(with_t1)
        e2 = sum(x['ret_t'] + x['ret_t1'] for x in with_t1) / len(with_t1)
        print(f'{env}   {len(items):>6}   {lu_rate:>6.0f}%   {ret_t_mean:>+8.2f}%   '
              f'{zb_mean:>+9.2f}%   {ret_t1_mean:>+8.2f}%   {e2:>+14.2f}%')

    print()
    print('弱市日 竞价4-8% 当日炸板股的收盘涨幅分位:')
    zb_all = sorted(x['ret_t'] for x in rows['弱市'] if not x['lu_t'])
    for pct in (10, 25, 50, 75, 90):
        idx = min(len(zb_all) - 1, int(len(zb_all) * pct / 100))
        print(f'  分位{pct}%: {zb_all[idx]:+.2f}%')

    # 弱市日当天封住的14%: 次日完整表现
    print()
    print('弱市日 当天封住(14%)的次日:')
    sealed = [x for x in rows['弱市'] if x['lu_t'] and x['ret_t1'] is not None]
    if sealed:
        m = sum(x['ret_t1'] for x in sealed) / len(sealed)
        print(f'  {len(sealed)}笔 次日开盘→收盘均{m:+.2f}%')

    # 弱市炸板后: T+1开盘卖 vs T+1收盘卖 vs 持有等修复
    print()
    print('弱市日 当天炸板股: T+1不同卖出时机的期望 (从T日开盘买入算累计):')
    zb1 = [x for x in rows['弱市'] if not x['lu_t'] and x['ret_t1'] is not None]
    for mode, fn in (('T+1开盘卖(竞价止损)', lambda x: x['ret_t']),
                     ('T+1收盘卖(等修复)', lambda x: x['ret_t'] + x['ret_t1'])):
        m = sum(fn(x) for x in zb1) / len(zb1)
        wins = sum(1 for x in zb1 if fn(x) > 0)
        print(f'  {mode}: {len(zb1)}笔 均{m:+.2f}% 正收益占比{wins/len(zb1)*100:.0f}%')


if __name__ == '__main__':
    main()
