"""交易员A选股特征 vs 模型规则 差异分析 (2026-08-25)
问题: A推荐了楚天龙(8.1%竞价/13分)而模型没有 — A的77笔里有多少类似案例?
方法: 用本地K线回算A的77笔买入日特征(竞价gap/连板/量比/涨停/环境), 对照模型过滤规则
输出: logs/trader_a_gap_analysis.txt
"""
import json, os
from datetime import datetime
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIRS = [os.path.join(BASE, 'data', 'kline_data'),
              os.path.join(BASE, 'data', 'backtest_kline')]
START, END = '2026-02-20', '2026-08-19'


def is_lu(pct, name):
    if pct is None:
        return False
    if 'ST' in (name or ''):
        return pct >= 4.85
    return pct >= 9.8


def load_all():
    """{code: (name, {date: row})} + name→code映射"""
    tbl = {}
    name_map = {}
    for d in KLINE_DIRS:
        for fn in os.listdir(d):
            if not fn.endswith('.json') or fn.startswith('._'):
                continue
            code = fn.replace('.json', '')
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
                t[date] = {
                    'open': op, 'high': float(r.get('high', 0) or 0),
                    'low': float(r.get('low', 0) or 0), 'close': cl,
                    'gap': gap, 'pct': r.get('pct_change'),
                    'vol': float(r.get('volume_lots', 0) or 0),
                }
                pc = cl
            if t:
                tbl[code] = (name, t)
                name_map[name] = code
    return tbl, name_map


def main():
    print('加载K线...')
    tbl, name_map = load_all()
    print(f'{len(tbl)}只')

    with open(os.path.join(BASE, 'logs', 'trader_a.json'), encoding='utf-8') as f:
        ta = json.load(f)
    history = ta.get('trade_history', [])

    # 每日涨停数
    pool = defaultdict(set)
    for code, (name, t) in tbl.items():
        for date, r in t.items():
            if is_lu(r['pct'], name):
                pool[date].add(code)
    days_all = sorted(pool.keys())

    out = []
    out.append('=' * 84)
    out.append('交易员A选股特征 vs 模型规则 差异分析 (77笔, 2026-03~07)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    out.append('=' * 84)

    rows = []
    unmatched = []
    for t in history:
        name = t.get('name', '')
        bd = t.get('buy_date', '')
        code = name_map.get(name)
        if not code:
            unmatched.append(name)
            continue
        _, kt = tbl[code]
        r = kt.get(bd)
        if not r:
            unmatched.append(f'{name}({bd}无K线)')
            continue
        # 买入日特征
        lu_t = is_lu(r['pct'], name)
        # 连板数(买入日)
        cons = 0
        if lu_t:
            # 找当日是连续第几板: 用前一天是否涨停回算
            dl = sorted(kt.keys())
            idx = dl.index(bd)
            cons = 1
            j = idx - 1
            while j >= 0:
                if is_lu(kt[dl[j]]['pct'], name):
                    cons += 1
                    j -= 1
                else:
                    break
        # 量比
        dl = sorted(kt.keys())
        idx = dl.index(bd)
        vols = [kt[dl[k]]['vol'] for k in range(max(0, idx - 5), idx) if kt[dl[k]]['vol'] > 0]
        vr5 = r['vol'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 0
        # 环境
        n_zt = len(pool.get(bd, set()))
        rows.append({
            'name': name, 'code': code, 'bd': bd,
            'gap': r['gap'], 'lu_t': lu_t, 'cons': cons, 'vr5': vr5,
            'n_zt': n_zt, 'pnl': t.get('pnl_pct'),
        })

    n = len(rows)
    out.append(f'成功匹配 {n} 笔 | 未匹配: {unmatched}')
    out.append('')

    # 1. 竞价gap分布 vs 模型窗口4-8%
    out.append('[1] 买入日竞价gap分布 vs 模型窗口4-8%')
    gap_bins = [(-99, 0, '低开<0%'), (0, 4, '小高开0-4%'), (4, 6, '4-6%'), (6, 8, '6-8%(窗口内)'),
                (8, 10, '8-10%(超上限)'), (10, 99, '一字≥10%')]
    for lo, hi, label in gap_bins:
        items = [x for x in rows if x['gap'] is not None and lo <= x['gap'] < hi]
        if not items:
            continue
        pnls = [x['pnl'] for x in items if x['pnl'] is not None]
        pnl_str = f'均盈亏{sum(pnls)/len(pnls):+.1f}%' if pnls else '盈亏未知'
        out.append(f'  {label:<14} {len(items):>3}笔 ({len(items)/n*100:.0f}%) | {pnl_str}')

    # 2. 被模型过滤的比例(窗口外或评分不足)
    out.append('\n[2] 模型过滤规则对照:')
    out_filter = []
    for x in rows:
        reasons = []
        if x['gap'] is not None and not (4.0 <= x['gap'] <= 8.0):
            reasons.append(f'gap{x["gap"]:+.1f}%超窗口')
        if x['cons'] >= 4:
            reasons.append(f'{x["cons"]}板高危')
        if x['vr5'] >= 5:
            reasons.append(f'量比{x["vr5"]:.1f}巨量')
        if reasons:
            out_filter.append((x, reasons))
    out.append(f'  77笔中被模型规则过滤: {len(out_filter)}笔 ({len(out_filter)/n*100:.0f}%)')
    for x, reasons in out_filter:
        pnl = f'{x["pnl"]:+.1f}%' if x['pnl'] is not None else '?'
        out.append(f'    {x["bd"]} {x["name"]} gap{x["gap"]:+.1f}% {x["cons"]}板 vr{x["vr5"]:.1f} '
                   f'涨停{x["n_zt"]}只 盈亏{pnl} | {"+".join(reasons)}')

    # 3. 被过滤笔的盈亏 vs 未过滤笔
    out.append('\n[3] 盈亏对比: 被过滤 vs 未被过滤')
    for label, cond in (('被模型过滤', out_filter), ('通过模型规则', [(x, []) for x in rows if x not in [y[0] for y in out_filter]])):
        items = [x for x, _ in cond] if label == '被模型过滤' else [x for x, _ in cond]
        pnls = [x['pnl'] for x in items if x['pnl'] is not None]
        if pnls:
            wins = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            out.append(f'  {label}: {len(items)}笔 胜率{wins:.0f}% 均{sum(pnls)/len(pnls):+.2f}%')
        else:
            out.append(f'  {label}: {len(items)}笔 (盈亏无数据)')

    # 4. 环境分布
    out.append('\n[4] 买入日市场环境(当日涨停数):')
    env_bins = [(0, 60, '弱市<60'), (60, 110, '正常60-109'), (110, 999, '强势≥110')]
    for lo, hi, label in env_bins:
        items = [x for x in rows if lo <= x['n_zt'] < hi]
        if not items:
            continue
        pnls = [x['pnl'] for x in items if x['pnl'] is not None]
        pnl_str = f'均{sum(pnls)/len(pnls):+.1f}%' if pnls else ''
        out.append(f'  {label}: {len(items)}笔 ({len(items)/n*100:.0f}%) {pnl_str}')

    with open(os.path.join(BASE, 'logs', 'trader_a_gap_analysis.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/trader_a_gap_analysis.txt')


if __name__ == '__main__':
    main()
