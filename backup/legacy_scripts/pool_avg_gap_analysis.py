"""竞价池平均gap信号校准表 — 方案B的阈值校准
信号: T-1涨停股在T日竞价的平均gap (每日一个值, 竞价面板二次确认用)
分档: 日均gap按1%粒度, 统计各档对应的当日表现
口径: T-1涨停股(剔除300/301/688/8/9), T日竞价open, T日收盘
输出: logs/pool_avg_gap_analysis.txt
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

    # T-1涨停池
    pool = defaultdict(set)
    for code, (name, t) in tbl.items():
        for date, r in t.items():
            if is_lu(r['pct'], name):
                pool[date].add(code)
    days = sorted(pool.keys())

    # 每日: 池均gap + 池内股票当日表现
    day_rows = []   # {date, avg_gap, stocks: [(ret_overnight, ret_intraday, ret_total, lu_t)]}
    for i, d in enumerate(days):
        if i + 1 >= len(days):
            continue
        d1 = days[i + 1]
        gaps = []
        stocks = []
        for c in pool[d]:
            _, t = tbl.get(c, ('', {}))
            if d not in t or d1 not in t:
                continue
            r0, r1 = t[d], t[d1]
            if r0['close'] <= 0 or r1['open'] <= 0 or r1['close'] <= 0:
                continue
            gap = (r1['open'] - r0['close']) / r0['close'] * 100
            ret_intra = (r1['close'] - r1['open']) / r1['open'] * 100
            ret_total = (r1['close'] - r0['close']) / r0['close'] * 100
            gaps.append(gap)
            stocks.append({
                'gap': gap, 'ret_intra': ret_intra, 'ret_total': ret_total,
                'lu_t': is_lu(r1['pct'], ''),
            })
        if gaps:
            day_rows.append({
                'date': d1,
                'avg_gap': sum(gaps) / len(gaps),
                'stocks': stocks,
            })

    # 分档: 1% 粒度, 两端开放
    edges = list(range(-6, 7))
    out = []
    out.append('=' * 80)
    out.append('竞价池平均gap信号校准表 (方案B: 池均gap二次确认)')
    out.append('口径: T-1涨停股 → T日竞价平均gap → 当日表现 (3年, 剔除300/301/688/8/9)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 交易日: {len(day_rows)}')
    out.append('=' * 80)
    out.append(f"{'池均gap档':<12} {'交易日':>6} {'当日均收益':>9} {'隔夜均gap':>9} {'盘中均收益':>9} {'上涨占比':>8} {'当日晋级率':>9}")
    out.append('-' * 80)

    buckets = defaultdict(list)
    for dr in day_rows:
        g = dr['avg_gap']
        if g < -6:
            buckets['<-6%'].append(dr)
        elif g >= 6:
            buckets['>=6%'].append(dr)
        else:
            for i, lo in enumerate(edges):
                hi = edges[i + 1] if i + 1 < len(edges) else None
                if hi is not None and lo <= g < hi:
                    buckets[f'{lo:+d}~{hi:+d}%'].append(dr)
                    break

    order = ['<-6%'] + [f'{lo:+d}~{lo+1:+d}%' for lo in edges[:-1]] + ['>=6%']
    for label in order:
        items = buckets.get(label, [])
        if len(items) < 5:
            continue
        all_stocks = [s for dr in items for s in dr['stocks']]
        n_stocks = len(all_stocks)
        ret_total = sum(s['ret_total'] for s in all_stocks) / n_stocks
        avg_gap = sum(s['gap'] for s in all_stocks) / n_stocks
        ret_intra = sum(s['ret_intra'] for s in all_stocks) / n_stocks
        up_ratio = sum(1 for s in all_stocks if s['ret_total'] > 0) / n_stocks * 100
        lu_ratio = sum(1 for s in all_stocks if s['lu_t']) / n_stocks * 100
        out.append(f'{label:<12} {len(items):>6} {ret_total:>+8.2f}% {avg_gap:>+8.2f}% '
                   f'{ret_intra:>+8.2f}% {up_ratio:>7.0f}% {lu_ratio:>8.0f}%')

    out.append('')
    out.append('注: 当日均收益=close_T/close_{T-1}-1 (隔夜+盘中); 晋级率=T日涨停占比')
    out.append('信号用法: 竞价面板9:25算池均gap, 查表得当日预期 → 决定环境降档/维持')
    with open(os.path.join(BASE, 'logs', 'pool_avg_gap_analysis.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/pool_avg_gap_analysis.txt')


if __name__ == '__main__':
    main()
