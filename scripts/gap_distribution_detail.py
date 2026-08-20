"""涨停股次日gap细分档 — 1%粒度 × 环境分层
数据: 3年(2023-08~2026-08) 涨停股 close→次日open gap 与次日收盘表现
输出: logs/gap_distribution_detail.txt
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

    pool = defaultdict(set)
    for code, (name, t) in tbl.items():
        for date, r in t.items():
            if is_lu(r['pct'], name):
                pool[date].add(code)
    days = sorted(pool.keys())

    rows = []   # {env, gap1, ret1, lu_t1}
    for i, d in enumerate(days):
        n = len(pool[d])
        env = '弱市' if n < 40 else ('强势' if n >= 70 else '正常')
        if i + 1 >= len(days):
            continue
        d1 = days[i + 1]
        for c in pool[d]:
            _, t = tbl.get(c, ('', {}))
            if d not in t or d1 not in t:
                continue
            r0, r1 = t[d], t[d1]
            if r0['close'] <= 0 or r1['open'] <= 0:
                continue
            gap1 = (r1['open'] - r0['close']) / r0['close'] * 100
            ret1 = (r1['close'] - r0['close']) / r0['close'] * 100
            rows.append({'env': env, 'gap1': gap1, 'ret1': ret1,
                         'lu_t1': is_lu(r1['pct'], '')})

    # 分档边界: -10 起 1% 步长到 +10, 两端开放
    edges = list(range(-10, 11))
    def bucket_label(lo, hi):
        if hi is None:
            return f'>={lo}%'
        if lo is None:
            return f'<{hi}%'
        return f'[{lo},{hi})%'

    env_map = defaultdict(list)
    for x in rows:
        env_map[x['env']].append(x)

    out = []
    out.append('=' * 78)
    out.append('涨停股次日gap细分档 — 3年 (2023-08~2026-08, 剔除300/301/688/8/9)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 全量样本: {len(rows)}')
    out.append('=' * 78)
    out.append(f"{'次日gap档':<12} {'样本':>6} {'次日上涨率':>8} {'次日均收益':>9} {'次日晋级率':>9}")
    out.append('-' * 78)

    def emit(prefix, items, out):
        total_buckets = 0
        for i, lo in enumerate(edges):
            hi = edges[i + 1] if i + 1 < len(edges) else None
            lo_v, hi_v = lo, hi
            if lo is None:
                continue
            if i == 0:
                bucket = [x for x in items if x['gap1'] < lo]
                label = f'<-10%'
            elif hi is None:
                bucket = [x for x in items if x['gap1'] >= lo]
                label = f'>={lo}%'
            else:
                bucket = [x for x in items if lo <= x['gap1'] < hi]
                label = f'{lo:+d}~{hi:+d}%'
            if len(bucket) < 30:
                continue
            wins = sum(1 for x in bucket if x['ret1'] > 0)
            mean = sum(x['ret1'] for x in bucket) / len(bucket)
            lu = sum(1 for x in bucket if x['lu_t1']) / len(bucket) * 100
            out.append(f'{label:<12} {len(bucket):>6} {wins/len(bucket)*100:>7.0f}% {mean:>+8.2f}% {lu:>8.0f}%')
            total_buckets += 1
        return total_buckets

    for env in ('全量', '弱市', '正常', '强势'):
        out.append(f'\n【{env}】')
        items = rows if env == '全量' else env_map[env]
        emit('', items, out)

    with open(os.path.join(BASE, 'logs', 'gap_distribution_detail.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/gap_distribution_detail.txt')


if __name__ == '__main__':
    main()
