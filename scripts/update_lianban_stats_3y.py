"""
连板延续概率统计 — 3年样本（本地K线回算版）
区间: 2023-08-19 → 2026-08-19
数据源: 本地K线 (kline_data/ 3045只 + backtest_kline/ 70只, 搜狐10年不复权, pct_change字段)
涨停判定: pct_change ≥ 9.8 (主板10%) | ST股 ≥ 4.85 (5%)
口径校验: 2025-08-19 同花顺涨停池85只中, 主板74只K线回算100%命中(漏判11只全为300/688/301已剔除)
输出: logs/full_market_lianban_3y.txt
"""
import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIRS = [os.path.join(BASE, 'data', 'kline_data'),
              os.path.join(BASE, 'data', 'backtest_kline')]

STAT_START = '2023-08-19'
STAT_END = '2026-08-19'
WARMUP_DAYS = 15


def is_limit_up(pct, name) -> bool:
    """涨停判定: 主板10%(pct≥9.8) | ST 5%(pct≥4.85)。300/301/688/8/9 剔除在调用方"""
    if pct is None:
        return False
    if 'ST' in (name or ''):
        return pct >= 4.85
    return pct >= 9.8


def collect_pools():
    """逐文件读本地K线 → {date_ymd: set(codes)}，只保留统计区间+预热期"""
    from datetime import datetime as dt
    warm_start = (dt.strptime(STAT_START, '%Y-%m-%d')
                  - timedelta(days=WARMUP_DAYS * 2 + 10)).strftime('%Y-%m-%d')

    pool = defaultdict(set)
    n_files = 0
    for d in KLINE_DIRS:
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.json'):
                continue
            code = fn.replace('.json', '')
            if code.startswith(('300', '301', '688', '8', '9')):
                continue   # 口径剔除
            try:
                with open(os.path.join(d, fn), encoding='utf-8') as f:
                    j = json.load(f)
            except Exception:
                continue
            name = (j.get('metadata') or {}).get('name', '')
            data = j.get('data') or []
            for x in data:
                date = x.get('date', '')
                if not (warm_start <= date <= STAT_END):
                    continue
                if is_limit_up(x.get('pct_change'), name):
                    pool[date].add(code)
            n_files += 1
    return pool, n_files


def analyze(pool):
    """回算连板 + 统计延续概率（预热期不统计）"""
    days = sorted(d for d in pool if d <= STAT_END)
    prev = {}
    for day in days:
        if day < STAT_START:   # 预热期只更新状态
            prev = {c: prev.get(c, 0) + 1 for c in pool[day]}
            continue
        break
    stat_days = [d for d in days if d >= STAT_START]
    print(f'统计区间 {STAT_START}~{STAT_END}: {len(stat_days)} 个交易日有涨停数据')

    transitions = defaultdict(lambda: [0, 0])
    for i, day in enumerate(stat_days):
        nxt = pool[stat_days[i + 1]] if i + 1 < len(stat_days) else set()
        for code in pool[day]:
            cons = prev.get(code, 0)
            transitions[cons][0] += 1
            if code in nxt:
                transitions[cons][1] += 1
        prev = {c: prev.get(c, 0) + 1 for c in pool[day]}
    return transitions


def main():
    pool, n_files = collect_pools()
    print(f'读取K线文件: {n_files} 只 | 涨停事件日: {len(pool)} 天')
    transitions = analyze(pool)

    out_path = os.path.join(BASE, 'logs', 'full_market_lianban_3y.txt')
    lines = ['=' * 65,
             '全市场连板延续概率 (3年, 2023-08至2026-08, 剔除300/301/688/8/9)',
             f'数据源: 本地K线回算(搜狐10年不复权, {n_files}只) | 生成: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
             '=' * 65 + '',
             f"{'当前位置':<12} {'总样本':>8} {'延续':>8} {'概率':>10} {'趋势':>10}",
             '-' * 52]

    for cons in sorted(transitions.keys())[:14]:
        t, n = transitions[cons]
        if t >= 5:
            prob = n / t * 100
            label = f'{cons+1}板->{cons+2}板' if cons > 0 else '首板->2板'
            bar = '#' * int(prob / 5)
            lines.append(f'{label:<12} {t:>8} {n:>8} {prob:>9.1f}% {bar}')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'Done: {out_path}')
    print('\n' + '\n'.join(lines))


if __name__ == '__main__':
    main()
