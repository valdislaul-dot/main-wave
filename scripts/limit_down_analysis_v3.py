"""跌停分析 v3 — 补齐五大遗漏维度 (2026-08-21)
[1] 连续跌停状态: 首个跌停 vs 连续第2/3+个跌停
[2] 量能: 跌停日量比(vs前5日均量) 分层
[3] 时间结构: 开盘触跌停 vs 盘中触跌停
[4] 市场环境: 当日涨停数(弱<60/正常60-109/强≥110)
[5] 价格区间: <5 / 5-10 / 10-20 / 20-50 / ≥50元
每维度: 开板率 + 地天率 + 次日均收益/上涨率
输出: logs/limit_down_analysis_v3.txt
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


def limit_price(prev_close, is_st, up=True):
    pct = 0.05 if is_st else 0.10
    return round(prev_close * (1 + pct), 2) if up else round(prev_close * (1 - pct), 2)


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
            for r in rows:
                if not isinstance(r, dict):
                    continue
                date = r.get('date', '')
                if not (START <= date <= END):
                    continue
                t[date] = {
                    'open': float(r.get('open', 0) or 0),
                    'high': float(r.get('high', 0) or 0),
                    'low': float(r.get('low', 0) or 0),
                    'close': float(r.get('close', 0) or 0),
                    'pct': r.get('pct_change'),
                    'vol': float(r.get('volume_lots', 0) or 0),
                }
            if t:
                tbl[code] = (name, t)
    return tbl


def main():
    print('加载K线...')
    tbl = load_all()
    print(f'{len(tbl)}只')

    # 每日涨停数(环境)
    pool = defaultdict(set)
    for code, (name, t) in tbl.items():
        for date, r in t.items():
            if is_lu(r['pct'], name):
                pool[date].add(code)
    days_all = sorted(pool.keys())
    zt_by_day = {d: len(pool[d]) for d in days_all}

    rows = []
    for code, (name, t) in tbl.items():
        is_st = 'ST' in name
        dates = sorted(t.keys())
        for i, d in enumerate(dates):
            if i == 0:
                continue
            r = t[d]
            prev = t[dates[i - 1]]
            pc = prev['close']
            if pc <= 0:
                continue
            dt_price = limit_price(pc, is_st, up=False)
            lu_price = limit_price(pc, is_st, up=True)
            if r['low'] > dt_price + 0.005:
                continue
            # 连续跌停数: 前一日是否跌停
            prev_dt = limit_price(t[dates[i-2]]['close'] if i >= 2 else 0, is_st, up=False) if i >= 2 else 0
            dt_streak = 1
            j = i - 1
            while j >= 1:
                pj, pj1 = t[dates[j]], t[dates[j-1]]
                if pj1['close'] > 0 and pj['close'] <= limit_price(pj1['close'], is_st, up=False) + 0.005:
                    dt_streak += 1
                    j -= 1
                else:
                    break
            # 量比: 当日量 / 前5日均量
            vols = [t[dates[k]]['vol'] for k in range(max(0, i-5), i) if t[dates[k]]['vol'] > 0]
            vr5 = r['vol'] / (sum(vols)/len(vols)) if vols and sum(vols) > 0 else 0
            # 环境
            n_zt = zt_by_day.get(d, 0)
            env = '弱市' if n_zt < 60 else ('强势' if n_zt >= 110 else '正常')
            rows.append({
                'code': code, 'date': d,
                'dt_open': r['open'] <= dt_price + 0.005,   # 开盘即触
                'opened': r['close'] > dt_price + 0.005,
                'dt2lu': r['close'] >= lu_price - 0.005,
                'dt_streak': dt_streak,
                'vr5': vr5,
                'env': env,
                'price': r['close'],
                'close': r['close'],
            })

    # 次日
    nxt = {}
    for code, (name, t) in tbl.items():
        dates = sorted(t.keys())
        for i, d in enumerate(dates):
            if i + 1 < len(dates):
                nxt[(code, d)] = t[dates[i + 1]]

    def nxt_ret(x):
        r1 = nxt.get((x['code'], x['date']))
        if r1 and x['close'] > 0 and r1['open'] > 0 and r1['close'] > 0:
            return (r1['close'] - x['close']) / x['close'] * 100
        return None

    out = []
    out.append('=' * 84)
    out.append('跌停分析 v3 — 五大遗漏维度补齐 (3年, 剔除300/301/688/8/9)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 触跌停样本: {len(rows)}')
    out.append('=' * 84)

    def pct(v):
        return f'{v*100:.1f}%'

    def emit_layer(title, items):
        if len(items) < 50:
            return
        op_n = sum(1 for x in items if x['opened'])
        dt2 = sum(1 for x in items if x['dt2lu'])
        rets = [r for r in (nxt_ret(x) for x in items) if r is not None]
        line = f'  {title:<28} {len(items):>6}次 | 开板率 {pct(op_n/len(items)):<6} | 地天率 {pct(dt2/len(items)):<6}'
        if len(rets) >= 30:
            up = sum(1 for r in rets if r > 0) / len(rets) * 100
            line += f' | 次日均{sum(rets)/len(rets):+.2f}% 上涨率{up:.0f}%'
        out.append(line)

    # [1] 连续跌停状态
    out.append('\n[1] 连续跌停状态')
    for streak, label in ((1, '首个跌停'), (2, '连续第2个跌停'), (3, '连续第3个跌停'), (4, '连续第4+个跌停')):
        emit_layer(label, [x for x in rows if (x['dt_streak'] >= 4 if streak == 4 else x['dt_streak'] == streak)])

    # [2] 量能
    out.append('\n[2] 跌停日量比(vs前5日均量)')
    for lo, hi, label in ((0, 0.5, '缩量<0.5x'), (0.5, 1.0, '缩量0.5-1x'), (1.0, 2.0, '平量1-2x'),
                          (2.0, 4.0, '放量2-4x'), (4.0, 99, '巨量≥4x')):
        emit_layer(label, [x for x in rows if lo <= x['vr5'] < hi])

    # [3] 时间结构
    out.append('\n[3] 触跌停时间结构')
    emit_layer('开盘即触跌停(open≈跌停价)', [x for x in rows if x['dt_open']])
    emit_layer('盘中才触跌停(open>跌停价)', [x for x in rows if not x['dt_open']])

    # [4] 市场环境
    out.append('\n[4] 市场环境(当日涨停数)')
    for env in ('弱市', '正常', '强势'):
        emit_layer(f'{env}(<60/60-109/≥110只)', [x for x in rows if x['env'] == env])

    # [5] 价格区间
    out.append('\n[5] 价格区间(收盘价)')
    for lo, hi, label in ((0, 5, '<5元'), (5, 10, '5-10元'), (10, 20, '10-20元'),
                          (20, 50, '20-50元'), (50, 99999, '≥50元')):
        emit_layer(label, [x for x in rows if lo <= x['price'] < hi])

    # 交互: 时间结构 × 连续跌停
    out.append('\n[6] 交互: 开盘触跌停 × 连续跌停状态')
    for streak, label in ((1, '首个跌停'), (2, '连续第2个'), (3, '连续第3+个')):
        emit_layer(f'{label}+开盘触', [x for x in rows if x['dt_open'] and
                                       (x['dt_streak'] >= 3 if streak == 3 else x['dt_streak'] == streak)])
    # 交互: 开盘触 × 量能
    out.append('\n[7] 交互: 开盘触跌停 × 量能')
    for lo, hi, label in ((0, 1.0, '缩量<1x'), (1.0, 3.0, '平量1-3x'), (3.0, 99, '放量≥3x')):
        emit_layer(f'开盘触+{label}', [x for x in rows if x['dt_open'] and lo <= x['vr5'] < hi])

    with open(os.path.join(BASE, 'logs', 'limit_down_analysis_v3.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/limit_down_analysis_v3.txt')


if __name__ == '__main__':
    main()
