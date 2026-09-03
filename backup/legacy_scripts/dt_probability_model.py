"""T+1跌停概率/开板概率预测表 (2026-08-21)
模型A: T日竞价4-8%买入池 → T+1触跌停概率 (按T日板数/量比/封板状态分层)
模型B: T+1已触跌停 → 开板概率 (按T+1竞价gap × T日状态 × 量能 交叉查表)
数据: 3年K线 (2023-08~2026-08, 剔除300/301/688/8/9)
输出: logs/dt_probability_model.txt
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
            pc = None
            for r in rows:
                if not isinstance(r, dict):
                    continue
                date = r.get('date', '')
                if not (START <= date <= END):
                    continue
                cl = float(r.get('close', 0) or 0)
                op = float(r.get('open', 0) or 0)
                gap = (op - pc) / pc * 100 if pc and pc > 0 and op > 0 else None
                t[date] = {
                    'open': op, 'high': float(r.get('high', 0) or 0),
                    'low': float(r.get('low', 0) or 0), 'close': cl,
                    'gap': gap, 'pct': r.get('pct_change'),
                    'vol': float(r.get('volume_lots', 0) or 0),
                }
                pc = cl
            if t:
                tbl[code] = (name, t)
    return tbl


def main():
    print('加载K线...')
    tbl = load_all()
    print(f'{len(tbl)}只')

    rows = []   # 模型A池: T日竞价4-8%的股票
    for code, (name, t) in tbl.items():
        is_st = 'ST' in name
        dates = sorted(t.keys())
        for i, d in enumerate(dates):
            if i == 0 or i + 1 >= len(dates):
                continue
            r = t[d]
            if r['gap'] is None or not (4.0 <= r['gap'] <= 8.0):
                continue
            r1 = t[dates[i + 1]]
            r0 = t[dates[i - 1]]
            if r0['close'] <= 0 or r1['open'] <= 0:
                continue
            dt1 = limit_price(r['close'], is_st, up=False)
            touch_dt1 = r1['low'] <= dt1 + 0.005
            # T日特征
            t_lu = is_lu(r['pct'], name)
            cons = 0
            j = i - 1
            while j >= 1:
                if is_lu(t[dates[j]]['pct'], name):
                    cons += 1
                    j -= 1
                else:
                    break
            vols = [t[dates[k]]['vol'] for k in range(max(0, i - 5), i) if t[dates[k]]['vol'] > 0]
            vr5 = r['vol'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 0
            # T+1竞价gap
            gap1 = (r1['open'] - r['close']) / r['close'] * 100
            # T+1开板(若触跌停)
            opened1 = r1['close'] > dt1 + 0.005
            rows.append({
                't_lu': t_lu, 'cons': cons, 'vr5': vr5,
                'gap1': gap1, 'touch1': touch_dt1, 'opened1': opened1,
            })

    out = []
    out.append('=' * 80)
    out.append('T+1跌停概率/开板概率预测表 (3年, 模型买入池=竞价4-8%)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 买入池样本: {len(rows)}')
    out.append('=' * 80)

    def pct(v):
        return f'{v*100:.1f}%'

    # 模型A: T+1触跌停概率
    out.append('\n【模型A】T日竞价4-8%买入 → T+1触跌停概率')
    out.append(f'  全池基线: {pct(sum(1 for x in rows if x["touch1"])/len(rows))}')
    # A1: T日封板状态
    out.append('\n  A1. T日封板与否:')
    for label, cond in (('T日封板(收盘涨停)', lambda x: x['t_lu']),
                        ('T日炸板(高开未涨停)', lambda x: not x['t_lu'])):
        items = [x for x in rows if cond(x)]
        if len(items) < 50:
            continue
        touch_rate = sum(1 for x in items if x['touch1']) / len(items)
        out.append(f'    {label}: {len(items)}笔 → T+1触跌停率 {pct(touch_rate)}')
    # A2: T日量比
    out.append('\n  A2. T日量比(vs前5日):')
    for lo, hi, label in ((0, 1.0, '缩量<1x'), (1.0, 2.0, '平量1-2x'), (2.0, 4.0, '放量2-4x'), (4.0, 99, '巨量≥4x')):
        items = [x for x in rows if lo <= x['vr5'] < hi]
        if len(items) < 50:
            continue
        touch_rate = sum(1 for x in items if x['touch1']) / len(items)
        out.append(f'    {label}: {len(items)}笔 → T+1触跌停率 {pct(touch_rate)}')
    # A3: T日板数
    out.append('\n  A3. T日板数背景:')
    for cons_v, label in ((0, 'T日未涨停'), (1, 'T日首板'), (2, 'T日2板'), (3, 'T日3板+'), ):
        items = [x for x in rows if (x['cons'] >= 3 if cons_v == 3 else x['cons'] == cons_v)]
        if len(items) < 50:
            continue
        touch_rate = sum(1 for x in items if x['touch1']) / len(items)
        out.append(f'    {label}: {len(items)}笔 → T+1触跌停率 {pct(touch_rate)}')
    # A4: 交叉 T日封板 × T+1竞价gap
    out.append('\n  A4. T日封板 × T+1竞价gap → T+1触跌停率:')
    out.append(f'    {"T+1竞价gap":<14} {"T日封板":>12} {"T日炸板":>12}')
    for lo, hi, label in ((-99, -4, '深水<-4%'), (-4, 0, '低开-4~0%'), (0, 4, '平开0-4%'),
                          (4, 8, '竞价窗4-8%'), (8, 99, '大高开≥8%')):
        cells = []
        for cond in (lambda x: x['t_lu'], lambda x: not x['t_lu']):
            items = [x for x in rows if cond(x) and lo <= x['gap1'] < hi]
            if len(items) < 30:
                cells.append('样本不足')
            else:
                cells.append(pct(sum(1 for x in items if x['touch1']) / len(items)))
        out.append(f'    {label:<14} {cells[0]:>12} {cells[1]:>12}')

    # 模型B: 开板概率
    touch_rows = [x for x in rows if x['touch1']]
    out.append(f'\n【模型B】已触跌停 → 开板概率 (触跌停样本: {len(touch_rows)})')
    # B1: T+1竞价gap(跌停开vs深水vs低开)
    out.append('\n  B1. T+1竞价位置:')
    for lo, hi, label in ((-99, -9.5, '跌停开盘(gap≤-9.5%)'), (-9.5, -5, '深水-9.5~-5%'), (-5, -3, '低开-5~-3%'),
                          (-3, 0, '微低开-3~0%'), (0, 99, '平开/高开')):
        items = [x for x in touch_rows if lo <= x['gap1'] < hi]
        if len(items) < 30:
            continue
        out.append(f'    {label}: {len(items)}笔 → 开板率 {pct(sum(1 for x in items if x["opened1"])/len(items))}')
    # B2: 交叉 T日封板 × T+1竞价
    out.append('\n  B2. T日状态 × T+1竞价位置 → 开板率:')
    out.append(f'    {"T+1竞价位置":<16} {"T日封板":>10} {"T日炸板":>10}')
    for lo, hi, label in ((-99, -9.5, '跌停开'), (-9.5, -4, '深水'), (-4, 0, '低开'), (0, 99, '平开/高开')):
        cells = []
        for cond in (lambda x: x['t_lu'], lambda x: not x['t_lu']):
            items = [x for x in touch_rows if cond(x) and lo <= x['gap1'] < hi]
            if len(items) < 25:
                cells.append('样本不足')
            else:
                cells.append(pct(sum(1 for x in items if x['opened1']) / len(items)))
        out.append(f'    {label:<16} {cells[0]:>10} {cells[1]:>10}')
    # B3: T日量比
    out.append('\n  B3. T日量比 → 开板率:')
    for lo, hi, label in ((0, 1.0, 'T日缩量<1x'), (1.0, 3.0, 'T日平量1-3x'), (3.0, 99, 'T日放量≥3x')):
        items = [x for x in touch_rows if lo <= x['vr5'] < hi]
        if len(items) < 30:
            continue
        out.append(f'    {label}: {len(items)}笔 → 开板率 {pct(sum(1 for x in items if x["opened1"])/len(items))}')

    with open(os.path.join(BASE, 'logs', 'dt_probability_model.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/dt_probability_model.txt')


if __name__ == '__main__':
    main()
