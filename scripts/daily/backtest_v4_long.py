"""V4长期验证 (2026-08-25) — K线回算池(3年) + 6因子子集
背景: 同花顺池仅1年且9-10月缺失; 长期/3年用K线回算涨停池, 评分用6个K线可算因子
  (vr/gap/cons/dow/dt_risk/board_type — seal/zhaban/sector/divergence无池明细不可算)
权重: 最优权重子集重归一化(子集内占比保持)
四象限: 强弱×5月/12月 (强弱=区间日均涨停数: 强≥70/弱<60, 从3年滑动窗口自动切)
输出: logs/backtest_v4_long.txt
"""
import json, os, sys
from datetime import datetime, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
START, END = '2023-08-19', '2026-08-19'
INIT = 200000
COST = 0.00125
SUB_FACTORS = ['vr', 'gap', 'board_type', 'cons', 'dow', 'dt_risk']


def main():
    with open(os.path.join(BASE, 'data', 'scoring_config.json'), encoding='utf-8') as f:
        cfg = json.load(f)
    norm = cfg['v4']['normalize']
    full_w = cfg['v4']['weights']
    # 子集权重重归一化
    sub_total = sum(full_w[k] for k in SUB_FACTORS)
    sub_w = {k: full_w[k] * 100 / sub_total for k in SUB_FACTORS}

    # K线加载
    ktbl = {}
    for fn in os.listdir(KLINE_DIR):
        if not fn.endswith('.json') or fn.startswith('._'):
            continue
        code = fn.replace('.json', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        for enc in ('utf-8', 'gbk'):
            try:
                with open(os.path.join(KLINE_DIR, fn), encoding=enc) as f:
                    raw = json.load(f)
                kls = raw.get('data', raw) if isinstance(raw, dict) else raw
                ktbl[code] = kls
                break
            except Exception:
                continue
    print(f'K线: {len(ktbl)}只')

    def is_lu_pct(k, pk):
        if k.get('pct_change') is not None:
            return k['pct_change'] >= 9.8
        return pk and pk['close'] > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098

    # 每日涨停池+因子
    pool = defaultdict(set)
    for code, kls in ktbl.items():
        for i, k in enumerate(kls):
            if not isinstance(k, dict):
                continue
            date = k.get('date', '')
            if not (START <= date <= END) or i == 0:
                continue
            if is_lu_pct(k, kls[i - 1] if isinstance(kls[i - 1], dict) else None):
                pool[date].add(code)
    days = sorted(pool.keys())
    print(f'涨停事件日: {len(days)}')

    # 因子预计算
    def factor_of(code, date_fmt):
        kls = ktbl.get(code)
        if not kls:
            return None
        idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date_fmt), None)
        if idx is None or idx < 20:
            return None
        k, pk = kls[idx], kls[idx - 1]
        cons = 1
        j = idx - 1
        while j >= 1:
            if is_lu_pct(kls[j], kls[j - 1]):
                cons += 1
                j -= 1
            else:
                break
        vols = [kls[t]['volume'] for t in range(max(0, idx - 20), idx) if kls[t].get('volume', 0) > 0]
        vr = k['volume'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1.0
        gap = (k['open'] - pk['close']) / pk['close'] * 100 if pk['close'] > 0 else 0
        lu_price = round(pk['close'] * 1.10, 2)
        is_yz = k['open'] >= lu_price - 0.005 and k['low'] >= lu_price - 0.005
        is_tz = k['open'] >= lu_price - 0.005 and k['close'] >= lu_price - 0.005 and k['low'] < lu_price - 0.005
        board_type = '一字' if is_yz else ('T字' if is_tz else '换手')
        dow = ['周一', '周二', '周三', '周四', '周五'][datetime.strptime(date_fmt, '%Y-%m-%d').weekday()]
        if cons >= 3:
            dt_p = 30.5
        elif cons == 2:
            dt_p = 22.0
        elif vr >= 4:
            dt_p = 9.5
        elif vr < 1:
            dt_p = 4.1
        else:
            dt_p = 10.7
        f = {
            'vr': norm['vr'].get(('<0.5' if vr < 0.5 else '0.5-1' if vr < 1 else '1-2' if vr < 2 else '2-4' if vr < 4 else '>=4'), 50),
            'gap': norm['gap'].get(('<0' if gap < 0 else '0-2' if gap < 2 else '2-4' if gap < 4 else '4-6' if gap < 6 else '6-8' if gap < 8 else '8-10' if gap < 10 else '>=10'), 50),
            'board_type': norm['board_type'].get(board_type, 50),
            'cons': norm['cons'].get(('1' if cons == 1 else '2' if cons == 2 else '3' if cons == 3 else '4' if cons == 4 else '5+'), 55),
            'dow': norm['dow'].get(dow, 55),
            'dt_risk': max(10, min(100, 100 - (dt_p - 5) * 3)),
        }
        return f, board_type, cons, k, kls, idx

    def simulate(seg_days, pos_pct):
        cash = INIT
        pos = None
        trades = []
        for i, d in enumerate(seg_days):
            if pos is not None and i > 0:
                prev_d = seg_days[i - 1]
                kls = ktbl.get(pos['code'])
                if kls:
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    if idx1 is not None and idx0 is not None:
                        k1, k0 = kls[idx1], kls[idx0]
                        yest_lu = is_lu_pct(k1, kls[idx1 - 1] if idx1 > 0 else None)
                        today_lu = is_lu_pct(k0, kls[idx0 - 1] if idx0 > 0 else None)
                        gap = (k0['open'] - k1['close']) / k1['close'] * 100
                        loss = (k0['open'] - pos['buy_price']) / pos['buy_price'] * 100
                        if loss <= -10:
                            action = 'sell'
                        elif yest_lu and gap < 0:
                            action = 'sell'
                        elif yest_lu and today_lu:
                            action = 'hold'
                        elif yest_lu:
                            action = 'sell'
                        elif gap >= 4:
                            action = 'hold'
                        else:
                            action = 'sell'
                        if action == 'sell':
                            sell_price = k0['open'] * (1 - COST)
                            pnl = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                            cash += pos['shares'] * sell_price
                            trades.append({'pnl': pnl})
                            pos = None
            if pos is None and i > 0:
                prev_d = seg_days[i - 1]
                cands = []
                for c in pool.get(prev_d, set()):
                    r = factor_of(c, prev_d)
                    if not r:
                        continue
                    f, btype, cons, k, kls, idx = r
                    if btype == '一字' or cons >= 4:
                        continue
                    score = sum(sub_w[fac] * f[fac] for fac in SUB_FACTORS) / 100.0
                    cands.append((score, c))
                cands.sort(key=lambda x: -x[0])
                for score, c in cands:
                    if score < 50:
                        break
                    r = factor_of(c, d)
                    if not r:
                        continue
                    f0, _, _, k0, kls, idx0 = r
                    r_prev = factor_of(c, prev_d)
                    if not r_prev:
                        continue
                    k1 = r_prev[3]
                    gap = (k0['open'] - k1['close']) / k1['close'] * 100
                    if not (4.0 <= gap <= 8.0):
                        continue
                    price = k0['open'] * (1 + COST)
                    shares = int(min(cash, cash * pos_pct) / price / 100) * 100
                    if shares <= 0:
                        continue
                    cash -= shares * price
                    pos = {'code': c, 'buy_date': d, 'buy_price': price, 'shares': shares}
                    break
        final = cash
        if pos:
            kls = ktbl.get(pos['code'])
            if kls:
                final += pos['shares'] * kls[-1]['close'] * (1 - COST)
        return final, trades

    # 月度日均涨停
    month_avg = defaultdict(list)
    for d in days:
        month_avg[d[:7]].append(len(pool[d]))
    months = sorted(month_avg)
    for m in months:
        month_avg[m] = sum(month_avg[m]) / len(month_avg[m])

    def find_seg(ml, strong=True):
        best = None
        best_avg = -1 if strong else 999
        for i in range(len(months) - ml + 1):
            seg = months[i:i + ml]
            avg = sum(month_avg[m] for m in seg) / ml
            if strong and avg > best_avg:
                best_avg, best = avg, seg
            if not strong and avg < best_avg:
                best_avg, best = avg, seg
        return best, best_avg

    out = []
    out.append('=' * 80)
    out.append('V4长期验证 — K线回算池(3年) + 6因子子集权重重归一')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 子集权重: ' +
               ' '.join(f'{k}={sub_w[k]:.1f}' for k in SUB_FACTORS))
    out.append('=' * 80)
    for label, ml, strong, pct in (('强市短期(5月)', 5, True, 1.0), ('强市长期(12月)', 12, True, 1.0),
                                   ('弱市短期(5月)', 5, False, 0.5), ('弱市长期(12月)', 12, False, 0.5)):
        seg, avg = find_seg(ml, strong)
        if not seg:
            out.append(f'{label}: 无合适区间')
            continue
        seg_days = [d for d in days if seg[0] <= d[:7] <= seg[-1]]
        final, trades = simulate(seg_days, pct)
        ret = (final / INIT - 1) * 100
        n = len(trades)
        wr = sum(1 for t in trades if t['pnl'] > 0) / n * 100 if n else 0
        out.append(f'{label} ({seg[0]}~{seg[-1]}, 日均涨停{avg:.0f}只, {"全仓" if pct == 1 else "半仓"}): '
                   f'收益{ret:+.1f}% | 胜率{wr:.0f}% | {n}笔 | 期末{final:,.0f}')
    # 3年全程(稳健性, 半仓)
    final3, trades3 = simulate(days, 0.5)
    ret3 = (final3 / INIT - 1) * 100
    n3 = len(trades3)
    wr3 = sum(1 for t in trades3 if t['pnl'] > 0) / n3 * 100 if n3 else 0
    out.append(f'3年全程(半仓, 稳健性): 收益{ret3:+.1f}% | 胜率{wr3:.0f}% | {n3}笔')
    with open(os.path.join(BASE, 'logs', 'backtest_v4_long.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))


if __name__ == '__main__':
    main()
