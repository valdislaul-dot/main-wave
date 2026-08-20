"""
弱市回测 v2 — 补两个关键维度:
[6] 全市场: 竞价gap 4-8% 当日收盘涨停率 (模型买入当天风险, 哈森天地板模式)
[7] 分年段稳健性: 3年分3段各1年, 验证核心结论各段一致
输出: logs/weak_market_analysis_v2.txt
"""
import json, os
from datetime import datetime
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIRS = [os.path.join(BASE, 'data', 'kline_data'),
              os.path.join(BASE, 'data', 'backtest_kline')]
START = '2023-08-19'
END = '2026-08-19'


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
            prev_close = None
            for r in rows:
                if not isinstance(r, dict):
                    continue
                date = r.get('date', '')
                if not (START <= date <= END):
                    continue
                close = float(r.get('close', 0) or 0)
                op = float(r.get('open', 0) or 0)
                if prev_close and prev_close > 0 and op > 0:
                    gap = (op - prev_close) / prev_close * 100
                else:
                    gap = None
                t[date] = {
                    'open': op, 'close': close,
                    'gap': gap,   # 当日竞价gap
                    'pct': r.get('pct_change'),
                    'vol': float(r.get('volume_lots', 0) or 0),
                }
                prev_close = close
            if t:
                tbl[code] = (name, t)
    return tbl


def env_of(n_zt, max_cons):
    if n_zt < 40 or max_cons <= 2:
        return '弱市'
    if n_zt >= 70 and max_cons >= 5:
        return '强势'
    return '正常'


def stat(items):
    if len(items) < 20:
        return None
    wins = sum(1 for x in items if x['ret1'] > 0)
    mean = sum(x['ret1'] for x in items) / len(items)
    lu = sum(1 for x in items if x['lu_t1']) / len(items) * 100
    return f'{len(items)}笔 上涨率{wins/len(items)*100:.0f}% 均{mean:+.2f}% 晋级率{lu:.0f}%'


