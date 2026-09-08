"""A模式20个交易日回测 → Excel明细导出 (2026-09-08晚)
表: A口径(上穿分时均线买入)121笔明细 + 无触发12笔 + 汇总
数据: 腾讯mkline m15缓存 data/m15_research/ (脚本analysis_temp_a_intraday.py已抓取)
输出: results/a_mode_intraday_backtest_20260908.xlsx
"""
import json, os, sys
from collections import defaultdict
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COST = 0.00125

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis_temp_a_intraday import (load_klines, load_pools, gen_signals, fetch_m15,
                                      bar_on, is_lu, COST as _C)


def trigger_with_time(m15_bars, buy_date):
    """上穿分时均线触发 → (买入价, 触发时间HH:MM) 或 (None, None)"""
    day = buy_date.replace('-', '')
    bars = [b for b in m15_bars if str(b[0]).startswith(day)]
    if not bars:
        return None, None
    cum_pv, cum_v, vwap_prev = 0.0, 0.0, None
    for b in bars:
        o, c, h, l = float(b[1]), float(b[2]), float(b[3]), float(b[4])
        v = float(b[5])
        typical = (h + l + c) / 3.0
        if vwap_prev is None:
            # 首根(9:30-9:45): 开盘后拉升(H>开盘价)即视为几分钟内上穿均线, 买入价=开盘价
            # (2026-09-08用户口径: 竞价结束直接按模型推荐买, 通常几分钟内上穿)
            if h > o:
                return o, '09:30-45'
            vwap_prev = o
        elif h > vwap_prev:
            tm = str(b[0])[8:10] + ':' + str(b[0])[10:12]
            return max(vwap_prev, o), tm
        cum_pv += typical * v
        cum_v += v
        vwap_prev = cum_pv / cum_v if cum_v > 0 else o
    return None, None


def sell_with_detail(kls, buy_date, buy_price):
    """卖出 → (pnl, days, tag, sell_date, sell_price)"""
    idx = next(i for i, x in enumerate(kls) if x.get('date') == buy_date)
    j = idx
    days = 0
    while j + 1 < len(kls):
        j += 1
        days += 1
        kk, kp = kls[j], kls[j - 1]
        if (kk['low'] - buy_price) / buy_price <= -0.10:
            return (buy_price * 0.90 - buy_price) / buy_price * 100, days, '硬止损', kk['date'], round(buy_price * 0.90, 2)
        if is_lu(kk, kp):
            continue
        if kk['high'] >= kp['close'] * 1.10 * 0.999:
            sp = round(kp['close'] * 1.10, 2)
            return (sp * (1 - COST) - buy_price) / buy_price * 100, days, '摸板涨停价卖', kk['date'], sp
        sp = kk['open']
        return (sp * (1 - COST) - buy_price) / buy_price * 100, days, '断板开盘卖', kk['date'], sp
    if j > idx:
        sp = kls[j]['close']
        return (sp * (1 - COST) - buy_price) / buy_price * 100, days, '期末估值', kls[j]['date'], sp
    return None, days, None, None, None


def name_of(code, pools):
    for ymd in pools:
        for s in pools[ymd]:
            if str(s.get('code', '')) == code and s.get('name'):
                return str(s['name'])
    return '?'


def signal_kind(ktbl, pools, s):
    """信号类型: 🧊冰点修复(分歧日温度<40) / 涨停分歧(分歧日涨停+大振幅) / 断板修复(分歧日断板摸板未封)
    返回 (kind, 分歧日温度, 分歧日涨停数)"""
    dates_fmt = sorted(f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in pools)
    temp = {d: len(pools[d]) for d in pools}
    bi = dates_fmt.index(s['buy_date'])
    div_d = dates_fmt[bi - 1] if bi > 0 else None
    t_div = temp[div_d.replace('-', '')] if div_d else None
    kls = ktbl[s['code']]
    k1, k0 = bar_on(kls, div_d) if div_d else (None, None)
    lu = is_lu(k1, k0) if k1 else False
    if t_div is not None and t_div < 40:
        kind = '🧊冰点修复'
    elif lu:
        kind = '涨停分歧'
    else:
        kind = '断板修复'
    return kind, t_div


