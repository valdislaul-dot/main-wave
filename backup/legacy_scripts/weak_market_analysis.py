"""
弱市历史回测 — 3年K线按市场环境分层的涨停股次日表现
问题: 模型在弱市期失效, 弱市期正确交易方式是什么?
方法: 2023-08-19~2026-08-19 每日涨停池(K线回算) → 环境分类 → 次日表现 → 弱市子集特征
环境分类(与竞价面板一致): 弱市=涨停<40或最高≤2板 | 强势=≥70且≥5板 | 其余正常
输出: logs/weak_market_analysis.txt
"""
import json, os
from datetime import datetime, timedelta
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
    """{code: {date: {open, close, pct, vol, name}}} 内存表"""
    tbl = {}
    n_bad = 0
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
                n_bad += 1
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
                    'vol': float(r.get('volume_lots', 0) or 0),
                }
            if t:
                tbl[code] = (name, t)
    return tbl, n_bad


def main():
    print('加载K线...')
    tbl, n_bad = load_all()
    print(f'K线表: {len(tbl)}只 (坏文件{n_bad})')

    # 逐日涨停池 + 环境
    dates = sorted({d for _, t in tbl.values() for d in t})
    pool = defaultdict(set)   # date -> codes
    for code, (name, t) in tbl.items():
        for date, r in t.items():
            if is_lu(r['pct'], name):
                pool[date].add(code)
    days = sorted(pool.keys())
    print(f'涨停事件日: {len(days)}')

    # 连板数回算
    streak = {}
    cons_map = {}   # (date, code) -> cons(不含当日的前序连续数)
    prev = {}
    for d in days:
        for c in pool[d]:
            cons_map[(d, c)] = prev.get(c, 0)
        prev = {c: prev.get(c, 0) + 1 for c in pool[d]}

    # 环境分类 + 次日表现
    rows = []   # {date, code, env, cons, gap_t1, ret_t1, lu_t1}
    for i, d in enumerate(days):
        n = len(pool[d])
        max_cons = max((cons_map[(d, c)] + 1 for c in pool[d]), default=1)
        if n < 40 or max_cons <= 2:
            env = '弱市'
        elif n >= 70 and max_cons >= 5:
            env = '强势'
        else:
            env = '正常'
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
            cons = cons_map[(d, c)]
            rows.append({
                'env': env, 'cons': cons, 'gap1': gap1, 'ret1': ret1,
                'lu_t1': is_lu(r1['pct'], ''),   # 次日涨停
            })

    print(f'样本: {len(rows)}')

    def stat(label, items):
        if len(items) < 20:
            print(f'  {label}: {len(items)}笔(样本不足)')
            return
        wins = sum(1 for x in items if x['ret1'] > 0)
        mean = sum(x['ret1'] for x in items) / len(items)
        lu = sum(1 for x in items if x['lu_t1']) / len(items) * 100
        print(f'  {label}: {len(items)}笔 次日上涨率{wins/len(items)*100:.0f}% 均{mean:+.2f}% 晋级率{lu:.0f}%')

    out = []
    out.append('=' * 62)
    out.append('弱市历史回测 — 3年涨停股次日表现按环境分层 (2023-08~2026-08)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 样本: {len(rows)}')
    out.append('=' * 62)

    # 1. 环境分层
    out.append('\n[1] 环境分层: 任意涨停股次日表现')
    env_map = defaultdict(list)
    for x in rows:
        env_map[x['env']].append(x)
    for env in ('弱市', '正常', '强势'):
        items = env_map[env]
        if len(items) < 20:
            out.append(f'  {env}: {len(items)}笔(样本不足)')
            continue
        wins = sum(1 for x in items if x['ret1'] > 0)
        mean = sum(x['ret1'] for x in items) / len(items)
        lu = sum(1 for x in items if x['lu_t1']) / len(items) * 100
        gap_mean = sum(x['gap1'] for x in items) / len(items)
        out.append(f'  {env}: {len(items)}笔 次日上涨率{wins/len(items)*100:.0f}% 均{mean:+.2f}% '
                   f'晋级率{lu:.0f}% 次日均gap{gap_mean:+.2f}%')

    # 2. 环境 × 连板数
    out.append('\n[2] 环境×连板数: 次日均收益')
    for env in ('弱市', '正常', '强势'):
        for cons in (0, 1, 2):
            items = [x for x in env_map[env] if x['cons'] == cons]
            if len(items) >= 20:
                wins = sum(1 for x in items if x['ret1'] > 0)
                mean = sum(x['ret1'] for x in items) / len(items)
                lu = sum(1 for x in items if x['lu_t1']) / len(items) * 100
                out.append(f'  {env} {cons+1}板: {len(items)}笔 上涨率{wins/len(items)*100:.0f}% '
                           f'均{mean:+.2f}% 晋级率{lu:.0f}%')

    # 3. 弱市内的次日gap分层(竞价4-8%窗口对应T日买入位置的次日)
    out.append('\n[3] 弱市日涨停股: 按次日gap分层 (模拟竞价窗口可买性)')
    weak = env_map['弱市']
    for lo, hi, label in ((-10, -4, '深水低开<-4%'), (-4, 0, '低开-4~0%'), (0, 4, '平开/小高开0-4%'),
                          (4, 8, '竞价窗口4-8%'), (8, 100, '大高开>8%')):
        items = [x for x in weak if lo <= x['gap1'] < hi]
        if len(items) >= 20:
            wins = sum(1 for x in items if x['ret1'] > 0)
            mean = sum(x['ret1'] for x in items) / len(items)
            lu = sum(1 for x in items if x['lu_t1']) / len(items) * 100
            out.append(f'  {label}: {len(items)}笔 上涨率{wins/len(items)*100:.0f}% 均{mean:+.2f}% 晋级率{lu:.0f}%')

    # 4. 弱市按连板数的次日gap分层(深水自救检验: 3板内深水低开是否值得等)
    out.append('\n[4] 弱市: 深水低开(gap<-4%)按连板数 (卖点引擎深水自救规则的弱市检验)')
    deep = [x for x in weak if x['gap1'] < -4]
    for cons in (0, 1, 2, 3):
        items = [x for x in deep if x['cons'] == cons]
        if len(items) >= 10:
            wins = sum(1 for x in items if x['ret1'] > 0)
            mean = sum(x['ret1'] for x in items) / len(items)
            out.append(f'  {cons+1}板: {len(items)}笔 上涨率{wins/len(items)*100:.0f}% 均{mean:+.2f}%')
    if len(deep) >= 20:
        wins = sum(1 for x in deep if x['ret1'] > 0)
        mean = sum(x['ret1'] for x in deep) / len(deep)
        out.append(f'  全部深水: {len(deep)}笔 上涨率{wins/len(deep)*100:.0f}% 均{mean:+.2f}%')

    # 5. 各月弱市天数(弱市密度)
    out.append('\n[5] 月度弱市日占比 (模型最难受的月份)')
    month_env = defaultdict(lambda: [0, 0])
    for i, d in enumerate(days):
        n = len(pool[d])
        max_cons = max((cons_map[(d, c)] + 1 for c in pool[d]), default=1)
        env = '弱市' if (n < 40 or max_cons <= 2) else '其他'
        m = d[:7]
        month_env[m][0] += 1
        if env == '弱市':
            month_env[m][1] += 1
    for m in sorted(month_env):
        t, w = month_env[m]
        if w >= 3:
            out.append(f'  {m}: 弱市{w}/{t}天 ({w/t*100:.0f}%)')

    with open(os.path.join(BASE, 'logs', 'weak_market_analysis.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/weak_market_analysis.txt')


if __name__ == '__main__':
    main()
