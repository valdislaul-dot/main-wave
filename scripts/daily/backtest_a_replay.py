"""A真实买入回放 (2026-09-04): 用A的77笔真实买入(主升浪.xlsx), 套A卖点体系日线近似, 对比A实盘收益
用途: 分离"选股"与"卖出"的贡献 — 若回放≈A实盘则卖出模拟OK; 若远低于则选股端(或盘中细节)还有差距
卖出(日线近似): 低开开盘卖 | 昨烂板: 今缩量涨停格局/今爆量涨停板砸(涨停价)/未涨停开盘卖
| 昨强封: 前爆量今缩量 高开>=5%格局 / <5%半仓出 | 前正常量大高开>=5%分歧卖
| 断板: 高开今日涨停反包格局/深水<=3板自救(HIGH)/其余开盘卖 | 硬止损-10%
仓位: 固定单笔5.5万(10万本金55%), 卖出后现金可复用, 单持仓滚动
"""
import json, os, sys
from datetime import datetime, timedelta
from openpyxl import load_workbook

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
INIT = 100000
COST = 0.00125
POS_PCT = 0.55


def main():
    # A买入列表
    wb = load_workbook(os.path.join(BASE, '资料', '主升浪.xlsx'), data_only=True)
    ws = wb['Sheet1']
    def serial_to_date(s):
        return (datetime(1899, 12, 30) + timedelta(days=int(s))).strftime('%Y-%m-%d')
    buys = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        for i in range(0, 15, 3):
            if row[i] is None:
                continue
            d = serial_to_date(row[i])
            if row[i + 1]:
                buys.append((d, str(row[i + 1]).strip()))
    buys.sort()

    # name→code
    name2code = {}
    for fn in sorted(os.listdir(THS_DIR)):
        if not ('202601' <= fn[:6] <= '202608'):
            continue
        with open(os.path.join(THS_DIR, fn), encoding='utf-8') as f:
            for s in json.load(f):
                name2code[str(s.get('name', '')).strip()] = str(s.get('code', ''))
    # 池(昨烂板/炸板)
    pool_by_date = {}
    for fn in sorted(os.listdir(THS_DIR)):
        with open(os.path.join(THS_DIR, fn), encoding='utf-8') as f:
            d = json.load(f)
        ymd = fn.replace('.json', '')
        pool_by_date[f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'] = {str(s.get('code', '')): s for s in d}

    def kline(code):
        p = os.path.join(KLINE_DIR, f'{code}.json')
        if not os.path.exists(p):
            return None
        with open(p, encoding='utf-8') as f:
            kls = json.load(f)
        return kls.get('data', kls) if isinstance(kls, dict) else kls

    def is_lu_pct(k, pk):
        if k.get('pct_change') is not None:
            return k['pct_change'] >= 9.8
        return pk and pk['close'] > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098

    def vr_at(code, date):
        kls = kline(code)
        if not kls:
            return None
        idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date), None)
        if idx is None or idx < 20:
            return None
        vols = [kls[t]['volume'] for t in range(max(0, idx - 20), idx) if kls[t].get('volume', 0) > 0]
        if not vols:
            return None
        return kls[idx]['volume'] / (sum(vols) / len(vols))

    # A实盘月度收益(对照)
    a_monthly = {'2026-03': 17.7, '2026-04': 101.5, '2026-05': 19.1, '2026-06': -8.1, '2026-07': 77.3}

    cash = INIT
    pos = None
    trades = []
    # 交易日序列(A买入日期+后续, 用K线日历)
    kls0 = kline('000001')
    all_td = [x['date'] for x in kls0 if isinstance(x, dict) and x.get('date')]
    buy_map = {d: n for d, n in buys}
    sim_days = [d for d in all_td if '2026-03-01' <= d <= '2026-07-31']
    pending = [d for d, _ in buys]

    def sell_pos(pos, d, prev_d):
        nonlocal cash
        kls = kline(pos['code'])
        if not kls:
            return None
        idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
        idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
        if idx1 is None or idx0 is None:
            return None
        k1, k0 = kls[idx1], kls[idx0]
        yest_lu = is_lu_pct(k1, kls[idx1 - 1] if idx1 > 0 else None)
        today_lu = is_lu_pct(k0, kls[idx0 - 1] if idx0 > 0 else None)
        gap = (k0['open'] - k1['close']) / k1['close'] * 100
        loss_min = (k0['low'] - pos['buy_price']) / pos['buy_price'] * 100
        zh_y = pos['zh_y']
        vr_y = pos['vr_y']
        vr_t = vr_at(pos['code'], d) or 1.0
        reason = 'hold'
        sell_price = None
        sell_shares = None
        if loss_min <= -10:
            sell_price = pos['buy_price'] * 0.90
            reason = '硬止损-10%'
            sell_shares = pos['shares']
        elif yest_lu:
            if gap < 0:
                sell_price = k0['open'] * (1 - COST)
                reason = '低开→竞价卖'
                sell_shares = pos['shares']
            elif zh_y >= 1:
                if today_lu and vr_t < vr_y:
                    reason = 'hold'
                elif today_lu and vr_t >= vr_y:
                    sell_price = k0['close'] * (1 - COST)
                    reason = '连续爆量→板砸'
                    sell_shares = pos['shares']
                else:
                    sell_price = k0['open'] * (1 - COST)
                    reason = '弱转强失败→开盘卖'
                    sell_shares = pos['shares']
            else:
                if vr_y >= 2.0 and vr_t < vr_y:
                    if gap >= 5:
                        reason = 'hold'
                    else:
                        sell_price = k0['open'] * (1 - COST)
                        reason = '高开<5%→半仓出'
                        sell_shares = pos['shares'] // 200 * 100
                        if sell_shares <= 0:
                            reason = 'hold'
                else:
                    if gap >= 5:
                        sell_price = k0['open'] * (1 - COST)
                        reason = '大高开→分歧卖'
                        sell_shares = pos['shares']
                    else:
                        reason = 'hold'
        else:
            if gap >= 4:
                if today_lu:
                    reason = 'hold'
                else:
                    sell_price = k0['open'] * (1 - COST)
                    reason = '断板未反包→开盘卖'
                    sell_shares = pos['shares']
            elif gap <= -5 and pos['cons'] <= 3:
                sell_price = k0['high'] * (1 - COST)
                reason = '深水→自救HIGH'
                sell_shares = pos['shares']
            else:
                sell_price = k0['open'] * (1 - COST)
                reason = '断板→开盘卖'
                sell_shares = pos['shares']
        if reason != 'hold' and sell_price is not None and sell_shares:
            pnl = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
            cash += sell_shares * sell_price
            trades.append({'pnl': pnl, 'code': pos['code'], 'buy_date': pos['buy_date'],
                           'sell_date': d, 'reason': reason, 'shares_sold': sell_shares})
            pos['shares'] -= sell_shares
            if pos['shares'] <= 0:
                pos = None
        return pos

    i = 0
    while i < len(sim_days):
        d = sim_days[i]
        prev_d = sim_days[i - 1] if i > 0 else None
        # 卖出
        if pos is not None and prev_d:
            pos = sell_pos(pos, d, prev_d)
        # 买入(A的真实买入)
        if d in buy_map and pos is None:
            name = buy_map[d]
            code = name2code.get(name)
            if code:
                kls = kline(code)
                if not kls:
                    print(f'  [跳过] {d} {name}({code}): 无K线文件')
                    i += 1
                    continue
                idx = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                if idx is not None and idx > 0:
                    p = pool_by_date.get(prev_d, {}).get(code) if prev_d else None
                    zh_y = int(p.get('open_num', 0) or 0) if p else 0
                    vr_y = vr_at(code, prev_d) if prev_d else 1.0
                    cons = 1
                    j = idx - 1
                    while j >= 1:
                        if is_lu_pct(kls[j], kls[j - 1]):
                            cons += 1
                            j -= 1
                        else:
                            break
                    price = kls[idx]['open'] * (1 + COST)
                    budget = cash * POS_PCT
                    shares = int(min(cash, budget) / price / 100) * 100
                    if shares > 0:
                        cash -= shares * price
                        pos = {'code': code, 'buy_date': d, 'buy_price': price, 'shares': shares,
                               'cons': cons, 'vr_y': vr_y or 1.0, 'zh_y': zh_y}
        i += 1
    final = cash
    if pos:
        kls = kline(pos['code'])
        last_k = next((x for x in kls if isinstance(x, dict) and x.get('date') == sim_days[-1]), None) or kls[-1]
        final += pos['shares'] * last_k['close'] * (1 - COST)

    # 月度统计
    monthly = {}
    for t in trades:
        m = t['sell_date'][:7]
        monthly.setdefault(m, []).append(t['pnl'])
    print('=' * 70)
    print('A真实买入回放 (77笔买入 + A卖点体系日线近似, 55%仓位, 10万本金)')
    print('=' * 70)
    print(f'实际成交: {len(trades)}笔卖出(+期末持仓{1 if pos else 0})')
    wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100 if trades else 0
    avg = sum(t['pnl'] for t in trades) / len(trades) if trades else 0
    print(f'期末资金: {final:,.0f} | 总收益 {(final/INIT-1)*100:+.1f}% | 胜率 {wr:.1f}% | 均笔 {avg:+.2f}%')
    print()
    print('月度对比 (回放 vs A实盘):')
    for m in sorted(set(list(monthly.keys()) + list(a_monthly.keys()))):
        mp = sum(monthly.get(m, []))
        # 月度收益=该月卖出盈亏/期初资金近似
        print(f'  {m}: 回放月度盈亏合计 {mp:+.1f}% (按笔加总) | A实盘 {a_monthly.get(m, "?"):+}%')
    print()
    print('卖出原因分布:')
    from collections import Counter
    rc = Counter(t['reason'] for t in trades)
    for r, n in rc.most_common():
        print(f'  {r}: {n}笔')
    # 明细到Excel
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    name2code_r = {v: k for k, v in name2code.items()}
    out = os.path.join(os.path.dirname(BASE), 'a_replay_backtest_20260303_20260723.xlsx')
    wb2 = Workbook()
    wsx = wb2.active
    wsx.title = '回放明细'
    wsx.append(['序号', '代码', '名称', '买入日', '卖出日', '买入价', '卖出价', '盈亏%', '卖出股数', '卖出原因'])
    for i, t in enumerate(trades, 1):
        wsx.append([i, t['code'], name2code_r.get(t['code'], ''), t['buy_date'], t['sell_date'],
                    '', '', round(t['pnl'], 2), t['shares_sold'], t['reason']])
    wsx2 = wb2.create_sheet('汇总')
    wsx2.append(['A真实买入回放', f'期末资金{final:,.0f}', f'总收益{(final/INIT-1)*100:+.1f}%',
                 f'{len(trades)}笔', f'胜率{wr:.1f}%', f'均笔{avg:+.2f}%'])
    wsx2.append(['A实盘对照', '+411%(3-7月)', '4月+101.5%', '7月+77.3%', '', ''])
    try:
        wb2.save(out)
    except PermissionError:
        import time
        out = os.path.join(os.path.dirname(BASE), f'a_replay_backtest_{time.strftime("%H%M%S")}.xlsx')
        wb2.save(out)
    print(f'\n✓ Excel已生成: {out}')


if __name__ == '__main__':
    main()