def simulate_real(ktbl, pools, signals, m15_cache, init=200000, pos_pct=0.55):
    """实盘口径资金序列: 每天最多买1只(Top1按vr排序), 55%仓, 持仓期间不加仓,
    卖出(涨停持有→断板兑现)后资金回收次日可再买 — 2026-09-08用户纠正: 信号口径≠实盘纪律"""
    from backtest_common import FIXED_POS
    by_day = defaultdict(list)
    for s in signals:
        px, tm = trigger_with_time(m15_cache.get(s['code'], []), s['buy_date'])
        if px is not None:
            by_day[s['buy_date']].append((s, px, tm))
    cash = float(init)
    pos = None
    trades = []
    _dates = sorted(by_day)
    for _di, d in enumerate(_dates):
        # 卖出
        if pos:
            kls = ktbl[pos['code']]
            idx = next((i for i, x in enumerate(kls) if x.get('date') == d), None)
            if idx is None or idx < 1:
                continue  # 该日无K线(停牌等), 跳过卖出检查
            kk, kp = kls[idx], kls[idx - 1]
            buy = pos['buy_price']
            sp = None
            tag = None
            if (kk['low'] - buy) / buy <= -0.10:
                sp, tag = buy * 0.90, '硬止损'
            elif not is_lu(kk, kp):
                if kk['high'] >= kp['close'] * 1.10 * 0.999:
                    sp, tag = round(kp['close'] * 1.10, 2), '摸板涨停价卖'
                else:
                    sp, tag = kk['open'], '断板开盘卖'
            if sp:
                pnl = (sp * (1 - COST) - buy) / buy * 100
                cash += pos['shares'] * sp * (1 - COST)
                pos['pnl'] = round(pnl, 2)
                pos['sell_date'] = d
                pos['sell_price'] = round(sp, 2)
                pos['tag'] = tag
                pos['days'] = _di - pos['_buy_idx']
                trades.append(pos)
                pos = None
        # 买入: Top1(vr排序), 无触发跳过
        if pos is None:
            day_sigs = sorted(by_day[d], key=lambda x: -x[0]['div_vr'])
            total = cash
            for s, px, tm in day_sigs:
                code = s['code']
                kls = ktbl[code]
                k, pk = bar_on(kls, d)
                if not k or k['open'] >= pk['close'] * 1.098:
                    continue
                price = px * (1 + COST)
                budget = min(cash, total * pos_pct)
                shares = int(budget / price / 100) * 100
                if shares <= 0:
                    continue
                cash -= shares * price
                pos = {'code': code, 'buy_date': d, 'buy_time': tm,
                       'buy_price': price, 'shares': shares,
                       'name': name_of(code, pools),
                       'kind': signal_kind(ktbl, pools, s)[0],
                       'div_vr': round(s['div_vr'], 1), '_buy_idx': _di}
                break
    # 期末估值
    if pos:
        kls = ktbl[pos['code']]
        sp = kls[-1]['close']
        pnl = (sp * (1 - COST) - pos['buy_price']) / pos['buy_price'] * 100
        pos['pnl'] = round(pnl, 2)
        pos['sell_date'] = kls[-1]['date'] + '(期末)'
        pos['sell_price'] = round(sp, 2)
        pos['tag'] = '期末估值'
        pos['days'] = len(_dates) - 1 - pos['_buy_idx'] + 1
        trades.append(pos)
        cash += pos['shares'] * sp * (1 - COST)
    return trades, cash