def main():
    print('加载K线...')
    tbl = load_all()
    print(f'{len(tbl)}只')

    dates = sorted({d for _, t in tbl.values() for d in t})
    # 每日涨停池(用于环境)
    pool = defaultdict(set)
    for code, (name, t) in tbl.items():
        for date, r in t.items():
            if is_lu(r['pct'], name):
                pool[date].add(code)
    days = sorted(pool.keys())
    env_by_day = {}
    for d in days:
        env_by_day[d] = env_of(len(pool[d]), 1)   # 环境近似: 用涨停数为主
    # 精确环境: 需要最高板, 简化用涨停数分档(与面板评级<40一致)
    for d in days:
        n = len(pool[d])
        env_by_day[d] = '弱市' if n < 40 else ('强势' if n >= 70 else '正常')

    out = []
    out.append('=' * 64)
    out.append('弱市回测 v2: 竞价当日炸板风险 + 分年段稳健性检验')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    out.append('=' * 64)

    # [6] 全市场竞价gap 4-8% 当日收盘涨停率
    out.append('\n[6] 全市场: 竞价gap4-8%的股票 当日收盘涨停率 (买入当天风险)')
    by_env = defaultdict(lambda: [0, 0])
    for d in days:
        env = env_by_day[d]
        for code in tbl:
            _, t = tbl[code]
            r = t.get(d)
            if not r or r['gap'] is None:
                continue
            if 4.0 <= r['gap'] <= 8.0:
                by_env[env][0] += 1
                if is_lu(r['pct'], ''):
                    by_env[env][1] += 1
    for env in ('弱市', '正常', '强势'):
        tot, lu = by_env[env]
        if tot >= 20:
            out.append(f'  {env}: 竞价4-8%共{tot}笔, 当日涨停{lu}笔 (封板率{lu/tot*100:.0f}%, 当日炸板率{100-lu/tot*100:.0f}%)')

    # 竞价4-8% 当天未涨停的股票次日表现(炸板后次日)
    out.append('\n[6b] 竞价4-8%当日炸板股的次日表现 (哈森模式: 当天炸板, 次日如何)')
    zb_rows = []
    for code in tbl:
        name, t = tbl[code]
        dlist = sorted(t.keys())
        for i, d in enumerate(dlist):
            r = t[d]
            if r['gap'] is None or not (4.0 <= r['gap'] <= 8.0):
                continue
            if is_lu(r['pct'], name):
                continue   # 当天封住了, 不是炸板
            if i + 1 >= len(dlist):
                continue
            d1 = dlist[i + 1]
            r1 = t[d1]
            if r1['open'] <= 0:
                continue
            gap1 = (r1['open'] - r['close']) / r['close'] * 100
            ret1 = (r1['close'] - r['close']) / r['close'] * 100
            env = env_by_day.get(d, '正常')
            zb_rows.append({'env': env, 'gap1': gap1, 'ret1': ret1,
                            'lu_t1': is_lu(r1['pct'], name)})
    for env in ('弱市', '正常', '强势'):
        items = [x for x in zb_rows if x['env'] == env]
        s = stat(items)
        if s:
            out.append(f'  {env}日炸板: {s}')
        # 炸板后次日gap分层
        for lo, hi, label in ((-4, 0, '次日低开'), (0, 4, '次日平开'), (4, 8, '次日竞价窗'), (8, 99, '次日大高开')):
            sub = [x for x in items if lo <= x['gap1'] < hi]
            if len(sub) >= 20:
                wins = sum(1 for x in sub if x['ret1'] > 0)
                mean = sum(x['ret1'] for x in sub) / len(sub)
                out.append(f'    {label}: {len(sub)}笔 上涨率{wins/len(sub)*100:.0f}% 均{mean:+.2f}%')

    # [7] 分年段稳健性: 弱市日涨停股次日表现 × 次日gap分层
    out.append('\n[7] 分年段稳健性检验 (核心结论三段各验证)')
    years = [('2023-08-19', '2024-08-18', '年段1: 2023-08~2024-08'),
             ('2024-08-19', '2025-08-18', '年段2: 2024-08~2025-08'),
             ('2025-08-19', '2026-08-19', '年段3: 2025-08~2026-08')]
    for lo, hi, label in years:
        seg_days = [d for d in days if lo <= d <= hi]
        if len(seg_days) < 100:
            out.append(f'  {label}: 数据不足')
            continue
        weak_rows = []
        for d in seg_days:
            env = env_by_day[d]
            idx = days.index(d)
            if idx + 1 >= len(days):
                continue
            d1 = days[idx + 1]
            for c in pool[d]:
                _, t = tbl.get(c, ('', {}))
                if d not in t or d1 not in t:
                    continue
                r0, r1 = t[d], t[d1]
                if r0['close'] <= 0 or r1['open'] <= 0:
                    continue
                gap1 = (r1['open'] - r0['close']) / r0['close'] * 100
                ret1 = (r1['close'] - r0['close']) / r0['close'] * 100
                weak_rows.append({'gap1': gap1, 'ret1': ret1, 'env': env,
                                  'lu_t1': is_lu(r1['pct'], '')})
        out.append(f'\n  {label} ({len(seg_days)}个交易日):')
        for env in ('弱市', '正常', '强势'):
            items = [x for x in weak_rows if x['env'] == env]
            s = stat(items)
            if s:
                out.append(f'    {env}全体: {s}')
        for gl, gh, glabel in ((4, 8, '竞价窗口4-8%'), (-4, 0, '低开-4~0%')):
            w_items = [x for x in weak_rows if x['env'] == '弱市' and gl <= x['gap1'] < gh]
            s = stat(w_items)
            if s:
                out.append(f'    弱市{glabel}: {s}')

    with open(os.path.join(BASE, 'logs', 'weak_market_analysis_v2.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/weak_market_analysis_v2.txt')


if __name__ == '__main__':
    main()
