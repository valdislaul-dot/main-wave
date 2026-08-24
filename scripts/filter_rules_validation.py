"""三项筛选规则验证 (2026-08-24, 3年K线)
#4 最高板条件: 涨停数×最高板 二维期望表
#2 买入窗口上限: 8-10%高开的完整期望(当日封板率+次日收益)
#3 4板+过滤: 4板+一字/T字 vs 不过滤的次日表现
输出: logs/filter_rules_validation.txt
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
                t[date] = {
                    'open': op, 'high': float(r.get('high', 0) or 0),
                    'low': float(r.get('low', 0) or 0), 'close': cl,
                    'gap': gap, 'pct': r.get('pct_change'),
                }
                pc = cl
            if t:
                tbl[code] = (name, t)
    return tbl


def main():
    print('加载K线...')
    tbl = load_all()
    print(f'{len(tbl)}只')

    # 每日涨停池+连板
    pool = defaultdict(set)
    for code, (name, t) in tbl.items():
        for date, r in t.items():
            if is_lu(r['pct'], name):
                pool[date].add(code)
    days = sorted(pool.keys())
    prev = {}
    cons_map = {}
    for d in days:
        for c in pool[d]:
            cons_map[(d, c)] = prev.get(c, 0)
        prev = {c: prev.get(c, 0) + 1 for c in pool[d]}

    out = []
    out.append('=' * 84)
    out.append('三项筛选规则验证 (3年, 剔除300/301/688/8/9)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    out.append('=' * 84)

    # ============ #4 涨停数×最高板 二维 ============
    out.append('\n【#4】涨停数 × 最高板 → 竞价4-8%买入的T开盘→T+1收盘期望')
    buckets = defaultdict(list)
    for i, d in enumerate(days):
        n = len(pool[d])
        maxc = max((cons_map[(d, c)] + 1 for c in pool[d]), default=1)
        if i + 1 >= len(days):
            continue
        d1 = days[i + 1]
        key = (f'涨停{n // 20 * 20}-{(n // 20 + 1) * 20 - 1}', f'最高{maxc}板')
        for code in tbl:
            name, t = tbl[code]
            r = t.get(d)
            if not r or r['gap'] is None or not (4.0 <= r['gap'] <= 8.0):
                continue
            r1 = t.get(d1)
            if not r1 or r1['close'] <= 0:
                continue
            cum = (r1['close'] - r['open']) / r['open'] * 100
            buckets[key].append(cum)
    out.append(f'  {"环境组合":<24} {"样本":>6} {"期望":>8}')
    for key in sorted(buckets, key=lambda k: int(k[0][2:].split('-')[0])):
        items = buckets[key]
        if len(items) < 80:
            continue
        m = sum(items) / len(items)
        out.append(f'  {key[0]}+{key[1]:<6} {len(items):>6} {m:>+7.2f}%')

    # ============ #2 买入窗口上限8% ============
    out.append('\n【#2】买入窗口上限验证: 竞价8-10% vs 4-8% 完整期望')
    for lo, hi, label in ((4, 8, '现行窗口4-8%'), (8, 10, '疑似遗漏8-10%')):
        items = []
        for i, d in enumerate(days):
            if i + 1 >= len(days):
                continue
            d1 = days[i + 1]
            for code in tbl:
                name, t = tbl[code]
                r = t.get(d)
                if not r or r['gap'] is None or not (lo <= r['gap'] < hi):
                    continue
                ret_t = (r['close'] - r['open']) / r['open'] * 100
                lu_t = is_lu(r['pct'], name)
                r1 = t.get(d1)
                if not r1 or r1['open'] <= 0 or r1['close'] <= 0:
                    continue
                ret_t1 = (r1['close'] - r1['open']) / r1['open'] * 100
                items.append({'ret_t': ret_t, 'lu_t': lu_t, 'cum': ret_t + ret_t1})
        if len(items) < 100:
            continue
        n = len(items)
        lu_rate = sum(1 for x in items if x['lu_t']) / n * 100
        mean_t = sum(x['ret_t'] for x in items) / n
        mean_cum = sum(x['cum'] for x in items) / n
        out.append(f'  {label}: {n}笔 当日封板率{lu_rate:.0f}% 当日均{mean_t:+.2f}% '
                   f'T开盘→T+1收盘{mean_cum:+.2f}%')

    # ============ #3 4板+过滤 ============
    # 注: 竞价4-8%窗口内的股票open≈+4~8%, 不可能是一字(一字=开在涨停价≈+10%)
    # 正确验证口径: 全部4板+涨停股按当日板型分组(一字/T字/换手板), 比较次日表现
    out.append('\n【#3】4板+一字/T字板过滤规则验证 (全部4板+涨停股按板型分组)')
    # 先识别每日涨停股的一字/T字(用当日K线)
    board_type_map = {}   # (date, code) -> '一字'|'T字'|'换手'
    for code, (name, t) in tbl.items():
        for i, d in enumerate(sorted(t.keys())):
            if i == 0:
                continue
            r = t[d]
            if not is_lu(r['pct'], name):
                continue
            dlist = sorted(t.keys())
            idx = dlist.index(d)
            prev_c = t[dlist[idx - 1]]['close']
            lu_price = round(prev_c * 1.10, 2)
            is_yz = (r['open'] >= lu_price - 0.005 and r['high'] >= lu_price - 0.005
                     and r['low'] >= lu_price - 0.005)
            is_tz = (r['open'] >= lu_price - 0.005 and r['close'] >= lu_price - 0.005
                     and r['low'] < lu_price - 0.005)
            board_type_map[(d, code)] = '一字' if is_yz else ('T字' if is_tz else '换手')
    for label, bt in (('4板+ 换手板', '换手'), ('4板+ T字板', 'T字'), ('4板+ 一字板', '一字')):
        items = []
        for i, d in enumerate(days):
            if i + 1 >= len(days):
                continue
            d1 = days[i + 1]
            for c in pool[d]:
                cons = cons_map[(d, c)] + 1
                if cons < 4:
                    continue
                if board_type_map.get((d, c)) != bt:
                    continue
                _, t = tbl.get(c, ('', {}))
                r = t.get(d)
                r1 = t.get(d1)
                if not r or not r1 or r1['close'] <= 0 or r1['open'] <= 0 or r['open'] <= 0:
                    continue
                ret_t1 = (r1['close'] - r1['open']) / r1['open'] * 100
                # 可买性口径: 次日竞价gap 4-8%时次日开盘买入
                items.append({'ret_t1': ret_t1, 'lu_t': is_lu(r1['pct'], '')})
        if len(items) < 20:
            out.append(f'  {label}: 样本不足({len(items)})')
            continue
        m = sum(x['ret_t1'] for x in items) / len(items)
        wins = sum(1 for x in items if x['ret_t1'] > 0) / len(items) * 100
        lu1 = sum(1 for x in items if x['lu_t']) / len(items) * 100
        out.append(f'  {label}: {len(items)}笔 次日开盘→收盘均{m:+.2f}% 正收益{wins:.0f}% 次日晋级{lu1:.0f}%')

    with open(os.path.join(BASE, 'logs', 'filter_rules_validation.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/filter_rules_validation.txt')


if __name__ == '__main__':
    main()
