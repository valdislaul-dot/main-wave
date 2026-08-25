"""8-10%高开档的条件拆解 (2026-08-25)
问题: 模型一刀切8%上限(-5.13%全量), A的框架说大高开+分歧板是机会 — 哪些条件下8-10%是正的?
拆解维度: T-1爆量烂板回封 / 缩量 / 板数 / 封板与否
输出: logs/gap8_10_conditions.txt
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

    rows = []
    for code, (name, t) in tbl.items():
        dates = sorted(t.keys())
        for i, d in enumerate(dates):
            if i == 0 or i + 1 >= len(dates):
                continue
            r = t[d]
            if r['gap'] is None or not (8.0 <= r['gap'] < 10.0):
                continue
            r0 = t[dates[i - 1]]
            r1 = t[dates[i + 1]]
            if r0['close'] <= 0 or r1['open'] <= 0 or r1['close'] <= 0:
                continue
            # T-1特征
            prev_lu = is_lu(r0['pct'], name)
            prev_vol = r0['vol']
            # T-1是否爆量(近5日最高且≥2x均)
            vols5 = [t[dates[k]]['vol'] for k in range(max(0, i - 5), i - 1) if t[dates[k]]['vol'] > 0]
            prev_heavy = prev_vol > 0 and vols5 and prev_vol >= max(vols5) and prev_vol >= 2 * (sum(vols5) / len(vols5))
            # T日量比
            vols_t = [t[dates[k]]['vol'] for k in range(max(0, i - 5), i) if t[dates[k]]['vol'] > 0]
            vr_t = r['vol'] / (sum(vols_t) / len(vols_t)) if vols_t and sum(vols_t) > 0 else 0
            # 结果
            ret_t = (r['close'] - r['open']) / r['open'] * 100
            lu_t = is_lu(r['pct'], name)
            ret_t1 = (r1['close'] - r1['open']) / r1['open'] * 100
            rows.append({
                'prev_lu': prev_lu, 'prev_heavy': prev_heavy, 'vr_t': vr_t,
                'ret_t': ret_t, 'lu_t': lu_t, 'cum': ret_t + ret_t1,
            })

    out = []
    out.append('=' * 84)
    out.append('8-10%高开档条件拆解 (3年) — 哪些子集是正期望?')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 样本: {len(rows)}')
    out.append('=' * 84)

    def stat(label, items):
        if len(items) < 50:
            out.append(f'  {label}: 样本不足({len(items)})')
            return
        n = len(items)
        lu_rate = sum(1 for x in items if x['lu_t']) / n * 100
        m_t = sum(x['ret_t'] for x in items) / n
        m_cum = sum(x['cum'] for x in items) / n
        wins = sum(1 for x in items if x['cum'] > 0) / n * 100
        out.append(f'  {label:<30} {n:>5}笔 封板率{lu_rate:>4.0f}% 当日{m_t:>+6.2f}% 完整{m_cum:>+6.2f}% 正收益{wins:>4.0f}%')

    out.append('\n[基线]')
    stat('8-10%全量', rows)
    stat('4-8%全量(对照)', [])   # 占位

    out.append('\n[T-1状态]')
    stat('T-1涨停(连板背景)', [x for x in rows if x['prev_lu']])
    stat('T-1未涨停', [x for x in rows if not x['prev_lu']])

    out.append('\n[T-1爆量]')
    stat('T-1爆量', [x for x in rows if x['prev_heavy']])
    stat('T-1非爆量', [x for x in rows if not x['prev_heavy']])

    out.append('\n[T-1爆量 × T-1涨停 交叉]')
    stat('T-1爆量+涨停(A分歧事件)', [x for x in rows if x['prev_heavy'] and x['prev_lu']])
    stat('T-1爆量+未涨停', [x for x in rows if x['prev_heavy'] and not x['prev_lu']])
    stat('T-1非爆量+涨停', [x for x in rows if not x['prev_heavy'] and x['prev_lu']])

    out.append('\n[T日量比]')
    stat('T日缩量<1x', [x for x in rows if x['vr_t'] < 1])
    stat('T日平量1-3x', [x for x in rows if 1 <= x['vr_t'] < 3])
    stat('T日放量≥3x', [x for x in rows if x['vr_t'] >= 3])

    out.append('\n[A框架组合: T-1爆量涨停 + T日缩量]')
    stat('爆量分歧+缩量转强(A CONFIRMED)', [x for x in rows if x['prev_heavy'] and x['prev_lu'] and x['vr_t'] < 1])
    stat('爆量分歧+再爆量(A REJECT)', [x for x in rows if x['prev_heavy'] and x['prev_lu'] and x['vr_t'] >= 2])
    stat('爆量分歧+平量', [x for x in rows if x['prev_heavy'] and x['prev_lu'] and 1 <= x['vr_t'] < 2])

    with open(os.path.join(BASE, 'logs', 'gap8_10_conditions.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/gap8_10_conditions.txt')


if __name__ == '__main__':
    main()
