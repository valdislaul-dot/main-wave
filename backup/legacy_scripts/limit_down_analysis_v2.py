"""跌停开板分析 v2 — 按前日连板背景分层, 全指标透视
分层: 前日连板数 cons_prev = 0(未涨停)/1(首板)/2(2板)/3(3板)/4+(高位)
每层指标:
  触跌停次数 / 跌停开盘占比 / 跌停开盘开板率 / 全触跌停开板率 /
  地天板率 / 跌停开盘收盘分布(封死·微开·反弹1-3·3-6·≥6·地天) /
  次日均收益·上涨率·均gap·回封涨停率 / 开板与封死的次日对照
输出: logs/limit_down_analysis_v2.txt
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
                }
            if t:
                tbl[code] = (name, t)
    return tbl


def main():
    print('加载K线...')
    tbl = load_all()
    print(f'{len(tbl)}只')

    rows = []
    for code, (name, t) in tbl.items():
        is_st = 'ST' in name
        dates = sorted(t.keys())
        # 前日连板数回算
        cons_hist = {}   # date -> 该日连续涨停数
        cons = 0
        for i, d in enumerate(dates):
            if i == 0:
                cons_hist[d] = 0
                continue
            r = t[d]
            if is_lu(r['pct'], name):
                cons += 1
            else:
                cons = 0
            cons_hist[d] = cons
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
            touch = r['low'] <= dt_price + 0.005
            if not touch:
                continue
            dt_open = r['open'] <= dt_price + 0.005
            opened = r['close'] > dt_price + 0.005
            dt2lu = r['close'] >= lu_price - 0.005
            # 收盘反弹幅度(相对跌停价)
            reb = (r['close'] - dt_price) / dt_price * 100 if dt_price > 0 else 0
            rows.append({
                'code': code, 'name': name, 'date': d,
                'cons_prev': cons_hist[dates[i - 1]],
                'dt_open': dt_open, 'opened': opened, 'dt2lu': dt2lu,
                'reb': reb, 'close': r['close'],
            })

    # 次日数据
    nxt = {}
    for code, (name, t) in tbl.items():
        dates = sorted(t.keys())
        for i, d in enumerate(dates):
            if i + 1 < len(dates):
                nxt[(code, d)] = t[dates[i + 1]]

    out = []
    out.append('=' * 80)
    out.append('跌停开板分析 v2 — 按前日连板背景分层 (3年, 剔除300/301/688/8/9)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 触跌停样本: {len(rows)}')
    out.append('=' * 80)

    layers = [(0, '前日未涨停'), (1, '前日首板'), (2, '前日2板'), (3, '前日3板'), (4, '前日4板+')]

    def pct(v):
        return f'{v*100:.1f}%'

    for cons_th, label in layers:
        if cons_th == 4:
            items = [x for x in rows if x['cons_prev'] >= 4]
        else:
            items = [x for x in rows if x['cons_prev'] == cons_th]
        if len(items) < 30:
            continue
        out.append(f'\n━━━ {label} ({cons_th if cons_th < 4 else "≥4"}板背景) — 触跌停 {len(items)} 次 ━━━')

        # 基本指标
        dt_open_n = sum(1 for x in items if x['dt_open'])
        opened_n = sum(1 for x in items if x['opened'])
        dt2lu_n = sum(1 for x in items if x['dt2lu'])
        out.append(f'  跌停开盘: {dt_open_n}次({pct(dt_open_n/len(items))}) | '
                   f'跌停开盘→开板: {pct(sum(1 for x in items if x["dt_open"] and x["opened"])/dt_open_n) if dt_open_n else "N/A"} | '
                   f'全部触跌停→开板: {pct(opened_n/len(items))} | '
                   f'地天板: {dt2lu_n}次({pct(dt2lu_n/len(items))})')

        # 跌停开盘的收盘分布
        dt_open_items = [x for x in items if x['dt_open']]
        if dt_open_items:
            dist = defaultdict(int)
            for x in dt_open_items:
                if x['dt2lu']:
                    dist['地天板'] += 1
                elif not x['opened']:
                    dist['封死跌停'] += 1
                elif x['reb'] >= 6:
                    dist['反弹≥6%'] += 1
                elif x['reb'] >= 3:
                    dist['反弹3-6%'] += 1
                elif x['reb'] >= 1:
                    dist['反弹1-3%'] += 1
                else:
                    dist['微开<1%'] += 1
            out.append('  跌停开盘收盘分布: ' + ' | '.join(
                f'{k} {v}({pct(v/len(dt_open_items))})' for k, v in sorted(dist.items(), key=lambda x: -x[1])))

        # 次日表现(全部)
        rets, gaps, lu_rates = [], [], []
        for x in items:
            r1 = nxt.get((x['code'], x['date']))
            if not r1 or x['close'] <= 0 or r1['open'] <= 0 or r1['close'] <= 0:
                continue
            rets.append((r1['close'] - x['close']) / x['close'] * 100)
            gaps.append((r1['open'] - x['close']) / x['close'] * 100)
            lu_rates.append(1 if (r1['close'] - x['close']) / x['close'] >= 0.098 else 0)
        if len(rets) >= 20:
            up = sum(1 for r in rets if r > 0) / len(rets) * 100
            out.append(f'  次日(全部): {len(rets)}笔 均{sum(rets)/len(rets):+.2f}% 上涨率{up:.0f}% '
                       f'均gap{sum(gaps)/len(gaps):+.2f}% 回封涨停率{pct(sum(lu_rates)/len(lu_rates))}')

        # 次日: 开板 vs 封死
        for cond, slabel in ((lambda x: x['opened'], '开板'), (lambda x: not x['opened'], '封死')):
            sub = [x for x in items if cond(x)]
            rets2, gaps2 = [], []
            for x in sub:
                r1 = nxt.get((x['code'], x['date']))
                if not r1 or x['close'] <= 0 or r1['open'] <= 0 or r1['close'] <= 0:
                    continue
                rets2.append((r1['close'] - x['close']) / x['close'] * 100)
                gaps2.append((r1['open'] - x['close']) / x['close'] * 100)
            if len(rets2) >= 15:
                up2 = sum(1 for r in rets2 if r > 0) / len(rets2) * 100
                out.append(f'    次日[{slabel}]: {len(rets2)}笔 均{sum(rets2)/len(rets2):+.2f}% 上涨率{up2:.0f}% 均gap{sum(gaps2)/len(gaps2):+.2f}%')

    # 汇总对比表
    out.append('\n' + '=' * 80)
    out.append('汇总: 各连板背景核心指标对比')
    out.append('=' * 80)
    out.append(f'{"背景":<10} {"触跌停":>6} {"跌停开盘占比":>9} {"跌停开→开板率":>10} {"全开板率":>7} {"地天率":>6} {"次日均收益":>9} {"次日上涨率":>8}')
    for cons_th, label in layers:
        items = ([x for x in rows if x['cons_prev'] >= 4] if cons_th == 4
                 else [x for x in rows if x['cons_prev'] == cons_th])
        if len(items) < 30:
            continue
        dt_open_n = sum(1 for x in items if x['dt_open'])
        dto_open_rate = (sum(1 for x in items if x['dt_open'] and x['opened']) / dt_open_n) if dt_open_n else 0
        rets = []
        for x in items:
            r1 = nxt.get((x['code'], x['date']))
            if r1 and x['close'] > 0 and r1['open'] > 0 and r1['close'] > 0:
                rets.append((r1['close'] - x['close']) / x['close'] * 100)
        m = sum(rets) / len(rets) if len(rets) >= 20 else None
        up = sum(1 for r in rets if r > 0) / len(rets) * 100 if len(rets) >= 20 else None
        out.append(f'{label:<10} {len(items):>6} {pct(dt_open_n/len(items)):>9} {pct(dto_open_rate):>10} '
                   f'{pct(sum(1 for x in items if x["opened"])/len(items)):>7} '
                   f'{pct(sum(1 for x in items if x["dt2lu"])/len(items)):>6} '
                   f'{(f"{m:+.2f}%" if m is not None else "样本不足"):>9} '
                   f'{(f"{up:.0f}%" if up is not None else "-"):>8}')

    with open(os.path.join(BASE, 'logs', 'limit_down_analysis_v2.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/limit_down_analysis_v2.txt')


if __name__ == '__main__':
    main()
