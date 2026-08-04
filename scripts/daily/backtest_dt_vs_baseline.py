"""
回测: V2基线 vs V2+龙虎榜增强 (5个月, 2026-03-03 ~ 2026-07-24)

数据: stock_data.json (72只) + dt_block/ (龙虎榜+大宗历史)
"""

import json, os, sys, glob
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 加载 ──
def load_all():
    with open(os.path.join(BASE, 'data', 'stock_data.json'), encoding='utf-8') as f:
        sd = json.load(f)

    # name→code mapping from kline_data file names
    name2code = {}
    for kf in glob.glob(os.path.join(BASE, 'data', 'kline_data', '*.json')):
        fn = os.path.basename(kf).replace('.json', '')
        parts = fn.rsplit('_', 1)
        if len(parts) == 2:
            name2code[parts[0]] = parts[1]

    # dt_block: {YYYY-MM-DD: data}
    dt_all = {}
    dt_dir = os.path.join(BASE, 'data', 'dt_block')
    if os.path.exists(dt_dir):
        for fn in os.listdir(dt_dir):
            if fn.startswith('_') or not fn.endswith('.json'):
                continue
            date_key = fn.replace('.json', '')  # 2026-03-04
            for enc in ['utf-8', 'gbk']:
                try:
                    with open(os.path.join(dt_dir, fn), encoding=enc) as f:
                        dt_all[date_key] = json.load(f)
                    break
                except:
                    continue

    return sd, name2code, dt_all


