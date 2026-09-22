"""📤 卖出质量跟踪 — 卖出后走势回填 (2026-09-19)
================================================
用户痛点: "模型给出卖出结论后, 部分股票卖出后又上涨甚至涨停" → 用真实成交记录量化它。

数据: logs/trading_journal.json (真实卖出) + data/kline_data/ (只读本地, 无网络)
口径:
  - 基准 = 该条卖出记录的实际成交价 price
  - d0 = 卖出日收盘 vs 卖价; d1/d3/d5 = 之后第 N 个交易日收盘 vs 卖价
  - max_after = 卖出后 5 个交易日内最高价 vs 卖价 (卖飞空间, 不含卖出当日)
  - 标记: 卖飞(d5>=+5%) / 卖后曾涨停(max_after>=9.8%) / 卖对(d5<=-3%)
局限: K线含前复权增量(除权期价格失真); 右侧截断(近期卖出无完整d5, 统计按可用样本)
"""
import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

JOURNAL = os.path.join(BASE, 'logs', 'trading_journal.json')
OUT = os.path.join(BASE, 'logs', 'sell_review.json')

FLY_D5 = 5.0        # 卖飞: 卖出后5日收盘 >= +5%
RIGHT_D5 = -3.0     # 卖对: 卖出后5日收盘 <= -3%
LU_AFTER = 9.8      # 卖后曾涨停: 5日内最高涨幅 >= 9.8%


def load_sells():
    with open(JOURNAL, 'r', encoding='utf-8') as f:
        rows = json.load(f)
    out = []
    for r in rows:
        a = str(r.get('action', ''))
        if (a == 'SELL' or a.startswith('卖出')) and r.get('code') and r.get('price'):
            out.append(r)
    return out


def review_one(rec, cache):
    from break_layer import load_klines
    code = str(rec['code']).zfill(6)
    if code not in cache:
        cache[code] = load_klines(str(rec.get('name', '')), code)
    kl = cache[code]
    if not kl:
        return {'status': 'no_kline', 'code': code, 'date': str(rec['date'])[:10]}
    d0 = str(rec['date'])[:10]
    idx = next((i for i, b in enumerate(kl) if b.get('date') == d0), None)
    if idx is None:
        return {'status': 'no_match', 'code': code, 'date': d0}
    price = float(rec['price'])
    if price <= 0:
        return {'status': 'bad_price', 'code': code, 'date': d0}
    row = {
        'status': 'ok', 'code': code, 'name': rec.get('name', ''),
        'date': d0, 'price': price,
        'pnl_pct': rec.get('pnl_pct'), 'hold_days': rec.get('hold_days'),
        'note': str(rec.get('note') or ''),
        'd0': round((kl[idx]['close'] - price) / price * 100, 2),
    }
    for n in (1, 3, 5):
        j = idx + n
        row[f'd{n}'] = round((kl[j]['close'] - price) / price * 100, 2) if j < len(kl) else None
    win = [b for b in kl[idx + 1:idx + 6] if b.get('high')]
    row['max_after'] = (round((max(b['high'] for b in win) - price) / price * 100, 2)
                        if win else None)
    row['fly'] = (row['d5'] is not None and row['d5'] >= FLY_D5)
    row['right'] = (row['d5'] is not None and row['d5'] <= RIGHT_D5)
    row['lu_after'] = (row['max_after'] is not None and row['max_after'] >= LU_AFTER)
    return row


def _stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {'n': len(vals), 'mean': round(statistics.mean(vals), 2),
            'med': round(statistics.median(vals), 2),
            'up_pct': round(sum(1 for v in vals if v > 0) / len(vals) * 100)}


def _fmt(tag, s):
    if not s:
        return f'  {tag:<16} (无样本)'
    return (f'  {tag:<16} n={s["n"]:<3} 均值{s["mean"]:+6.2f}% 中位{s["med"]:+6.2f}% '
            f'上涨占{s["up_pct"]:>3}%')


def benchmark(d_lo, d_hi, per_stock=2, seed=42):
    """同期随机基准: 随机(股票×日期) 的 5日内最高价 / d5 分布, 校准卖出数字用。
    ⚠ K线库本身=涨停池+持仓(活跃票), 基准是"同类活跃票"而非全市场, 只能同空间对比。
    """
    import glob
    import random
    from break_layer import KLINE_DIR
    random.seed(seed)
    base_max, base_d5, lu_after = [], [], 0
    for fp in glob.glob(os.path.join(KLINE_DIR, '*.json')):
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            kl = raw.get('data', raw) if isinstance(raw, dict) else raw
        except Exception:
            continue
        if not isinstance(kl, list) or len(kl) < 20:
            continue
        idxs = [i for i, b in enumerate(kl)
                if d_lo <= (b.get('date') or '') <= d_hi and i + 5 < len(kl)]
        if not idxs:
            continue
        for i in random.sample(idxs, min(per_stock, len(idxs))):
            c = kl[i].get('close')
            win = [b['high'] for b in kl[i + 1:i + 6] if b.get('high')]
            if not c or not win:
                continue
            base_max.append((max(win) - c) / c * 100)
            base_d5.append((kl[i + 5]['close'] - c) / c * 100)
            if (max(win) - c) / c * 100 >= LU_AFTER:
                lu_after += 1
    n = len(base_max)
    if not n:
        return None
    return {'n': n, 'max': _stats(base_max), 'd5': _stats(base_d5),
            'lu_after_pct': round(lu_after / n * 100),
            'fly_pct': round(sum(1 for v in base_d5 if v >= FLY_D5) / n * 100),
            'right_pct': round(sum(1 for v in base_d5 if v <= RIGHT_D5) / n * 100)}


