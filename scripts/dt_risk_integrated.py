"""跌停风险综合评估 (2026-08-21) — T日可用的全路径风险模型
方法: 条件概率链全路径积分
  P(触跌停) = Σ_gap P(gap|T特征) × P(触|T特征,gap)
  P(触且封死) = P(触) × (1-条件开板率)
  风险期望 = P(触且封死)×封死次日亏 + P(触且开板)×开板次日亏 + P(不触)×正常次日
输入: 仅T日已知特征(板数/量比/封板状态) — 无未来信息
输出: logs/dt_risk_integrated.txt
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

    rows = []
    for code, (name, t) in tbl.items():
        is_st = 'ST' in name
        dates = sorted(t.keys())
        for i, d in enumerate(dates):
            if i == 0 or i + 2 >= len(dates):
                continue
            r = t[d]
            if r['gap'] is None or not (4.0 <= r['gap'] <= 8.0):
                continue
            r1 = t[dates[i + 1]]
            r2 = t[dates[i + 2]]
            if r['close'] <= 0 or r1['open'] <= 0 or r1['close'] <= 0:
                continue
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
            # T+1
            gap1 = (r1['open'] - r['close']) / r['close'] * 100
            dt1 = limit_price(r['close'], is_st, up=False)
            touch1 = r1['low'] <= dt1 + 0.005
            opened1 = r1['close'] > dt1 + 0.005
            ret1 = (r1['close'] - r['open']) / r['open'] * 100
            # T+2 (封死跌停后的再隔日)
            ret2 = None
            if r2['open'] > 0 and r2['close'] > 0 and r1['close'] > 0:
                ret2 = (r2['close'] - r1['close']) / r1['close'] * 100
            rows.append({
                't_lu': t_lu, 'cons': cons, 'vr5': vr5,
                'gap1': gap1, 'touch1': touch1, 'opened1': opened1,
                'ret1': ret1, 'ret2': ret2,
            })

    out = []
    out.append('=' * 84)
    out.append('跌停风险综合评估 — T日可用的全路径模型 (3年, 竞价4-8%买入池)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 样本: {len(rows)}')
    out.append('=' * 84)

    def pct(v):
        return f'{v*100:.1f}%'

    def layer_stats(label, items):
        """给定T日特征子集 → 全路径综合统计"""
        if len(items) < 100:
            out.append(f'  {label}: 样本不足({len(items)})')
            return
        n = len(items)
        # 1. T+1竞价gap分布
        gap_dist = defaultdict(int)
        for x in items:
            g = x['gap1']
            if g < -4: gap_dist['深水<-4%'] += 1
            elif g < 0: gap_dist['低开-4~0%'] += 1
            elif g < 4: gap_dist['平开0-4%'] += 1
            elif g < 8: gap_dist['竞价窗4-8%'] += 1
            else: gap_dist['大高开≥8%'] += 1
        # 2. P(触跌停) 直接统计(等价于积分)
        touch = [x for x in items if x['touch1']]
        p_touch = len(touch) / n
        # 3. 触跌停条件下开板率
        p_open = sum(1 for x in touch if x['opened1']) / len(touch) if touch else 0
        p_seal = 1 - p_open
        # 4. 各路径期望收益
        not_touch = [x for x in items if not x['touch1']]
        seal = [x for x in touch if not x['opened1']]
        open_ = [x for x in touch if x['opened1']]
        m_not = sum(x['ret1'] for x in not_touch) / len(not_touch) if not_touch else 0
        m_seal = sum(x['ret1'] for x in seal) / len(seal) if seal else 0
        m_open = sum(x['ret1'] for x in open_) / len(open_) if open_ else 0
        # 综合期望(仅T+1)
        e1 = p_touch * (p_open * m_open + p_seal * m_seal) + (1 - p_touch) * m_not
        # 5. 封死跌停的T+2再跌
        m_seal2 = sum(x['ret2'] for x in seal if x['ret2'] is not None) / len([x for x in seal if x['ret2'] is not None]) if seal else 0
        out.append(f'  {label} ({n}笔):')
        out.append(f'    T+1竞价分布: ' + ' | '.join(f'{k} {pct(v/n)}' for k, v in sorted(gap_dist.items(), key=lambda x: -x[1])))
        out.append(f'    P(触跌停)={pct(p_touch)} | 触跌停后 开板率={pct(p_open)} 封死率={pct(p_seal)}')
        out.append(f'    全路径: P(触且封死)={pct(p_touch*p_seal)} | P(触且开板)={pct(p_touch*p_open)}')
        out.append(f'    T+1收益: 不触{m_not:+.2f}% | 开板{m_open:+.2f}% | 封死{m_seal:+.2f}%')
        out.append(f'    ★ 跌停风险期望(E[亏损部分]) = P(触且封死)×封死T+1亏 + P(触且开板)×开板T+1亏'
                   f' = {p_touch*p_seal*m_seal + p_touch*p_open*m_open:+.2f}%')
        out.append(f'    封死跌停的T+2再跌: {m_seal2:+.2f}%')
        out.append('')

    out.append('\n【综合评估】T日特征分层 → 全路径跌停风险')
    layer_stats('T日未涨停', [x for x in rows if x['cons'] == 0 and not x['t_lu']])
    layer_stats('T日首板', [x for x in rows if x['cons'] == 1 and x['t_lu']])
    layer_stats('T日2板', [x for x in rows if x['cons'] == 2 and x['t_lu']])
    layer_stats('T日3板+', [x for x in rows if x['cons'] >= 3 and x['t_lu']])
    layer_stats('T日炸板(高开未涨停)', [x for x in rows if not x['t_lu'] and x['cons'] >= 1])
    layer_stats('T日巨量≥4x', [x for x in rows if x['vr5'] >= 4])
    layer_stats('T日平量1-4x', [x for x in rows if 1 <= x['vr5'] < 4])
    layer_stats('T日缩量<1x', [x for x in rows if x['vr5'] < 1])

    with open(os.path.join(BASE, 'logs', 'dt_risk_integrated.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/dt_risk_integrated.txt')


if __name__ == '__main__':
    main()
