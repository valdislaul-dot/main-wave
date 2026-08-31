"""
周五买入效应分析 (2026-08-31, 用户问题驱动)
问题: 周五买入涨停股, 周末消息冲击是否让周一承受更大压力?
口径: T-1涨停股, T日开盘买入(竞价), 对比 周五买入 vs 周一~周四买入
指标: T+1开盘gap(隔夜冲击, 周五→周一=跨周末) / T+1收盘收益 / T+1最高点(最佳出场) / 胜率
数据: data/kline_data/ 全库K线(搜狐不复权主库), 3年窗口 2023-08-31 ~ 今
涨停判定: pct_change∈[9.5,31] 且 close==high (封板)
"""
import json, os, sys
from datetime import datetime, timedelta
from statistics import mean, median

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KL_DIR = os.path.join(BASE, 'data', 'kline_data')

START = '2023-08-31'
END = '2026-08-31'
BUY_WIN = (4.0, 8.0)  # 策略口径: 竞价4-8%买入窗 (--full 时改为全部可买 0~9.5)

def load_klines(code):
    fp = os.path.join(KL_DIR, f'{code}.json')
    try:
        with open(fp, encoding='utf-8') as f:
            raw = json.load(f)
        kl = raw.get('data', raw) if isinstance(raw, dict) else raw
        return kl if isinstance(kl, list) else []
    except Exception:
        return []

def weekday_of(date_s):
    return datetime.strptime(date_s, '%Y-%m-%d').weekday()  # 0=周一 ... 4=周五

def main():
    global BUY_WIN
    if '--full' in sys.argv:
        BUY_WIN = (0.0, 9.5)
    rows = []  # {buy_wd, gap_open, ret_close, ret_high}
    files = [f for f in os.listdir(KL_DIR) if f.endswith('.json')]
    scanned = 0
    for fn in files:
        code = fn[:-5]
        kl = load_klines(code)
        if len(kl) < 30:
            continue
        scanned += 1
        for i in range(1, len(kl) - 1):
            prev = kl[i - 1]
            cur = kl[i]
            nxt = kl[i + 1]
            d = cur.get('date', '')
            if not (START <= d <= END):
                continue
            # T-1 涨停判定
            pc = prev.get('pct_change')
            if pc is None and cur.get('close') and prev.get('close') and prev['close'] > 0:
                pc = (cur['close'] - prev['close']) / prev['close'] * 100
            if pc is None or not (9.5 <= pc <= 31):
                continue
            if prev.get('high') and prev.get('close') and prev['close'] < prev['high'] * 0.999:
                continue  # 未封板(收盘≠最高)
            # T日开盘买入
            pc_prev = prev.get('close', 0)
            if pc_prev <= 0 or not cur.get('open') or not nxt.get('open'):
                continue
            gap_open = (cur['open'] - pc_prev) / pc_prev * 100  # 竞价高开幅度
            if not (BUY_WIN[0] <= gap_open <= BUY_WIN[1]):
                continue  # 策略口径: 仅4-8%窗
            nxt_open_gap = (nxt['open'] - cur['open']) / cur['open'] * 100
            ret_close = (nxt['close'] - cur['open']) / cur['open'] * 100
            ret_high = (nxt['high'] - cur['open']) / cur['open'] * 100 if nxt.get('high') else ret_close
            rows.append({'buy_wd': weekday_of(d), 'date': d,
                         'nxt_open_gap': nxt_open_gap, 'ret_close': ret_close, 'ret_high': ret_high})

    print(f'K线文件扫描: {scanned}/{len(files)} | 样本(4-8%窗): {len(rows)} 笔')
    print()
    wd_names = ['周一', '周二', '周三', '周四', '周五']
    print(f'{"买入日":<6}{"笔数":>6}{"T+1开盘gap均值":>14}{"T+1收盘收益":>12}{"胜率":>8}{"T+1最高点":>12}')
    print('-' * 58)
    agg = {}
    for wd in range(5):
        r = [x for x in rows if x['buy_wd'] == wd]
        if not r:
            continue
        agg[wd] = r
        wr = sum(1 for x in r if x['ret_close'] > 0) / len(r) * 100
        print(f'{wd_names[wd]:<7}{len(r):>5}{mean(x["nxt_open_gap"] for x in r):>13.2f}%'
              f'{mean(x["ret_close"] for x in r):>11.2f}%{wr:>7.1f}%'
              f'{mean(x["ret_high"] for x in r):>11.2f}%')
    print('-' * 58)
    fri = agg.get(4, [])
    oth = [x for x in rows if x['buy_wd'] != 4]
    if fri and oth:
        print()
        print('周五 vs 周一~周四 对比:')
        for label, a, b in [
            ('T+1开盘gap(隔夜冲击)', 'nxt_open_gap', 'nxt_open_gap'),
            ('T+1收盘收益', 'ret_close', 'ret_close'),
            ('T+1最高点(最佳出场)', 'ret_high', 'ret_high'),
        ]:
            ma, mb = mean(x[a] for x in fri), mean(x[b] for x in oth)
            print(f'  {label}: 周五 {ma:+.2f}% vs 其他 {mb:+.2f}%  差 {ma - mb:+.2f}pp')
        wf = sum(1 for x in fri if x['ret_close'] > 0) / len(fri) * 100
        wo = sum(1 for x in oth if x['ret_close'] > 0) / len(oth) * 100
        print(f'  胜率: 周五 {wf:.1f}% vs 其他 {wo:.1f}%')
        print(f'  中位数收益: 周五 {median(x["ret_close"] for x in fri):+.2f}% vs 其他 {median(x["ret_close"] for x in oth):+.2f}%')
    print()
    print('周五按年份:')
    for year in ['2023', '2024', '2025', '2026']:
        r = [x for x in fri if x['date'].startswith(year)]
        if not r:
            continue
        wr = sum(1 for x in r if x['ret_close'] > 0) / len(r) * 100
        print(f'  {year}: {len(r)}笔  开盘gap {mean(x["nxt_open_gap"] for x in r):+.2f}%  '
              f'收盘 {mean(x["ret_close"] for x in r):+.2f}%  胜率 {wr:.1f}%')

if __name__ == '__main__':
    main()