def main():
    cache = {}
    rows = [review_one(r, cache) for r in load_sells()]
    ok = [r for r in rows if r['status'] == 'ok']
    skip = [r for r in rows if r['status'] != 'ok']

    print('=' * 66)
    print('  📤 卖出质量跟踪 — 卖出后走势回填')
    print('=' * 66)
    print(f'  卖出记录 {len(rows)} 条 | 可回填 {len(ok)} | 跳过 {len(skip)}'
          + (f' ({" ".join(sorted(set(s["status"] for s in skip)))})' if skip else ''))

    if not ok:
        print('  (无可回填样本)')
        return

    print(f'\n  ── 全样本: 卖出后相对卖价 ──')
    for tag in ('d0', 'd1', 'd3', 'd5'):
        print(_fmt(f'卖出后{tag[1]}日', _stats([r[tag] for r in ok])))
    print(_fmt('5日内最高价', _stats([r['max_after'] for r in ok])))
    print(f'  卖后曾涨停(最高>=+9.8%): {sum(1 for r in ok if r["lu_after"])} 条 / {len(ok)}')

    have5 = [r for r in ok if r['d5'] is not None]
    if have5:
        fly = sum(1 for r in have5 if r['fly'])
        right = sum(1 for r in have5 if r['right'])
        print(f'\n  ── 卖出质量 (有完整d5的 n={len(have5)}) ──')
        print(f'  卖飞(d5>=+5%): {fly} 条 ({fly / len(have5) * 100:.0f}%) | '
              f'卖对(d5<=-3%): {right} 条 ({right / len(have5) * 100:.0f}%) | '
              f'中性: {len(have5) - fly - right} 条')

    # 分档: 卖出时盈亏 / 模型 vs 其他
    groups = [
        ('亏损卖出(pnl<0)', lambda r: isinstance(r.get('pnl_pct'), (int, float)) and r['pnl_pct'] < 0),
        ('盈利卖出(pnl>=0)', lambda r: isinstance(r.get('pnl_pct'), (int, float)) and r['pnl_pct'] >= 0),
        ('模型建议', lambda r: '模型' in r.get('note', '')),
        ('非模型(主观)', lambda r: '模型' not in r.get('note', '')),
    ]
    print(f'\n  ── 分组: 卖出后5日收益 ──')
    for tag, cond in groups:
        sub = [r for r in ok if cond(r)]
        s5 = _stats([r['d5'] for r in sub])
        s_max = _stats([r['max_after'] for r in sub])
        if sub:
            print(f'  {tag} (n={len(sub)}):', end='')
            print(f' d5中位{s5["med"]:+.2f}%' if s5 else ' d5样本不足', end='')
            print(f' | 最高价中位{s_max["med"]:+.2f}%' if s_max else '')
            n_lu = sum(1 for r in sub if r['lu_after'])
            print(f'      卖后曾涨停 {n_lu} 条')

    # 卖飞 TOP
    top = sorted([r for r in ok if r['max_after'] is not None],
                 key=lambda r: r['max_after'], reverse=True)[:5]
    if top:
        print(f'\n  ── 卖飞 TOP5 (按5日内最高涨幅) ──')
        for r in top:
            d5s = f'{r["d5"]:+.1f}%' if r['d5'] is not None else '  -'
            print(f'  {r["date"]} {r["name"]}({r["code"]}) 卖价{r["price"]:.2f} '
                  f'→ 最高{r["max_after"]:+.1f}% d5{d5s} | pnl_at_sell '
                  f'{r["pnl_pct"] if r["pnl_pct"] is not None else "-"}')

    # 同期随机基准对照 (--benchmark, 计算稍慢)
    bench = None
    if '--benchmark' in sys.argv:
        print(f'\n  ── 同期随机基准对照 (K线库随机股票×日期, 校准用, 稍慢) ──')
        dates = sorted(r['date'] for r in ok)
        bench = benchmark(dates[0], dates[-1])
        if bench:
            s5 = _stats([r['d5'] for r in ok])
            print(f"  基准 n={bench['n']}: 5日内最高价中位{bench['max']['med']:+.2f}% "
                  f"| d5中位{bench['d5']['med']:+.2f}% (上涨{bench['d5']['up_pct']}%) "
                  f"| 5日内曾涨停{bench['lu_after_pct']}%")
            print(f"  基准中 d5>=+5% 占{bench['fly_pct']}% | d5<=-3% 占{bench['right_pct']}%"
                  + (f"  → 对比本样本 d5中位{s5['med']:+.2f}%" if s5 else ''))
            print(f"  ⚠ 基准空间=K线库(涨停池+持仓, 活跃票), 非全市场; 仅作同空间对比")
        else:
            print('  (基准样本为空)')

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'total': len(rows), 'reviewed': len(ok),
                   'skipped': [{'status': s['status'], 'code': s['code'], 'date': s['date']}
                               for s in skip],
                   'benchmark': bench, 'rows': ok}, f, ensure_ascii=False, indent=1)
    print(f'\n  结果已存: {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
