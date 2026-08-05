"""
历史涨停频次 vs 次日连板率 回测
问题: 三年涨停频次能否预测次日连板概率？
"""
import json, os, glob, sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')


def is_limit_up(close, prev_close, lp):
    return prev_close > 0 and close >= round(prev_close * (1 + lp), 2) - 0.005


def run():
    # 去重
    code_files = {}
    for fp in glob.glob(os.path.join(KLINE_DIR, '*.json')):
        fname = os.path.basename(fp).replace('.json', '')
        parts = fname.rsplit('_', 1)
        if len(parts) == 2 and parts[0] and parts[0] != parts[1]:
            name, code = parts[0], parts[1]
        else:
            code = fname.lstrip('_')
            name = ''
        if code not in code_files or (name and not code_files[code][0]):
            code_files[code] = (name, fp)

    # 排除300/301/688
    code_files = {c: v for c, v in code_files.items()
                  if not c.startswith(('300', '301', '688'))}

    # 统计: freq_bucket -> [total_samples, next_day_lu_count]
    # 分别看不同回看窗口
    for lookback_label, lookback_days in [("全部历史", None), ("近120天", 120), ("近60天", 60)]:
        buckets_6 = defaultdict(lambda: [0, 0])  # 6档
        buckets_fine = defaultdict(lambda: [0, 0])  # 细档

        total_stocks = 0
        for code, (name, fp) in code_files.items():
            try:
                with open(fp, encoding='utf-8') as f:
                    klines = json.load(f)
            except:
                continue
            if len(klines) < 30:
                continue
            total_stocks += 1

            lp = 0.10

            # 预先计算每天是否涨停
            is_lu = [False] * len(klines)
            for i in range(1, len(klines)):
                is_lu[i] = is_limit_up(klines[i]['close'], klines[i-1]['close'], lp)

            # 遍历每天（从第26天开始，保证有足够历史）
            for i in range(26, len(klines) - 1):  # -1 因为需要看次日
                if not is_lu[i]:
                    continue  # 只统计涨停日

                # 统计到 i 这天为止的历史涨停频次
                start = 0 if lookback_days is None else max(0, i - lookback_days)
                freq = sum(1 for j in range(start, i + 1) if is_lu[j])

                # 次日是否连板
                next_lu = is_lu[i + 1]

                # 粗分6档
                if freq <= 2:
                    bucket = "0-2次"
                elif freq <= 5:
                    bucket = "3-5次"
                elif freq <= 10:
                    bucket = "6-10次"
                elif freq <= 20:
                    bucket = "11-20次"
                elif freq <= 30:
                    bucket = "21-30次"
                else:
                    bucket = "30+次"
                buckets_6[bucket][0] += 1
                buckets_6[bucket][1] += 1 if next_lu else 0

                # 细分档
                if freq <= 1:
                    fb = "0-1"
                elif freq <= 3:
                    fb = "2-3"
                elif freq <= 5:
                    fb = "4-5"
                elif freq <= 8:
                    fb = "6-8"
                elif freq <= 12:
                    fb = "9-12"
                elif freq <= 18:
                    fb = "13-18"
                elif freq <= 25:
                    fb = "19-25"
                elif freq <= 35:
                    fb = "26-35"
                else:
                    fb = "36+"
                buckets_fine[fb][0] += 1
                buckets_fine[fb][1] += 1 if next_lu else 0

        # 输出
        total_samples_6 = sum(v[0] for v in buckets_6.values())
        total_next_6 = sum(v[1] for v in buckets_6.values())
        base_rate_6 = total_next_6 / total_samples_6 * 100 if total_samples_6 > 0 else 0

        print(f"\n{'='*65}")
        print(f"  回看窗口: {lookback_label} | {total_stocks}只 | {total_samples_6}个涨停日样本")
        print(f"  整体连板率基准: {base_rate_6:.1f}%")
        print(f"{'='*65}")

        # 6档
        order_6 = ["0-2次", "3-5次", "6-10次", "11-20次", "21-30次", "30+次"]
        print(f"\n{'档位':<10} {'样本':>6} {'连板':>6} {'连板率':>8} {'vs基准':>8}")
        print("-" * 45)
        for b in order_6:
            s, n = buckets_6[b]
            rate = n / s * 100 if s > 0 else 0
            diff = rate - base_rate_6
            bar = "+" if diff > 0 else "-"
            print(f"{b:<10} {s:>6} {n:>6} {rate:>7.1f}% {bar}{abs(diff):.1f}%")

        # 细档
        order_f = ["0-1", "2-3", "4-5", "6-8", "9-12", "13-18", "19-25", "26-35", "36+"]
        print(f"\n{'档位':<10} {'样本':>6} {'连板':>6} {'连板率':>8} {'vs基准':>8}")
        print("-" * 45)
        for b in order_f:
            s, n = buckets_fine[b]
            rate = n / s * 100 if s > 0 else 0
            diff = rate - base_rate_6
            bar = "+" if diff > 0 else "-"
            if s > 0:
                print(f"{b:<10} {s:>6} {n:>6} {rate:>7.1f}% {bar}{abs(diff):.1f}%")


if __name__ == '__main__':
    run()
