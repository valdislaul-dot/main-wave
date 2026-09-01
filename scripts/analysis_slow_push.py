"""
慢推型回测 v2 (2026-09-01)
样本: data/minute_kline 824个个股-日(44天), 全部为当日收盘涨停的T字板/池股(收盘=最高=涨停价)。
口径: 昨收=收盘/1.1 反推; 竞价gap分档; 统计封板时刻分布; 量化「10点放弃」错过的收益。
局限: 样本不含未封板股(失败率不可测), 只回答「对最终涨停的股, 早盘放弃会错过多少」。
"""
import sys, os, json
from statistics import mean, median
sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_DIR = os.path.join(BASE, 'data', 'minute_kline')

rows = []
files = [f for f in os.listdir(MIN_DIR) if f.endswith('.json') and not f.startswith('_')]
for fn in files:
    try:
        d = json.load(open(os.path.join(MIN_DIR, fn), encoding='utf-8'))
    except Exception:
        continue
    bars = d.get('min1', [])
    if len(bars) < 239:
        continue
    close_p = float(bars[-1]['c'])
    if close_p <= 0:
        continue
    limit = close_p                      # 收盘涨停 → 收盘价=涨停价
    prev_close = close_p / 1.1
    open_p = float(bars[0]['o'])
    gap = (open_p - prev_close) / prev_close * 100
    # 封板时刻: 第一根 h 触及涨停价
    seal_idx = next((i for i, b in enumerate(bars) if float(b['h']) >= limit * 0.995), None)
    seal_t = bars[seal_idx]['t'][-4:] if seal_idx is not None else '1500'
    # 10:00 状态
    idx10 = next((i for i, b in enumerate(bars) if b['t'].endswith('1000')), 29)
    pre = bars[:idx10 + 1]
    p10 = float(pre[-1]['c'])
    vwap = sum(float(b['c']) * float(b['v']) for b in pre) / sum(float(b['v']) for b in pre) if pre else p10
    sealed10 = p10 >= limit * 0.995
    gap_b = '低开<0%' if gap < 0 else ('平开0-4%' if gap < 4 else ('高开4-8%' if gap < 8 else '大高开≥8%'))
    slow = (not sealed10) and (p10 > open_p) and (p10 > vwap)   # 10点未封+均线上+高于开盘
    rows.append({'gap_b': gap_b, 'gap': gap, 'sealed10': sealed10, 'slow': slow,
                 'seal_t': seal_t, 'p10': p10, 'open': open_p, 'close': close_p,
                 'ret_close': (close_p - open_p) / open_p * 100,
                 'ret_10': (p10 - open_p) / open_p * 100,
                 'ret_after10': (close_p - p10) / p10 * 100})

print(f'样本: {len(rows)} 个股-日 (44天, 全部收盘涨停)')
print()
print('══ 竞价gap vs 封板时刻 ══')
print(f'{"竞价":<12}{"样本":>6}{"≤10:00封板":>11}{"10:00-11:30":>12}{"午后封板":>9}{"10点未封慢推型":>12}')
for g in ('低开<0%', '平开0-4%', '高开4-8%', '大高开≥8%'):
    r = [x for x in rows if x['gap_b'] == g]
    if not r:
        continue
    e = sum(1 for x in r if x['sealed10'])
    mid = sum(1 for x in r if not x['sealed10'] and x['seal_t'] <= '1130')
    pm = sum(1 for x in r if not x['sealed10'] and x['seal_t'] > '1130')
    slow = sum(1 for x in r if x['slow'])
    print(f'{g:<12}{len(r):>6}{e:>9}({e/len(r)*100:>4.0f}%){mid:>9}({mid/len(r)*100:>4.0f}%){pm:>8}({pm/len(r)*100:>4.0f}%){slow:>10}({slow/len(r)*100:>4.0f}%)')
print()
print('══ 10点未封板的股: 慢推型 vs 非慢推 ══')
late = [x for x in rows if not x['sealed10']]
slow_late = [x for x in late if x['slow']]
other_late = [x for x in late if not x['slow']]
print(f'  10点未封共 {len(late)} 只 (占全部 {len(late)/len(rows)*100:.1f}%)')
print(f'    其中慢推型(10点均线上+高于开盘): {len(slow_late)} 只 ({len(slow_late)/len(late)*100:.1f}%)')
if slow_late:
    print(f'      封板时刻分布: 10:00-11:30 {sum(1 for x in slow_late if x["seal_t"] <= "1130")} | 午后 {sum(1 for x in slow_late if x["seal_t"] > "1130")}')
    print(f'      收盘收益均值 {mean(x["ret_close"] for x in slow_late):+.2f}% | 10点时收益均值 {mean(x["ret_10"] for x in slow_late):+.2f}%')
    print(f'      10点后增量均值 {mean(x["ret_after10"] for x in slow_late):+.2f}% | 中位 {median(x["ret_after10"] for x in slow_late):+.2f}%')
if other_late:
    print(f'    非慢推型 {len(other_late)} 只: 收盘收益均值 {mean(x["ret_close"] for x in other_late):+.2f}% | 10点后增量 {mean(x["ret_after10"] for x in other_late):+.2f}%')
print()
print('注: 本样本全是当日最终涨停股(无失败率); 未封板股的亏损风险另需全池分钟数据验证。')
