"""跌停开板/地天板分析 — 3年日K线 (2023-08~2026-08, 剔除300/301/688/8/9)
维度:
[1] 盘中触跌停的开板率
[2] 跌停开盘(open≈跌停价)的开板率+当日收盘分布
[3] 地天板(跌停→涨停)频率与条件
[4] 跌停开板股 vs 封死跌停股 的次日表现
[5] 跌停开盘股按连板数分层(宝泰隆场景: 2板断板跌停开)
输出: logs/limit_down_analysis.txt
"""
import json, os
from datetime import datetime
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


def limit_price(prev_close, is_st, up=True):
    pct = 0.05 if is_st else 0.10
    if up:
        return round(prev_close * (1 + pct), 2)
    return round(prev_close * (1 - pct), 2)


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
            for r in rows:
                if not isinstance(r, dict):
                    continue
                date = r.get('date', '')
                if not (START <= date <= END):
                    continue
                t[date] = {
                    'open': float(r.get('open', 0) or 0),
                    'high': float(r.get('high', 0) or 0),
                    'low': float(r.get('low', 0) or 0),
                    'close': float(r.get('close', 0) or 0),
                    'pct': r.get('pct_change'),
                }
            if t:
                tbl[code] = (name, t)
    return tbl


def main():
    print('加载K线...')
    tbl = load_all()
    print(f'{len(tbl)}只')

    rows = []   # 每行: {code, name, date, open, low, close, dt_price, lu_price,
                #       touch_dt, dt_open, opened, dt_sealed, dt2lu(地天), prev_lu, cons}
    for code, (name, t) in tbl.items():
        is_st = 'ST' in name
        dates = sorted(t.keys())
        for i, d in enumerate(dates):
            if i == 0:
                continue
            r = t[d]
            prev = t[dates[i - 1]]
            pc = prev['close']
            if pc <= 0:
                continue
            dt_price = limit_price(pc, is_st, up=False)
            lu_price = limit_price(pc, is_st, up=True)
            touch = r['low'] <= dt_price + 0.005
            if not touch:
                continue
            dt_open = r['open'] <= dt_price + 0.005
            opened = r['close'] > dt_price + 0.005
            dt2lu = r['close'] >= lu_price - 0.005 and r['high'] >= lu_price - 0.005
            prev_lu = is_lu(prev['pct'], name)
            rows.append({
                'code': code, 'name': name, 'date': d,
                'open': r['open'], 'low': r['low'], 'close': r['close'],
                'dt_price': dt_price, 'lu_price': lu_price,
                'dt_open': dt_open, 'opened': opened, 'dt2lu': dt2lu,
                'prev_lu': prev_lu,
            })

    out = []
    out.append('=' * 78)
    out.append('跌停开板/地天板分析 — 3年 (2023-08~2026-08, 剔除300/301/688/8/9)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 盘中触跌停总样本: {len(rows)}')
    out.append('=' * 78)

    def fmt(pct_v):
        return f'{pct_v*100:.1f}%'

    # [1] 开板率
    out.append('\n[1] 盘中触跌停 → 当日开板率')
    opened_n = sum(1 for x in rows if x['opened'])
    dt2lu_n = sum(1 for x in rows if x['dt2lu'])
    out.append(f'  触跌停 {len(rows)} 次, 当日开板 {opened_n} 次 ({fmt(opened_n/len(rows))}), '
               f'地天板 {dt2lu_n} 次 ({fmt(dt2lu_n/len(rows))})')

    # [2] 跌停开盘的
    dt_open_rows = [x for x in rows if x['dt_open']]
    out.append('\n[2] 跌停开盘(open≈跌停价): 开板率 + 收盘分布')
    if dt_open_rows:
        op_n = sum(1 for x in dt_open_rows if x['opened'])
        out.append(f'  跌停开盘 {len(dt_open_rows)} 次, 当日开板 {op_n} 次 ({fmt(op_n/len(dt_open_rows))})')
        # 收盘位置分布
        dist = defaultdict(int)
        for x in dt_open_rows:
            if x['dt2lu']:
                dist['地天板(涨停收)'] += 1
            elif x['close'] >= x['dt_price'] + 0.005 and x['close'] > x['dt_price']:
                # 收盘相对跌停价的反弹幅度
                reb = (x['close'] - x['dt_price']) / x['dt_price'] * 100
                if reb >= 6: dist['反弹≥6%'] += 1
                elif reb >= 3: dist['反弹3-6%'] += 1
                elif reb >= 1: dist['反弹1-3%'] += 1
                else: dist['微开板<1%'] += 1
            else:
                dist['封死跌停'] += 1
        for k, v in sorted(dist.items(), key=lambda x: -x[1]):
            out.append(f'    {k}: {v} ({fmt(v/len(dt_open_rows))})')

    # [3] 地天板条件
    out.append('\n[3] 地天板: 频率与前置条件')
    if dt2lu_n:
        dt2lu_rows = [x for x in rows if x['dt2lu']]
        prev_lu_n = sum(1 for x in dt2lu_rows if x['prev_lu'])
        out.append(f'  3年共 {dt2lu_n} 次地天板, 其中前一交易日涨停的 {prev_lu_n} 次 ({fmt(prev_lu_n/dt2lu_n)})')
        # 地天板 vs 全部触跌停: 前日涨停占比对比
        all_prev_lu = sum(1 for x in rows if x['prev_lu'])
        out.append(f'  对照: 全部触跌停样本中前日涨停占比 {fmt(all_prev_lu/len(rows))}')
    else:
        out.append('  无地天板样本')

    # [4] 开板 vs 封死的次日
    out.append('\n[4] 次日表现: 跌停开板 vs 封死跌停')
    # 需要次日数据: 用tbl二次查
    nxt = {}
    for code, (name, t) in tbl.items():
        dates = sorted(t.keys())
        for i, d in enumerate(dates):
            if i + 1 < len(dates):
                nxt[(code, d)] = t[dates[i + 1]]
    for label, cond in (('开板', lambda x: x['opened']), ('封死跌停', lambda x: not x['opened'])):
        items = [x for x in rows if cond(x)]
        rets, gaps = [], []
        for x in items:
            r1 = nxt.get((x['code'], x['date']))
            if not r1 or x['close'] <= 0 or r1['open'] <= 0 or r1['close'] <= 0:
                continue
            rets.append((r1['close'] - x['close']) / x['close'] * 100)
            gaps.append((r1['open'] - x['close']) / x['close'] * 100)
        if len(rets) >= 20:
            up = sum(1 for r in rets if r > 0) / len(rets) * 100
            out.append(f'  {label}: {len(rets)}笔 次日均{sum(rets)/len(rets):+.2f}% 上涨率{up:.0f}% '
                       f'次日均gap{sum(gaps)/len(gaps):+.2f}%')

    # [5] 跌停开盘按前日状态分层 (宝泰隆: 前日断板+今日跌停开)
    out.append('\n[5] 跌停开盘股: 按前日是否涨停分层')
    for label, cond in (('前日涨停(昨涨停今跌停)', lambda x: x['prev_lu']),
                        ('前日未涨停(断板后跌停)', lambda x: not x['prev_lu'])):
        items = [x for x in dt_open_rows if cond(x)]
        if not items:
            continue
        op_n = sum(1 for x in items if x['opened'])
        out.append(f'  {label}: {len(items)}次, 当日开板率 {fmt(op_n/len(items))}')
        # 次日
        rets = []
        for x in items:
            r1 = nxt.get((x['code'], x['date']))
            if not r1 or x['close'] <= 0 or r1['open'] <= 0 or r1['close'] <= 0:
                continue
            rets.append((r1['close'] - x['close']) / x['close'] * 100)
        if len(rets) >= 10:
            up = sum(1 for r in rets if r > 0) / len(rets) * 100
            out.append(f'    次日: {len(rets)}笔 均{sum(rets)/len(rets):+.2f}% 上涨率{up:.0f}%')

    with open(os.path.join(BASE, 'logs', 'limit_down_analysis.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/limit_down_analysis.txt')


if __name__ == '__main__':
    main()