# ── 工具 ──
def is_lu(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0:
        return False
    return close >= round(prev_close * (1 + lpct), 2) - 0.005

def lp(code):
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10


def v2_score(code, klines, idx):
    """V2.2 评分"""
    if idx < 25:
        return None, None

    t = klines[idx]
    pc = float(klines[idx-1]['close'])
    c = float(t['close'])
    o = float(t['open'])
    h = float(t['high'])
    l = float(t['low'])
    v = float(t['volume'])

    if not is_lu(c, pc, lp(code)):
        return None, None

    gap = round((o - pc) / pc * 100, 2) if pc > 0 else 0

    # 量比
    if idx >= 5:
        ma5 = sum(float(klines[j]['volume']) for j in range(idx-4, idx+1)) / 5
    else:
        ma5 = v
    if idx >= 20:
        ma20 = sum(float(klines[j]['volume']) for j in range(idx-19, idx+1)) / 20
    else:
        ma20 = v

    # 连板
    cons = 0
    for j in range(idx-1, max(idx-10, -1), -1):
        cj = float(klines[j]['close'])
        pj = float(klines[j-1]['close']) if j > 0 else 0
        if is_lu(cj, pj, lp(code)):
            cons += 1
        else:
            break

    vr = (v / ma5) if (cons >= 2 and ma5 > 0) else (v / ma20 if ma20 > 0 else 1)

    # 一字板
    is_ol = False
    true_ol = False
    if h > 0 and l > 0:
        if abs(h - l) < 0.001:
            true_ol = is_ol = True
        elif h > l:
            us = (h - max(o, c)) / (h - l)
            body = abs(c - o) / (h - l)
            is_ol = (us < 0.1 and body < 0.1)

    score = 0.0

    # 量比6档
    if vr < 0.3: score += 37
    elif vr < 0.5: score += 19
    elif vr < 0.7: score += 7
    elif vr < 1.0: score -= 1
    elif vr < 3.0: score -= 3

    # gap6档
    if gap >= 9: score += 20
    elif gap >= 7: score += 6
    elif gap >= 3: score += 1
    elif gap >= -1: score -= 5
    elif gap >= -3: score -= 3
    else: score += 2

    # 一字板
    if true_ol: score += 20
    elif is_ol: score += 10

    # 连板
    if cons == 0: score -= 4
    elif cons <= 2: score += 10
    else: score += 15

    # 周几
    dt_str = t.get('day', '')
    if dt_str:
        dt = datetime.strptime(dt_str, '%Y-%m-%d') + timedelta(days=1)
        while dt.weekday() >= 5: dt += timedelta(days=1)
        if dt.weekday() == 0: score += 2
        elif dt.weekday() == 4: score -= 1

    details = {'vr': round(vr, 2), 'gap': gap, 'cons': cons+1,
               'one_line': is_ol, 'true_one_line': true_ol,
               'close': c, 'open': o}

    return score, details


def dt_adjust(code, date_str, dt_all):
    """DT调整分 (从预存数据)"""
    day = dt_all.get(date_str)
    if not day:
        return 0

    adj = 0
    for d in day.get('dragon_tiger', []):
        if d.get('code') == code:
            nb = d.get('net_buy_wan', 0)
            bw = d.get('buy_wan', 0)
            if nb > 10000: adj += 3
            elif nb < -5000: adj -= 4
            if bw > 0 and nb / bw > 0.5: adj += 5
            elif bw > 0 and nb / bw > 0.2: adj += 2
            break

    for b in day.get('block_trades', []):
        if b.get('code') == code:
            prem = b.get('premium_pct', 0)
            amt = b.get('amount_wan', 0)
            if prem < -5 and amt > 500: adj -= 5
            elif prem < -3 and amt > 300: adj -= 3
            elif prem > 2 and amt > 300: adj += 4
            elif prem > 0 and amt > 500: adj += 2

    return adj


# ── 回测核心 ──
def simulate(sd, n2c, dt_all, date_list, use_dt):
    INIT = 200000
    cash = INIT
    holding = None
    trades = []

    for date_str in date_list:
        # ── 卖出 ──
        if holding:
            name = holding['name']
            kls = sd.get(name, [])
            day_kl = None
            di = -1
            for i, k in enumerate(kls):
                if k.get('day') == date_str:
                    day_kl = k
                    di = i
                    break

            if day_kl and di >= 2:
                o = float(day_kl['open'])
                c_p = float(day_kl['close'])
                h = float(day_kl['high'])
                pc = float(kls[di-1]['close'])

                code = holding['code']
                # 昨涨停?
                y_lu = is_lu(float(kls[di-1]['close']),
                            float(kls[di-2]['close']) if di >= 2 else 0,
                            lp(code))

                sell = False
                if y_lu and o < pc:
                    sell = True
                elif not y_lu:
                    gap = (o - pc) / pc * 100 if pc > 0 else 0
                    if gap < 4:
                        sell = True

                if sell:
                    sp = h if y_lu else (0.7 * (h + o) / 2 + 0.3 * c_p)
                    pnl = (sp - holding['bp']) / holding['bp'] * 100
                    cash += sp * holding['shares']
                    trades.append({
                        'buy_d': holding['bd'], 'sell_d': date_str,
                        'code': code, 'name': name,
                        'pnl': round(pnl, 2),
                        'score': holding['score'],
                        'dt_adj': holding.get('dt_adj', 0),
                    })
                    holding = None

        # ── 买入 ──
        if holding is None and cash > 0:
            cands = []
            for name, kls in sd.items():
                code = n2c.get(name)
                if not code or code.startswith(('300', '301', '688')):
                    continue

                # 找当天K线
                idx = None
                for i, k in enumerate(kls):
                    if k.get('day') == date_str:
                        idx = i
                        break
                if idx is None or idx < 25:
                    continue

                score, det = v2_score(code, kls, idx)
                if score is None:
                    continue

                # 风控
                if det.get('true_one_line'): continue
                if det.get('one_line') and det.get('cons', 1) >= 4: continue
                if score < 10: continue

                dta = dt_adjust(code, date_str, dt_all) if use_dt else 0
                cands.append({
                    'name': name, 'code': code,
                    'score': score, 'vr': det['vr'],
                    'open': det['open'], 'close': det['close'],
                    'dt_adj': dta, 'adj_score': score + dta,
                })

            if cands:
                cands.sort(key=lambda x: x['adj_score'] if use_dt else x['score'],
                          reverse=True)
                top3 = cands[:3]
                best = min(top3, key=lambda x: x['vr'])

                sh = int(cash / best['open'] / 100) * 100
                if sh > 0:
                    cash -= sh * best['open']
                    holding = {'name': best['name'], 'code': best['code'],
                              'bp': best['open'], 'shares': sh,
                              'bd': date_str, 'score': best['score'],
                              'dt_adj': best.get('dt_adj', 0),
                              'close': best['close']}

    # 清仓
    if holding:
        cash += holding['shares'] * holding['close']
    return trades, cash


# ── Main ──
def main():
    print("加载数据...")
    sd, n2c, dt_all = load_all()
    print(f"  stock_data: {len(sd)} 只 | name→code: {len(n2c)} 股 | dt_block: {len(dt_all)} 天")

    # 生成交易日
    dates = []
    d = datetime(2026, 3, 3)
    end = datetime(2026, 7, 27)
    while d <= end:
        if d.weekday() < 5:
            dates.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    print(f"  交易日: {len(dates)} ({dates[0]} → {dates[-1]})")

    # 过滤只有stock_data覆盖的日期
    valid_dates = []
    for ds in dates:
        covered = False
        for name, kls in sd.items():
            for k in kls:
                if k.get('day') == ds:
                    covered = True
                    break
            if covered:
                break
        if covered:
            valid_dates.append(ds)
    if not valid_dates:
        print("[ERROR] 无有效交易日: stock_data日期范围不覆盖回测区间")
        return
    dates = valid_dates

    print(f"  有效交易日: {len(valid_dates)}")

    print("\n[1/2] V2基线回测...")
    b_trades, b_cash = simulate(sd, n2c, dt_all, dates, use_dt=False)
    b_ret = (b_cash - 200000) / 200000 * 100
    b_wr = sum(1 for t in b_trades if t['pnl'] > 0) / max(len(b_trades), 1) * 100

    print("[2/2] V2+龙虎榜增强回测...")
    e_trades, e_cash = simulate(sd, n2c, dt_all, dates, use_dt=True)
    e_ret = (e_cash - 200000) / 200000 * 100
    e_wr = sum(1 for t in e_trades if t['pnl'] > 0) / max(len(e_trades), 1) * 100

    # ── 对比 ──
    print(f"\n{'='*65}")
    print(f"  回测结果: V2 基线 vs V2 + 龙虎榜增强")
    print(f"  区间: 2026-03-03 → 2026-07-27 (5个月, 初始200k)")
    print(f"{'='*65}")
    print(f"  {'指标':<22} {'V2基线':>12} {'V2+DT':>12} {'差异':>10}")
    print(f"  {'-'*56}")
    print(f"  {'最终资产':<22} {b_cash:>12,.0f} {e_cash:>12,.0f} {e_cash-b_cash:>+10,.0f}")
    print(f"  {'收益率':<22} {b_ret:>+11.1f}% {e_ret:>+11.1f}% {e_ret-b_ret:>+9.1f}%")
    print(f"  {'交易笔数':<22} {len(b_trades):>12} {len(e_trades):>12} {len(e_trades)-len(b_trades):>+10}")
    print(f"  {'胜率':<22} {b_wr:>11.1f}% {e_wr:>11.1f}% {e_wr-b_wr:>+9.1f}%")

    if b_trades:
        ba = sum(t['pnl'] for t in b_trades) / len(b_trades)
        ea = sum(t['pnl'] for t in e_trades) / max(len(e_trades), 1)
        print(f"  {'平均每笔':<22} {ba:>+11.2f}% {ea:>+11.2f}% {ea-ba:>+9.2f}%")
        bm = min(t['pnl'] for t in b_trades)
        em = min(t['pnl'] for t in e_trades) if e_trades else 0
        print(f"  {'最大单笔亏损':<22} {bm:>+11.2f}% {em:>+11.2f}%")

    # DT信号统计
    dt_sigs = [t for t in e_trades if t.get('dt_adj', 0) != 0]
    if dt_sigs:
        pos = [t for t in dt_sigs if t['dt_adj'] > 0]
        neg = [t for t in dt_sigs if t['dt_adj'] < 0]
        print(f"\n  龙虎榜信号 ({len(dt_sigs)}/{len(e_trades)}笔):")
        if pos:
            print(f"    正面{len(pos)}笔 均收益{sum(t['pnl'] for t in pos)/len(pos):+.2f}%")
        if neg:
            print(f"    负面{len(neg)}笔 均收益{sum(t['pnl'] for t in neg)/len(neg):+.2f}%")

    # 结论
    print(f"\n  {'='*56}")
    if e_ret > b_ret + 1:
        print(f"  ✅ DT因子有效: +{e_ret-b_ret:.1f}% 收益提升")
    elif abs(e_ret - b_ret) < 1:
        print(f"  ➖ DT因子无明显差异")
    else:
        print(f"  ❌ DT因子负向: {e_ret-b_ret:.1f}%")

    # 保存详细记录
    out = {
        'baseline': {'trades': b_trades, 'cash': b_cash, 'ret': b_ret, 'wr': b_wr},
        'enhanced': {'trades': e_trades, 'cash': e_cash, 'ret': e_ret, 'wr': e_wr},
    }
    out_path = os.path.join(BASE, 'logs', 'backtest_dt_comparison.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n详细记录: {out_path}")


if __name__ == '__main__':
    main()
