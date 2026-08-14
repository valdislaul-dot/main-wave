"""
对子顶统计 (2026-08-14)
对子顶定义: 最高价或收盘价出现对子形态
  - <10元: 豹子 (8.88 / 9.99 / 6.66)
  - >=10元: 双对(33.88) 或 镜像(31.31)
统计: 对子顶出现后次日涨停概率 vs 全样本基线
数据: data/kline_data/ 全库(剔除300/301/688/北交所)
"""
import json, os, glob, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import get_lp


def is_duizi(p):
    """对子形态判定"""
    if not p or p <= 0:
        return False
    if p < 10:
        s = f'{round(p * 100):03d}'
        return s[0] == s[1] == s[2]
    s = f'{round(p * 100):04d}'
    if len(s) > 4:
        s = s[-4:]
    return (s[0] == s[1] and s[2] == s[3]) or (s[0:2] == s[2:4])


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    files = [f for f in glob.glob(os.path.join(KLINE_DIR, '*.json'))
             if not os.path.basename(f).startswith('._')]
    total_days = 0          # 全部有效次日天数
    total_zt = 0            # 全部次日涨停数
    dz_days = 0             # 对子顶天数
    dz_zt = 0               # 对子顶次日涨停数
    dz_high_only = [0, 0]   # [对子顶数, 次日涨停数] 仅最高价对子
    dz_close_only = [0, 0]  # 仅收盘价对子
    dz_both = [0, 0]        # 最高+收盘都对子
    dz_on_zt_day = [0, 0]   # 对子顶当日自身涨停
    dz_on_break_day = [0, 0]  # 对子顶当日未涨停

    for fp in files:
        code = os.path.basename(fp).split('_')[-1].replace('.json', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        try:
            with open(fp, encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            continue
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
        if not isinstance(rows, list) or len(rows) < 2:
            continue
        lpct = get_lp(code)
        for i in range(len(rows) - 1):
            k, n = rows[i], rows[i + 1]
            try:
                h, c = float(k.get('high', 0) or 0), float(k.get('close', 0) or 0)
                prev_c = float(k.get('open', 0) or 0)  # 占位, 下面用前一日close
                prev_close = float(rows[i - 1].get('close', 0) or 0) if i > 0 else 0
                n_close, n_prev = float(n.get('close', 0) or 0), float(k.get('close', 0) or 0)
            except Exception:
                continue
            if h <= 0 or c <= 0 or n_close <= 0 or n_prev <= 0:
                continue
            total_days += 1
            is_zt = (n_close - n_prev) / n_prev >= lpct - 0.002
            if is_zt:
                total_zt += 1
            dh, dc = is_duizi(h), is_duizi(c)
            if dh or dc:
                dz_days += 1
                if is_zt:
                    dz_zt += 1
                if dh and dc:
                    dz_both[0] += 1
                    dz_both[1] += int(is_zt)
                elif dh:
                    dz_high_only[0] += 1
                    dz_high_only[1] += int(is_zt)
                else:
                    dz_close_only[0] += 1
                    dz_close_only[1] += int(is_zt)
                if prev_close > 0:
                    day_zt = (c - prev_close) / prev_close >= lpct - 0.002
                    if day_zt:
                        dz_on_zt_day[0] += 1
                        dz_on_zt_day[1] += int(is_zt)
                    else:
                        dz_on_break_day[0] += 1
                        dz_on_break_day[1] += int(is_zt)

    def rate(a):
        return f'{a[1]}/{a[0]} = {a[1] / a[0] * 100:.2f}%' if a[0] else '无样本'

    print(f'{"=" * 60}')
    print(f'  对子顶统计 | 样本: {len(files)}只股票, {total_days:,}个交易日')
    print(f'{"=" * 60}')
    print(f'  基线(全部次日): {rate([total_days, total_zt])}')
    print(f'  对子顶(高或收): {rate([dz_days, dz_zt])}')
    print(f'    仅最高价对子: {rate(dz_high_only)}')
    print(f'    仅收盘价对子: {rate(dz_close_only)}')
    print(f'    最高+收盘都对: {rate(dz_both)}')
    print(f'    对子顶当日涨停: {rate(dz_on_zt_day)}')
    print(f'    对子顶当日未涨停: {rate(dz_on_break_day)}')


if __name__ == '__main__':
    main()