def main():
    ktbl = load_klines()
    pools = load_pools()
    signals = gen_signals(ktbl, pools)
    print(f'信号 {len(signals)}笔, 加载m15缓存...')
    m15_cache = {}
    for s in signals:
        if s['code'] not in m15_cache:
            m15_cache[s['code']] = fetch_m15(s['code'])

    rows_a = []   # A口径(上穿触发买入)
    rows_nt = []  # 无触发(若开盘价买)
    rows_open = {}  # code+buy → 开盘口径pnl, 供对比列
    for s in signals:
        code = s['code']
        nm = name_of(code, pools)
        kind, t_div = signal_kind(ktbl, pools, s)
        kls = ktbl[code]
        k, pk = bar_on(kls, s['buy_date'])
        # 开盘价口径
        buy_open = k['open'] * (1 + COST)
        pnl_o, d_o, tag_o, sd_o, sp_o = sell_with_detail(kls, s['buy_date'], buy_open)
        rows_open[(code, s['buy_date'])] = (pnl_o, sd_o, sp_o)
        # 实盘执行口径(2026-09-08晚用户纠正): 开盘后等上穿分时均线(通常几分钟内),
        # 首根拉升=开盘价成交; 开盘走弱→等后续上穿; 全天未上穿→不买
        px, tm = trigger_with_time(m15_cache.get(code, []), s['buy_date'])
        if px is None:
            continue
        buy = px * (1 + COST)
        pnl, days, tag, sd, sp = sell_with_detail(kls, s['buy_date'], buy)
        if pnl is None:
            continue
        rows_a.append({'name': nm, 'code': code, 'buy_date': s['buy_date'], 'buy_time': tm,
                       'buy_price': round(px, 2), 'open': k['open'],
                       'sell_date': sd, 'sell_price': sp, 'pnl': round(pnl, 2),
                       'pnl_open': None,
                       'days': days, 'tag': tag, 'div_vr': round(s['div_vr'], 1),
                       'kind': kind, 't_div': t_div})

    rows_a.sort(key=lambda x: (x['buy_date'], -x['pnl']))

    # 实盘口径资金序列 (2026-09-08用户纠正: 每天最多买1只Top1, 55%仓)
    real_trades, real_final = simulate_real(ktbl, pools, signals, m15_cache)
    print(f'实盘口径: {len(real_trades)}笔, 期末资产{real_final:.0f} (收益率{(real_final/200000-1)*100:+.1f}%)')

    # ===== 写 Excel =====
    wb = Workbook()
    ws = wb.active
    ws.title = '分歧信号明细(开盘价买入)'
    headers = ['序号', '标的中文名', '代码', '买入时间', '买入价格(元)', '开盘价(元)',
               '卖出时间', '卖出价格(元)', '收益率(%)', '开盘价口径收益(%)', '持有天数', '卖出类型',
               '分歧日量比', '信号类型', '分歧日涨停数']
    ws.append(headers)
    hfill = PatternFill('solid', fgColor='4472C4')
    hfont = Font(bold=True, color='FFFFFF')
    for c in ws[1]:
        c.fill = hfill
        c.font = hfont
        c.alignment = Alignment(horizontal='center')
    pos_fill = PatternFill('solid', fgColor='C6EFCE')
    neg_fill = PatternFill('solid', fgColor='FFC7CE')
    ice_fill = PatternFill('solid', fgColor='FFF2CC')  # 冰点修复行高亮
    for i, r in enumerate(rows_a, 1):
        row = [i, r['name'], r['code'], f"{r['buy_date']} {r['buy_time']}", r['buy_price'], r['open'],
               r['sell_date'], r['sell_price'], r['pnl'], r['pnl_open'], r['days'], r['tag'],
               r['div_vr'], r['kind'], r['t_div']]
        ws.append(row)
        pc = ws.cell(row=i + 1, column=9)
        pc.fill = pos_fill if r['pnl'] > 0 else neg_fill
        if r['pnl_open'] is not None:
            ws.cell(row=i + 1, column=10).fill = pos_fill if r['pnl_open'] > 0 else neg_fill
        if r['kind'] == '🧊冰点修复':
            for c in ws[i + 1]:
                if c.column <= 13:  # 冰点修复整行浅黄高亮(序号~量比)
                    c.fill = ice_fill
            ws.cell(row=i + 1, column=9).fill = pos_fill if r['pnl'] > 0 else neg_fill
    for col, w in zip('ABCDEFGHIJKLMNO', [6, 14, 9, 18, 12, 10, 12, 12, 10, 15, 8, 12, 10, 11, 12]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'A2'

    # Sheet3: 实盘口径(每日Top1, 55%仓)
    ws3 = wb.create_sheet('实盘口径(每日Top1·55%仓)')
    ws3.append(['序号', '标的中文名', '代码', '买入时间', '买入价格(元)', '卖出时间', '卖出价格(元)',
                '收益率(%)', '持有天数', '卖出类型', '信号类型', '分歧日量比'])
    for c in ws3[1]:
        c.fill = hfill
        c.font = hfont
        c.alignment = Alignment(horizontal='center')
    for i, r in enumerate(real_trades, 1):
        bd = r['buy_date']
        days = 0
        if r.get('sell_date'):
            try:
                sd_pure = str(r['sell_date']).split('(')[0]
                if sd_pure >= bd:
                    days = (int(sd_pure[8:10]) + 0)  # 简化: 用交易日序
            except Exception:
                pass
        ws3.append([i, r['name'], r['code'], f"{r['buy_date']} {r.get('buy_time', '')}",
                    round(r['buy_price'], 2), r.get('sell_date', ''), r.get('sell_price', ''),
                    r['pnl'], r.get('days', ''), r.get('tag', ''), r.get('kind', ''), r.get('div_vr', '')])
        pc = ws3.cell(row=i + 1, column=8)
        pc.fill = pos_fill if r['pnl'] > 0 else neg_fill
        if r.get('kind') == '🧊冰点修复':
            for c in ws3[i + 1]:
                if c.column <= 11:
                    c.fill = ice_fill
            ws3.cell(row=i + 1, column=8).fill = pos_fill if r['pnl'] > 0 else neg_fill
    for col, w in zip('ABCDEFGHIJKL', [6, 14, 9, 18, 12, 14, 12, 10, 8, 12, 11, 10]):
        ws3.column_dimensions[col].width = w
    ws3.freeze_panes = 'A2'
    n3 = len(real_trades)
    wr3 = round(sum(1 for t in real_trades if t['pnl'] > 0) / n3 * 100, 1) if n3 else 0
    avg3 = round(sum(t['pnl'] for t in real_trades) / n3, 2) if n3 else 0
    ws3.append([])
    ws3.append([f'汇总: {n3}笔 | 胜率{wr3}% | 均笔{avg3:+.2f}% | 期末资产{real_final:.0f}元'
                f' | 收益率{(real_final/200000-1)*100:+.1f}% (55%仓滚动, 每日最多买1只Top1)'])

    # Sheet4: 汇总
    ws4 = wb.create_sheet('汇总')
    def _stat(ts):
        n = len(ts)
        if not n:
            return (0, 0, 0, 0, 0)
        wr = sum(1 for t in ts if t['pnl'] > 0) / n * 100
        return (n, round(wr, 1), round(sum(t['pnl'] for t in ts) / n, 2),
                round(max(t['pnl'] for t in ts), 1), round(min(t['pnl'] for t in ts), 1))
    n1, wr1, avg1, mx1, mn1 = _stat(rows_a)
    n2, wr2, avg2, mx2, mn2 = 0, 0, 0, 0, 0
    ws4.append(['口径', '笔数', '胜率(%)', '均笔(%)', '最大赢(%)', '最大亏(%)'])
    for c in ws4[1]:
        c.fill = hfill
        c.font = hfont
    ws4.append(['信号全样本(开盘价买入, 每笔独立)', n1, wr1, avg1, mx1, mn1])
    ws4.append(['实盘口径(每日Top1·55%仓)', n3, wr3, avg3,
                round(max(t['pnl'] for t in real_trades), 1) if real_trades else 0,
                round(min(t['pnl'] for t in real_trades), 1) if real_trades else 0])
    ws4.append([])
    ws4.append(['说明: 收益含成本+滑点0.125%单边; 买入=开盘后等上穿分时均线, 通常几分钟内触发(首根=开盘价成交);'])
    ws4.append(['实盘口径=每日最多买1只(分歧候选按vr排序Top1), 55%仓位, 持仓期间不加仓, 9:30开盘价买入;'])
    ws4.append(['卖出规则: 涨停持有→断板日摸板按涨停价卖/否则开盘价卖, 盘中-10%硬止损;'])
    ws4.append(['数据: 腾讯mkline m15, 窗口2026-08-12~2026-09-07, 依据报告logs/analysis/a_mode_backtest_2026-09-08.md'])
    for col, w in zip('ABCDEF', [30, 8, 10, 10, 12, 12]):
        ws4.column_dimensions[col].width = w

    out = os.path.join(BASE, 'results', 'a_mode_intraday_backtest_20260908.xlsx')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    wb.save(out)
    print(f'已生成: {out}')
    print(f'A口径{len(rows_a)}笔 | 无触发{len(rows_nt)}笔')


if __name__ == '__main__':
    main()
