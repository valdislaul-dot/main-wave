"""
因子权重验证 — 6年全市场数据
对比实际连板率 vs 当前评分配置
"""
import json, os, glob, sys
from collections import defaultdict
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')

sys.path.insert(0, os.path.join(BASE, 'scripts', 'daily'))
from scoring import load_config, is_limit_up, get_lp, step_score_asc, step_score_desc

CUTOFF = '2020-01-01'  # 6年


def is_one_line(k):
    if k['high'] <= 0 or k['low'] <= 0:
        return False, False
    if abs(k['high'] - k['low']) < 0.01:
        return True, True  # 真一字
    if k['high'] > k['low']:
        us = (k['high'] - max(k['open'], k['close'])) / (k['high'] - k['low'])
        body = abs(k['close'] - k['open']) / (k['high'] - k['low'])
        if us < 0.1 and body < 0.1:
            return True, False  # T字
    return False, False


def run():
    config = load_config()
    v3 = config['tables']['v3']

    # 累积器: factor_name -> tier -> [total, next_lu]
    vr_data = defaultdict(lambda: [0, 0])
    gap_data = defaultdict(lambda: [0, 0])
    ol_data = {'真一字': [0, 0], 'T字': [0, 0], '非一字': [0, 0]}
    cons_data = defaultdict(lambda: [0, 0])
    dow_data = defaultdict(lambda: [0, 0])
    seal_data = defaultdict(lambda: [0, 0])  # 需要封板时间, K线没有, 跳过

    code_files = {}
    for fp in glob.glob(os.path.join(KLINE_DIR, '*.json')):
        fn = os.path.basename(fp).replace('.json', '')
        parts = fn.rsplit('_', 1)
        if len(parts) == 2 and parts[0] and parts[0] != parts[1]:
            name, code = parts[0], parts[1]
        else:
            code = fn.lstrip('_')
        if code not in code_files or (parts[0] and len(parts) > 1):
            code_files[code] = (parts[0] if len(parts) > 1 and parts[0] else '', fp)

    code_files = {c: v for c, v in code_files.items()
                  if not c.startswith(('300', '301', '688'))}

    total_lu_days = 0

    for code, (name, fp) in code_files.items():
        try:
            with open(fp, encoding='utf-8') as f:
                klines = json.load(f)
        except:
            continue
        if len(klines) < 30:
            continue

        lp = get_lp(code)

        # 预计算
        is_lu_arr = [False] * len(klines)
        for i in range(1, len(klines)):
            is_lu_arr[i] = is_limit_up(klines[i]['close'], klines[i-1]['close'], lp)

        for i in range(30, len(klines) - 1):
            if klines[i]['date'] < CUTOFF:
                continue
            if not is_lu_arr[i]:
                continue

            total_lu_days += 1
            curr = klines[i]
            prev = klines[i-1]
            next_k = klines[i+1]
            next_lu = is_lu_arr[i+1]

            # 量比
            if i >= 20:
                ma20 = sum(klines[j]['volume'] for j in range(i-19, i+1)) / 20
                vr20 = curr['volume'] / ma20 if ma20 > 0 else 1
            else:
                vr20 = 1
            vr_bin = f'{vr20:.1f}x'
            vr_data[vr_bin][0] += 1
            vr_data[vr_bin][1] += 1 if next_lu else 0

            # gap
            gap = round((curr['open'] - prev['close']) / prev['close'] * 100, 2)
            if gap >= 10:
                gap_bin = '10%+'
            elif gap >= 7:
                gap_bin = '7-10%'
            elif gap >= 3:
                gap_bin = '3-7%'
            elif gap >= 0:
                gap_bin = '0-3%'
            elif gap >= -3:
                gap_bin = '-3~0%'
            else:
                gap_bin = '<-3%'
            gap_data[gap_bin][0] += 1
            gap_data[gap_bin][1] += 1 if next_lu else 0

            # 一字板
            is_ol, is_true = is_one_line(curr)
            if is_true:
                ol_data['真一字'][0] += 1
                ol_data['真一字'][1] += 1 if next_lu else 0
            elif is_ol:
                ol_data['T字'][0] += 1
                ol_data['T字'][1] += 1 if next_lu else 0
            else:
                ol_data['非一字'][0] += 1
                ol_data['非一字'][1] += 1 if next_lu else 0

            # 连板数
            cons = 0
            for j in range(i-1, max(i-15, -1), -1):
                if j > 0 and is_lu_arr[j]:
                    cons += 1
                else:
                    break
            if cons == 0:
                cons_bin = '首板'
            elif cons <= 2:
                cons_bin = '2-3板'
            else:
                cons_bin = '4板+'
            cons_data[cons_bin][0] += 1
            cons_data[cons_bin][1] += 1 if next_lu else 0

            # 周几
            dt = datetime.strptime(curr['date'], '%Y-%m-%d')
            dow = (dt + timedelta(days=1)).weekday()
            while dow >= 5:
                dt = dt + timedelta(days=1)
                dow = dt.weekday()
            dow_data[dow][0] += 1
            dow_data[dow][1] += 1 if next_lu else 0

    base_rate = sum(v[1] for v in vr_data.values()) / sum(v[0] for v in vr_data.values()) * 100
    print(f"样本: {total_lu_days}个涨停日 | 基准连板率: {base_rate:.1f}%")
    print()

    # ==== 量比 ====
    print(f"{'='*55}")
    print(f" 量比因子")
    print(f"{'档位':<12} {'样本':>8} {'连板率':>8} {'vs基准':>8} {'当前权重':>8}")
    print(f"{'-'*55}")
    vr_sorted = sorted(vr_data.items(), key=lambda x: float(x[0].replace('x', '')))
    for bin_name, (s, n) in vr_sorted[:12]:
        rate = n / s * 100 if s > 0 else 0
        diff = rate - base_rate
        # 当前权重
        try:
            x = float(bin_name.replace('x', ''))
            wt = step_score_asc(x, v3['vr_tiers'])
        except:
            wt = '?'
        print(f"{bin_name:<12} {s:>8} {rate:>7.1f}% {diff:>+7.1f}% {wt:>8}")

    # ==== gap ====
    print(f"\n{'='*55}")
    print(f" gap因子")
    print(f"{'档位':<12} {'样本':>8} {'连板率':>8} {'vs基准':>8} {'当前权重':>8}")
    print(f"{'-'*55}")
    gap_order = ['10%+', '7-10%', '3-7%', '0-3%', '-3~0%', '<-3%']
    for bin_name in gap_order:
        s, n = gap_data[bin_name]
        rate = n / s * 100 if s > 0 else 0
        diff = rate - base_rate
        mid = {'10%+': 10, '7-10%': 8.5, '3-7%': 5, '0-3%': 1.5, '-3~0%': -1.5, '<-3%': -5}
        wt = step_score_desc(mid.get(bin_name, 0), v3['gap_tiers'])
        print(f"{bin_name:<12} {s:>8} {rate:>7.1f}% {diff:>+7.1f}% {wt:>8}")

    # ==== 一字板 ====
    print(f"\n{'='*55}")
    print(f" 一字板因子")
    print(f"{'类型':<12} {'样本':>8} {'连板率':>8} {'vs基准':>8} {'当前权重':>8}")
    print(f"{'-'*55}")
    for typ in ['真一字', 'T字', '非一字']:
        s, n = ol_data[typ]
        rate = n / s * 100 if s > 0 else 0
        diff = rate - base_rate
        wt = config['one_line_score'].get('true_one' if typ == '真一字' else 't_board', 0)
        print(f"{typ:<12} {s:>8} {rate:>7.1f}% {diff:>+7.1f}% {wt:>8}")

    # ==== 连板 ====
    print(f"\n{'='*55}")
    print(f" 连板因子")
    print(f"{'档位':<12} {'样本':>8} {'连板率':>8} {'vs基准':>8} {'当前权重':>8}")
    print(f"{'-'*55}")
    for bin_name in ['首板', '2-3板', '4板+']:
        s, n = cons_data[bin_name]
        rate = n / s * 100 if s > 0 else 0
        diff = rate - base_rate
        wt = config['cons_score'].get(
            'first' if bin_name == '首板' else ('sweet_2_3' if bin_name == '2-3板' else 'high_4plus'), 0)
        print(f"{bin_name:<12} {s:>8} {rate:>7.1f}% {diff:>+7.1f}% {wt:>8}")

    # ==== 周几 ====
    print(f"\n{'='*55}")
    print(f" 周几因子(次日)")
    print(f"{'星期':<12} {'样本':>8} {'连板率':>8} {'vs基准':>8} {'当前权重':>8}")
    print(f"{'-'*55}")
    dow_names = {0: '周一', 1: '周二', 2: '周三', 3: '周四', 4: '周五'}
    for dow in range(5):
        s, n = dow_data[dow]
        rate = n / s * 100 if s > 0 else 0
        diff = rate - base_rate
        wt = config['dow_score'].get('monday' if dow == 0 else ('friday' if dow == 4 else None), 0)
        print(f"{dow_names[dow]:<12} {s:>8} {rate:>7.1f}% {diff:>+7.1f}% {wt:>8}")


if __name__ == '__main__':
    run()
