"""市场强弱函数分析 (2026-08-25, 用户要求: 找代表性/关联性最强的强弱指标, 替代涨停数硬边界)
候选指标(每日, K线回算, 3年):
  zt_n 涨停数 | upgrade 晋级率(昨涨停今涨停占比) | money_effect 赚钱效应(昨涨停股今日均收益)
  max_cons 最高板 | cons2_ratio 2板+占比 | avg_gap 昨涨停股今日竞价均gap
目标: 当日「竞价4-8%买入池」的T开盘→T+1收盘期望 (日级)
方法: 各指标按日值分档(每档≥20天), 看档间期望单调性 + 斯皮尔曼相关
输出: logs/market_strength_indicator.txt
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


def spearman(xs, ys):
    """斯皮尔曼相关"""
    n = len(xs)
    if n < 10:
        return 0
    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0] * n
        i = 0
        while i < n:
            j = i
            while j < n and v[order[j]] == v[order[i]]:
                j += 1
            avg = (i + j - 1) / 2 + 1
            for k in range(i, j):
                r[order[k]] = avg
            i = j
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    vy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    return cov / (vx * vy) if vx * vy > 0 else 0


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

    # 连板
    prev = {}
    cons_map = {}
    for d in days:
        for c in pool[d]:
            cons_map[(d, c)] = prev.get(c, 0)
        prev = {c: prev.get(c, 0) + 1 for c in pool[d]}

    # 每日指标 + 目标(当日竞价4-8%买入期望)
    day_rows = []
    for i, d in enumerate(days):
        if i == 0 or i + 1 >= len(days):
            continue
        d0, d1 = days[i - 1], days[i + 1]
        zt_n = len(pool[d])
        max_cons = max((cons_map[(d, c)] + 1 for c in pool[d]), default=1)
        cons2 = sum(1 for c in pool[d] if cons_map[(d, c)] + 1 >= 2)
        # 晋级率: 昨涨停今日涨停占比
        yest = pool[d0]
        upgrade = sum(1 for c in yest if c in pool[d]) / len(yest) if yest else 0
        # 赚钱效应: 昨日涨停股今日均收益(close_d/close_d0-1)
        rets = []
        gaps = []
        for c in yest:
            _, t = tbl.get(c, ('', {}))
            r0, r1 = t.get(d0), t.get(d)
            if r0 and r1 and r0['close'] > 0 and r1['close'] > 0:
                rets.append((r1['close'] - r0['close']) / r0['close'] * 100)
                gaps.append((r1['open'] - r0['close']) / r0['close'] * 100)
        money_effect = sum(rets) / len(rets) if rets else 0
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        # 目标: 当日竞价4-8%股票的T开盘→T+1收盘期望
        targets = []
        for code in tbl:
            name, t = tbl[code]
            r = t.get(d)
            if not r or r['gap'] is None or not (4.0 <= r['gap'] <= 8.0):
                continue
            r1 = t.get(d1)
            if r1 and r1['close'] > 0:
                targets.append((r1['close'] - r['open']) / r['open'] * 100)
        target = sum(targets) / len(targets) if len(targets) >= 5 else None
        if target is None:
            continue
        day_rows.append({
            'date': d, 'zt_n': zt_n, 'upgrade': upgrade, 'money_effect': money_effect,
            'max_cons': max_cons, 'cons2_ratio': cons2 / zt_n if zt_n else 0,
            'avg_gap': avg_gap, 'target': target,
        })

    out = []
    out.append('=' * 84)
    out.append('市场强弱函数分析 — 各指标 vs 当日竞价4-8%买入期望 (3年)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 有效交易日: {len(day_rows)}')
    out.append('=' * 84)

    indicators = {
        'zt_n': ('涨停数', [(0, 40), (40, 60), (60, 80), (80, 110), (110, 999)]),
        'upgrade': ('晋级率', [(0, .15), (.15, .25), (.25, .35), (.35, .5), (.5, 1)]),
        'money_effect': ('赚钱效应%', [(-99, -2), (-2, 0), (0, 2), (2, 4), (4, 99)]),
        'avg_gap': ('池均gap%', [(-99, -1), (-1, 0), (0, 1), (1, 2), (2, 99)]),
        'max_cons': ('最高板', [(0, 3), (3, 5), (5, 7), (7, 10), (10, 99)]),
        'cons2_ratio': ('2板+占比', [(0, .15), (.15, .3), (.3, .5), (.5, .7), (.7, 1)]),
    }

    results = []
    for key, (label, bins) in indicators.items():
        out.append(f'\n【{label}】分档 vs 买入期望:')
        means = []
        for lo, hi in bins:
            items = [x for x in day_rows if lo <= x[key] < hi]
            if len(items) < 20:
                continue
            m = sum(x['target'] for x in items) / len(items)
            means.append((lo, hi, len(items), m))
            out.append(f'  [{lo:>5},{hi:>5}): {len(items):>4}天 期望{m:>+6.2f}%')
        if len(means) >= 3:
            # 单调性: 档间期望的相关系数
            sp = spearman([x[key] for x in day_rows], [x['target'] for x in day_rows])
            out.append(f'  斯皮尔曼相关: {sp:+.3f}')
            results.append((abs(sp), label, sp))
    out.append('\n' + '=' * 84)
    out.append('指标关联强度排序 (|斯皮尔曼|):')
    for abs_sp, label, sp in sorted(results, reverse=True):
        out.append(f'  {label}: {sp:+.3f}')
    with open(os.path.join(BASE, 'logs', 'market_strength_indicator.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/market_strength_indicator.txt')


if __name__ == '__main__':
    main()
