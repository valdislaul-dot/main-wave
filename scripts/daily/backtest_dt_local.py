"""
龙虎榜+大宗因子 本地回测 v3 — 高效版 (K线预缓存 + 进度刷新)
"""
import json, os, sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DT_DIR = os.path.join(BASE, 'data', 'dt_block')
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')

def main():
    files = sorted([f for f in os.listdir(DT_DIR)
                    if f.endswith('.json') and f != '_summary.json'])
    print(f"加载 {len(files)} 天 dt_block 数据...", flush=True)

    # Phase 1: Collect all unique codes and their DT/block data
    code_records = defaultdict(list)  # code -> [(date, dt_score, block_score, ...)]

    for i, fname in enumerate(files):
        date = fname.replace('.json', '')
        with open(os.path.join(DT_DIR, fname), encoding='utf-8') as f:
            day = json.load(f)
        dt_list = day.get('dragon_tiger', [])
        block_list = day.get('block_trades', [])

        # Index block trades by code
        block_by_code = defaultdict(list)
        for b in block_list:
            block_by_code[b['code']].append(b)

        for r in dt_list:
            code = r['code']
            if code.startswith(('300', '301', '688')):
                continue

            # Calc DT factor
            dt_score = 0
            net_buy = r.get('net_buy_wan', 0)
            if net_buy > 10000: dt_score += 3
            elif net_buy < -5000: dt_score -= 4

            turnover = r.get('turnover', 0)
            if turnover > 30: dt_score -= 2
            elif turnover < 1: dt_score += 2

            # Calc block factor
            blocks = block_by_code.get(code, [])
            blk_score = 0
            if blocks:
                disc = sum(b['amount_wan'] for b in blocks if b.get('premium_pct', 0) < -5)
                prem = sum(b['amount_wan'] for b in blocks if b.get('premium_pct', 0) > 2)
                if disc > 1000: blk_score -= 5
                elif disc > 500: blk_score -= 3
                elif disc > 100: blk_score -= 1
                if prem > 500: blk_score += 4
                elif prem > 100: blk_score += 2

            code_records[code].append((date, dt_score + blk_score, net_buy, turnover, len(blocks) > 0))

        if (i + 1) % 100 == 0:
            print(f"  收集进度: {i+1}/{len(files)}  唯一标的: {len(code_records)}", flush=True)

    print(f"\n唯一标的: {len(code_records)} 只", flush=True)
    total_records = sum(len(v) for v in code_records.values())
    print(f"总记录: {total_records} 条", flush=True)

    # Phase 2: Pre-cache K-lines
    print(f"\n预加载K线...", flush=True)
    kline_cache = {}
    codes_to_load = list(code_records.keys())
    loaded = 0
    for code in codes_to_load:
        fp = os.path.join(KLINE_DIR, f'{code}.json')
        if os.path.exists(fp):
            with open(fp, encoding='utf-8') as f:
                raw = json.load(f)
                kline_cache[code] = raw.get('data', raw) if isinstance(raw, dict) else raw
                loaded += 1
    print(f"K线加载: {loaded}/{len(codes_to_load)} 只", flush=True)

    # Phase 3: Compute next-day returns
    print(f"\n计算次日收益...", flush=True)
    all_results = []
    no_kline = 0
    no_next = 0

    for idx, (code, records) in enumerate(code_records.items()):
        kls = kline_cache.get(code)
        if not kls:
            no_kline += len(records)
            continue

        # Build date index for fast lookup
        date_idx = {k['date']: i for i, k in enumerate(kls)}

        for date, factor, net_buy, turnover, has_block in records:
            t_idx = date_idx.get(date)
            if t_idx is None or t_idx + 1 >= len(kls):
                no_next += 1
                continue

            t0 = kls[t_idx]
            t1 = kls[t_idx + 1]
            t_open = t1.get('open', 0)
            t_close = t1.get('close', 0)
            if t_open <= 0:
                no_next += 1
                continue

            gap = round((t_open - t0['close']) / t0['close'] * 100, 2)
            iret = round((t_close - t_open) / t_open * 100, 2)
            is_lu = iret > 9

            all_results.append({
                'code': code, 'date': date, 'factor': factor,
                'net_buy': net_buy, 'has_block': has_block,
                'gap_pct': gap, 'intraday_ret': iret, 'is_limit_up': is_lu,
            })

        if (idx + 1) % 1000 == 0:
            print(f"  处理: {idx+1}/{len(code_records)}  有效样本: {len(all_results)}", flush=True)

    print(f"\n有效样本: {len(all_results)} (无K线:{no_kline} 无次日:{no_next})", flush=True)

    # Phase 4: Analysis
    def show(group, label):
        n = len(group)
        if n == 0:
            print(f"\n{label}: 无样本")
            return
        avg_gap = sum(s['gap_pct'] for s in group) / n
        avg_ret = sum(s['intraday_ret'] for s in group) / n
        lu = sum(1 for s in group if s['is_limit_up']) / n * 100
        print(f"\n{label} ({n}只):  gap{avg_gap:+.2f}%  日内{avg_ret:+.2f}%  连板率{lu:.1f}%")
        return n, avg_gap, avg_ret, lu

    print(f"\n{'='*60}")
    print(f"  回测结果")
    print(f"{'='*60}")

    pos = [s for s in all_results if s['factor'] > 0]
    zero = [s for s in all_results if s['factor'] == 0]
    neg = [s for s in all_results if s['factor'] < 0]
    show(pos, "正面信号 (>0)")
    show(zero, "中性 (=0)")
    show(neg, "负面信号 (<0)")

    show([s for s in all_results if s['factor'] >= 3], "强正面 (>=+3)")
    show([s for s in all_results if s['factor'] <= -3], "强负面 (<=-3)")

    # By net buy amount
    print(f"\n{'='*60}")
    print("  龙虎榜净买额分组")
    print(f"{'='*60}")
    for lo, hi, label in [(5000, 999999, '净买>5000万'), (0, 5000, '净买0-5000万'),
                           (-5000, 0, '净卖0-5000万'), (-999999, -5000, '净卖>5000万')]:
        g = [s for s in all_results if lo <= s['net_buy'] < hi]
        if g:
            n = len(g)
            lu = sum(1 for s in g if s['is_limit_up']) / n * 100
            avg_ret = sum(s['intraday_ret'] for s in g) / n
            print(f"  {label}: {n}只 均收益{avg_ret:+.2f}% 连板率{lu:.1f}%")

    # Factor distribution
    factor_dist = defaultdict(list)
    for s in all_results:
        factor_dist[s['factor']].append(s)

    print(f"\n{'='*60}")
    print("  因子得分分布 (Top 15)")
    print(f"{'='*60}")
    top_scores = sorted(factor_dist.items(), key=lambda x: -len(x[1]))[:15]
    for score, group in sorted(top_scores, key=lambda x: x[0]):
        n = len(group)
        lu = sum(1 for s in group if s['is_limit_up']) / n * 100
        bar = '#' * min(n // 20, 40)
        print(f"  {score:+3d}: {n:5d} {bar} 连板率{lu:.0f}%")

    print()
    return all_results

if __name__ == '__main__':
    main()
