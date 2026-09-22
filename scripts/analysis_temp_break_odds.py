"""连板断板概率阶梯 + 断板日代价 + 过夜期望 (2026-09-21 用户问)

用户问: "妖股多少连板后下一交易日断板的概率"
背景: 用户做短线, 连板阶段前端买入, 出现断板即卖出 → 真正要的是"我拿在手里时,
      明天断板的概率有多大 + 断板那天亏多少"

口径: 事件法(逐"k板日"), 无幸存者偏差 —— 与 analysis_temp_streak_ladder.py 的段口径不同,
      段口径必须丢弃未结束段(817个), 会把"正在走的强票"整体排除, 低估右尾
      仅保留"连板段起点 >= 第40根K线"的样本(与段脚本同守卫), 排除新股上市连板
      晋级判定 is_lu 与既有一致(创业板/科创板 20% 口径)
分组: 训练段 <2023 / 检验段 >=2023 (同 妖股理论验证报告 §七/§八)
只读本地 data/kline_data/, 不做网络抓取
"""
import json, os, sys, glob

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
IPO_GUARD = 40
SPLIT = '2023-01-01'
MAXK = 12


def is_lu(close, prev_close, cyb):
    limit_price = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit_price - 0.005


def stat(vals):
    if not vals:
        return None
    s = sorted(vals)
    return {'n': len(vals), 'mean': sum(vals) / len(vals), 'med': s[len(s) // 2],
            'up': sum(1 for v in vals if v > 0) / len(vals) * 100}


def main():
    files = [f for f in glob.glob(os.path.join(KLINE_DIR, '*.json')) if os.path.basename(f)[:-5].isdigit()]
    print(f'K线库: {len(files)} 只')
    ev = {k: [] for k in range(1, MAXK + 2)}

    for fp in files:
        code = os.path.basename(fp).replace('.json', '')
        cyb = code.startswith(('30', '68'))
        try:
            raw = json.load(open(fp, encoding='utf-8'))
            kl = raw['data'] if isinstance(raw, dict) else raw
        except Exception:
            continue
        n = len(kl)
        if n < 60:
            continue
        lu = [False] * n
        for i in range(1, n):
            c, pc = kl[i].get('close'), kl[i - 1].get('close')
            if c and pc:
                lu[i] = is_lu(c, pc, cyb)

        i = 1
        while i < n:
            if not lu[i]:
                i += 1
                continue
            start = i
            while i < n and lu[i]:
                i += 1
            if start < IPO_GUARD:
                continue
            for j in range(start, i):          # j = 该连板段的第 (j-start+1) 板
                k = j - start + 1
                if k > MAXK + 1 or j + 1 >= n:
                    continue                   # 次日不可观测 → 剔除(段尾=已断板或数据尽头)
                d, nx = kl[j], kl[j + 1]
                if not d.get('close') or not nx.get('open'):
                    continue
                prev = d['close']
                gap = (nx['open'] - prev) / prev * 100
                hi = nx.get('high') or 0
                row = {
                    'date': d['date'], 'code': code,
                    'promo': bool(lu[j + 1]),
                    'gap': gap,                                               # 次日开盘 = 开盘卖价
                    'close_ret': (nx['close'] - prev) / prev * 100,           # 次日收盘 = 收盘卖价
                    'touch': bool(nx.get('high') and is_lu(nx['high'], prev, cyb)),  # 盘中曾触板(炸板)
                    'buy_ret': None,                                          # 次日按竞价窗买入 → 再次日收盘
                    # 卖出门径对比(均相对昨收): 公式价=sell_engine 的 70%(H+O)/2+30%收盘
                    'exec_ret': ((0.7 * (hi + nx['open']) / 2 + 0.3 * nx['close'] - prev) / prev * 100) if hi else None,
                    'ho2_ret': (((hi + nx['open']) / 2 - prev) / prev * 100) if hi else None,
                    'high_ret': ((hi - prev) / prev * 100) if hi else None,
                }
                # 入场视角: 次日 gap 落在 4-8% 硬边界内 → 次日开盘买入, 再次日收盘卖(项目模拟口径)
                if j + 2 < n and 4.0 <= gap <= 8.0 and kl[j + 2].get('close'):
                    row['buy_ret'] = (kl[j + 2]['close'] - nx['open']) / nx['open'] * 100
                ev[k].append(row)
            i = i if i > start else start + 1

    rows = []
    for k in range(1, MAXK + 1):
        all_ev = ev[k]
        seg = {}
        for name, cond in (('train', lambda e: e['date'] < SPLIT), ('test', lambda e: e['date'] >= SPLIT)):
            sub = [e for e in all_ev if cond(e)]
            brk = [e for e in sub if not e['promo']]
            buys = [e['buy_ret'] for e in sub if e['buy_ret'] is not None]
            seg[name] = {
                'n': len(sub), 'promo': sum(1 for e in sub if e['promo']) / len(sub) * 100 if sub else None,
                'brk_n': len(brk),
                'brk_gap': stat([e['gap'] for e in brk]),
                'brk_close': stat([e['close_ret'] for e in brk]),
                'brk_exec': stat([e['exec_ret'] for e in brk if e['exec_ret'] is not None]),
                'brk_ho2': stat([e['ho2_ret'] for e in brk if e['ho2_ret'] is not None]),
                'brk_high': stat([e['high_ret'] for e in brk if e['high_ret'] is not None]),
                'brk_touch': sum(1 for e in brk if e['touch']) / len(brk) * 100 if brk else None,
                'ev_close': stat([e['close_ret'] for e in sub]),
                'ev_open': stat([e['gap'] for e in sub]),
                'buy': stat(buys),
            }
        rows.append((k, seg))

    print(f'\n{"="*126}')
    print('断板率阶梯 (事件法, 口径=当日收于k板, 看次日)  [次日涨停=晋级 / 未涨停=断板]')
    print('=' * 126)
    print(f"{'板级':<5}{'训练n':>7}{'训练断板率':>10} | {'检验n':>7}{'检验断板率':>10} | "
          f"{'检验·断板日开盘均':>16}{'检验·断板日收盘均':>16}{'检验·开盘为正%':>14}{'断板日摸板%':>11}")
    print('-' * 126)
    for k, seg in rows:
        t, s = seg['train'], seg['test']
        if not t['n'] or not s['n']:
            continue
        print(f"{k:<5}{t['n']:>7}{100 - t['promo']:>9.1f}% | {s['n']:>7}{100 - s['promo']:>9.1f}% | "
              f"{s['brk_gap']['mean']:>15.2f}%{s['brk_close']['mean']:>15.2f}%"
              f"{s['brk_gap']['up']:>13.0f}%{s['brk_touch']:>10.0f}%")

    # ── 卖出门径对比 (只取断板日: 公式的 70%(H+O)/2+30%收盘 分支仅在不涨停日生效) ──
    print(f'\n{"="*126}')
    print('断板日卖出门径对比 (均相对昨收; 仅统计断板日, 涨停日走"挂涨停价"分支不看此公式)')
    print('=' * 126)
    print(f"{'板级':<5}{'检验n':>7}{'①开盘卖':>10}{'②公式价':>10}{'③收盘卖':>10}"
          f"{'④半程(H+O)/2':>14}{'⑤当日最高':>11}{'②-①':>9}{'摸板%':>8} | {'训练①':>9}{'训练②':>9}{'训练③':>9}")
    print('-' * 126)
    pool_t, pool_s = [], []
    for k, seg in rows:
        t, s = seg['train'], seg['test']
        if not t['brk_exec'] or not s['brk_exec'] or not s['brk_gap']:
            continue
        pool_t.append(t)
        pool_s.append(s)
        print(f"{k:<5}{s['brk_exec']['n']:>7}{s['brk_gap']['mean']:>9.2f}%{s['brk_exec']['mean']:>9.2f}%"
              f"{s['brk_close']['mean']:>9.2f}%{s['brk_ho2']['mean']:>13.2f}%{s['brk_high']['mean']:>10.2f}%"
              f"{s['brk_exec']['mean'] - s['brk_gap']['mean']:>8.2f}%{s['brk_touch']:>7.0f}% | "
              f"{t['brk_gap']['mean']:>8.2f}%{t['brk_exec']['mean']:>8.2f}%{t['brk_close']['mean']:>8.2f}%")
    # 全板级合计(按断板笔数加权)
    def _pool(segs, key):
        n = sum(s['brk_exec']['n'] for s in segs)
        return sum(s[key]['mean'] * s['brk_exec']['n'] for s in segs) / n if n else 0
    print('-' * 126)
    print(f"{'合计':<5}{sum(s['brk_exec']['n'] for s in pool_s):>7}"
          f"{_pool(pool_s, 'brk_gap'):>9.2f}%{_pool(pool_s, 'brk_exec'):>9.2f}%{_pool(pool_s, 'brk_close'):>9.2f}%"
          f"{_pool(pool_s, 'brk_ho2'):>13.2f}%{_pool(pool_s, 'brk_high'):>10.2f}%"
          f"{_pool(pool_s, 'brk_exec') - _pool(pool_s, 'brk_gap'):>8.2f}%{'':>8} | "
          f"{_pool(pool_t, 'brk_gap'):>8.2f}%{_pool(pool_t, 'brk_exec'):>8.2f}%{_pool(pool_t, 'brk_close'):>8.2f}%")

    print(f'\n{"="*118}')
    print('过夜期望 (持仓过夜, 次日不同卖点)  [开盘卖 = 次日开盘价 vs 今收]  [收盘卖 = 次日收盘 vs 今收]')
    print('=' * 118)
    print(f"{'板级':<5}{'训练n':>7}{'训练EV(收盘)':>13}{'检验n':>7}{'检验EV(收盘)':>13} | "
          f"{'训练EV(开盘)':>13}{'检验EV(开盘)':>13} | {'检验胜率(收盘)':>14}")
    print('-' * 118)
    for k, seg in rows:
        t, s = seg['train'], seg['test']
        if not t['n'] or not s['n']:
            continue
        print(f"{k:<5}{t['n']:>7}{t['ev_close']['mean']:>12.2f}%{s['n']:>7}{s['ev_close']['mean']:>12.2f}% | "
              f"{t['ev_open']['mean']:>12.2f}%{s['ev_open']['mean']:>12.2f}% | {s['ev_close']['up']:>13.0f}%")

    print(f'\n{"="*118}')
    print('入场视角 (无选择基准): 次日 gap∈[4%,8%] → 次日开盘买入, 再次日收盘卖  [=项目模拟口径, 不含选股]')
    print('=' * 118)
    print(f"{'板级':<5}{'训练n':>7}{'训练均收益':>12}{'训练胜率':>10} | "
          f"{'检验n':>7}{'检验均收益':>12}{'检验胜率':>10}")
    print('-' * 118)
    for k, seg in rows:
        t, s = seg['train'], seg['test']
        if not t['buy'] or not s['buy']:
            continue
        print(f"{k:<5}{t['buy']['n']:>7}{t['buy']['mean']:>11.2f}%{t['buy']['up']:>9.0f}% | "
              f"{s['buy']['n']:>7}{s['buy']['mean']:>11.2f}%{s['buy']['up']:>9.0f}%")

    out = os.path.join(BASE, 'logs', 'research_break_odds.json')
    json.dump({'generated': '2026-09-21', 'split': SPLIT, 'maxk': MAXK,
               'rows': {str(k): seg for k, seg in rows}},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
