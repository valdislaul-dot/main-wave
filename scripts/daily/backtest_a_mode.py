"""A模式完整回测 (2026-09-04用户拍板: 严格按照A的策略来)
A体系来源: 资料/干货_怎么选.doc(选股: 烂板出妖) + 资料/干货合集-卖点.docx(卖点体系) + logs/trader_a.json(执行口径)
选股: T-1爆量(vr>=2.0)+烂板(炸板>=1)涨停 → T日高开(gap>0)+缩量(vr<昨日) → 板块>=2只
      排序=缩量优先(今日vr升序), 买入=T日开盘价(含成本1.25‰)
卖出: 昨涨停: 低开→开盘卖 | 昨烂板: 今日缩量加速涨停→格局 / 连续爆量涨停→板砸(涨停价) / 未涨停→开盘卖
      | 昨强封: 前爆量今缩量 高开>=5%→格局 / 高开<5%→半仓出 | 前正常量 大高开>=5%→分歧卖(开盘) / 否则持有
      昨断板: 高开: 今日涨停→真反包格局 / 未涨停→开盘卖 | 深水(<=-5%)且<=3板→等自救(卖HIGH) | 其余开盘卖
      硬止损-10%盘中兜底
仓位: 55%滚动(A口径) | 本金10万
用法: python backtest_a_mode.py --excel [start_ymd] [end_ymd]  → 输出桌面
"""
import json, os, sys
from datetime import datetime
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
INIT = 100000
COST = 0.00125
POS_PCT = 0.55   # A的55%仓位滚动


def main():
    with open(os.path.join(BASE, 'data', 'scoring_config.json'), encoding='utf-8') as f:
        cfg = json.load(f)
    norm = cfg['v4']['normalize']

    klines_cache = {}
    def get_klines(code):
        if code in klines_cache:
            return klines_cache[code]
        for enc in ('utf-8', 'gbk'):
            try:
                with open(os.path.join(KLINE_DIR, f'{code}.json'), encoding=enc) as f:
                    raw = json.load(f)
                kls = raw.get('data', raw) if isinstance(raw, dict) else raw
                klines_cache[code] = kls
                return kls
            except Exception:
                continue
        klines_cache[code] = None
        return None

    def is_lu_pct(k, pk):
        if k.get('pct_change') is not None:
            return k['pct_change'] >= 9.8
        return pk and pk['close'] > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098

    ktbl = {}
    for fn in os.listdir(KLINE_DIR):
        if not fn.endswith('.json') or fn.startswith('._'):
            continue
        code = fn.replace('.json', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        kls = get_klines(code)
        if kls:
            ktbl[code] = kls
    print(f'K线: {len(ktbl)}只')

    ths_files = sorted(fn for fn in os.listdir(THS_DIR) if fn.endswith('.json')
                       and '20250601' <= fn.replace('.json', '') <= '20260819')
    all_dates = [fn.replace('.json', '') for fn in ths_files]
    ths_set = set(all_dates)

    _base_kls = ktbl.get('000001') or max(ktbl.values(), key=len)
    trade_dates = [x['date'].replace('-', '') for x in _base_kls
                   if isinstance(x, dict) and x.get('date')
                   and '20250601' <= x['date'].replace('-', '') <= '20260819']
    print(f'回测交易日: {trade_dates[0]} ~ {trade_dates[-1]} ({len(trade_dates)}天)')

    # 预计算: 每日池股因子 (f, btype, cons, k, vr, zh, heat)
    factor_days = {}
    for ymd in trade_dates:
        date_fmt = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
        info = []
        if ymd in ths_set:
            with open(os.path.join(THS_DIR, f'{ymd}.json'), encoding='utf-8') as f:
                info = json.load(f)
        day_map = {}
        word_freq = Counter()
        entries = []
        for s in info:
            code = str(s.get('code', ''))
            if not code or code.startswith(('300', '301', '688', '8', '9')):
                continue
            reason = s.get('reason_type', '')
            ws = [w for w in str(reason).replace('，', '+').split('+') if w.strip()]
            for w in ws:
                word_freq[w] += 1
            entries.append((code, s, ws))
        for code, s, ws in entries:
            kls = ktbl.get(code)
            if not kls:
                continue
            idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date_fmt), None)
            if idx is None or idx < 20:
                continue
            k = kls[idx]
            pk = kls[idx - 1]
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
            zh = int(s.get('open_num', 0) or 0)
            heat = max(word_freq[w] for w in ws) if ws else 0
            day_map[code] = (cons, vr, zh, heat)
        factor_days[date_fmt] = day_map
    print(f'因子预计算: {len(factor_days)}天')

    def vr_of(code, date_fmt):
        """某股某日量比(20日均量)"""
        kls = ktbl.get(code)
        if not kls:
            return None
        idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date_fmt), None)
        if idx is None or idx < 20:
            return None
        vols = [kls[t]['volume'] for t in range(max(0, idx - 20), idx) if kls[t].get('volume', 0) > 0]
        if not vols or sum(vols) <= 0:
            return 1.0
        return kls[idx]['volume'] / (sum(vols) / len(vols))

    def simulate(dates_fmt):
        cash = INIT
        pos = None
        trades = []
        for i, d in enumerate(dates_fmt):
            # ===== 卖出(A卖点体系) =====
            if pos is not None and i > 0:
                prev_d = dates_fmt[i - 1]
                kls = ktbl.get(pos['code'])
                if kls:
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    if idx1 is not None and idx0 is not None:
                        k1, k0 = kls[idx1], kls[idx0]
                        yest_lu = is_lu_pct(k1, kls[idx1 - 1] if idx1 > 0 else None)
                        today_lu = is_lu_pct(k0, kls[idx0 - 1] if idx0 > 0 else None)
                        gap = (k0['open'] - k1['close']) / k1['close'] * 100
                        loss_min = (k0['low'] - pos['buy_price']) / pos['buy_price'] * 100
                        zh_y = pos['zh_y']
                        vr_y = pos['vr_y']
                        vr_t = vr_of(pos['code'], d) or 1.0
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
                                reason = '昨涨停低开→竞价第一卖点'
                                sell_shares = pos['shares']
                            elif zh_y >= 1:
                                # 昨烂板: 弱转强观察
                                if today_lu and vr_t < vr_y:
                                    reason = 'hold'   # 缩量加速板→格局
                                elif today_lu and vr_t >= vr_y:
                                    sell_price = k0['close'] * (1 - COST)
                                    reason = '连续两日爆量→板砸(涨停价)'
                                    sell_shares = pos['shares']
                                else:
                                    sell_price = k0['open'] * (1 - COST)
                                    reason = '昨烂板弱转强失败→开盘卖'
                                    sell_shares = pos['shares']
                            else:
                                # 昨强封
                                if vr_y >= 2.0 and vr_t < vr_y:
                                    # 前爆量今缩量: 高开>=5%格局, <5%半仓出
                                    if gap >= 5:
                                        reason = 'hold'   # 加速格局
                                    else:
                                        sell_price = k0['open'] * (1 - COST)
                                        reason = '前爆量今缩量 高开<5%→竞价半仓出'
                                        sell_shares = pos['shares'] // 200 * 100
                                        if sell_shares <= 0:
                                            sell_price = k0['open'] * (1 - COST)
                                            reason = '前爆量今缩量 高开<5%→竞价全出(余量不足一手)'
                                            sell_shares = pos['shares']
                                else:
                                    # 前正常量: 大高开=分歧日第一卖点
                                    if gap >= 5:
                                        sell_price = k0['open'] * (1 - COST)
                                        reason = '连续正常量 大高开→分歧日第一卖点'
                                        sell_shares = pos['shares']
                                    else:
                                        reason = 'hold'
                        else:
                            # 昨断板
                            if gap >= 4:
                                if today_lu:
                                    reason = 'hold'   # 真反包弱转强→格局
                                else:
                                    sell_price = k0['open'] * (1 - COST)
                                    reason = '断板高开未反包→开盘卖'
                                    sell_shares = pos['shares']
                            elif gap <= -5 and pos['cons'] <= 3:
                                sell_price = k0['high'] * (1 - COST)
                                reason = '深水低开(<=-5%)且<=3板→等自救卖HIGH'
                                sell_shares = pos['shares']
                            else:
                                sell_price = k0['open'] * (1 - COST)
                                reason = '断板小亏/低开→开盘卖'
                                sell_shares = pos['shares']
                        if reason != 'hold' and sell_price is not None and sell_shares:
                            pnl = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                            cash += sell_shares * sell_price
                            trades.append({'pnl': pnl, 'buy_date': pos['buy_date'],
                                           'code': pos['code'], 'buy_price': pos['buy_price'],
                                           'sell_price': sell_price, 'sell_date': d,
                                           'gap': pos.get('gap'), 'reason': reason,
                                           'score': pos.get('score', 0), 'cons': pos['cons'],
                                           'w': pos.get('w', 1), 'cash_after': round(cash, 2),
                                           'pct': pos['pct'], 'temp': pos['temp'],
                                           'amount': pos['amount'],
                                           'shares_sold': sell_shares})
                            pos['shares'] -= sell_shares
                            if pos['shares'] <= 0:
                                pos = None
            # ===== 买入(A式放宽选股, 2026-09-04用户拍板): 昨涨停接力 + 板块>=2 + 今高开0~10% + 缩量优先; 不纳入300/688 =====
            if pos is None and i > 0:
                prev_d = dates_fmt[i - 1]
                cands = []
                for code, (cons, vr_y, zh_y, heat) in factor_days.get(prev_d, {}).items():
                    if heat < 2:
                        continue          # 板块>=2只(A干货条件)
                    kls = ktbl.get(code)
                    if not kls:
                        continue
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    if idx0 is None or idx1 is None:
                        continue
                    gap = (kls[idx0]['open'] - kls[idx1]['close']) / kls[idx1]['close'] * 100
                    if gap <= 0 or gap > 10:
                        continue          # 高开(0~10%宽窗口, A实测0.4%~10%)
                    vr_t = vr_of(code, d)
                    if vr_t is None:
                        continue
                    cands.append((-vr_t, code, gap, cons, vr_y, zh_y))
                cands.sort(key=lambda x: x[0])
                for _, code, gap, cons, vr_y, zh_y in cands:
                    kls = ktbl.get(code)
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    if idx0 is None:
                        continue
                    price = kls[idx0]['open'] * (1 + COST)
                    budget = cash * POS_PCT
                    shares = int(min(cash, budget) / price / 100) * 100
                    if shares <= 0:
                        continue
                    cash -= shares * price
                    pos = {'code': code, 'buy_date': d, 'buy_price': price, 'shares': shares,
                           'gap': gap, 'cons': cons, 'score': 0, 'w': 1,
                           'pct': POS_PCT, 'temp': 0, 'amount': round(shares * price, 2),
                           'vr_y': vr_y, 'zh_y': zh_y}
                    break
        final = cash
        if pos:
            kls = ktbl.get(pos['code'])
            if kls:
                last_k = next((x for x in kls if isinstance(x, dict) and x.get('date') == dates_fmt[-1]), None)
                if last_k is None:
                    last_k = kls[-1]
                final += pos['shares'] * last_k['close'] * (1 - COST)
                pos['end_price'] = last_k['close'] * (1 - COST)
        return final, trades, pos

    # ===== --excel 输出桌面 =====
    if '--excel' in sys.argv:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
        _ai = sys.argv.index('--excel')
        _ws_, _we_ = '20250601', '20250901'
        if len(sys.argv) > _ai + 2:
            _ws_, _we_ = sys.argv[_ai + 1], sys.argv[_ai + 2]
        win_fmt = [f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in trade_dates if _ws_ <= y <= _we_]
        print(f'Excel回测窗口: {win_fmt[0]} ~ {win_fmt[-1]} ({len(win_fmt)}个交易日)')
        name_map = {}
        for ymd in all_dates:
            with open(os.path.join(THS_DIR, f'{ymd}.json'), encoding='utf-8') as f:
                for s in json.load(f):
                    name_map[str(s.get('code', ''))] = s.get('name', '')
        final, trades, end_pos = simulate(win_fmt)
        wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100 if trades else 0
        avg = sum(t['pnl'] for t in trades) / len(trades) if trades else 0
        results_dir = os.path.dirname(BASE)
        xlsx_path = os.path.join(results_dir, f'a_mode_backtest_{win_fmt[0].replace("-","")}_{win_fmt[-1].replace("-","")}.xlsx')
        wb = Workbook()
        ws = wb.active
        ws.title = '汇总'
        head_font = Font(bold=True, color='FFFFFF')
        head_fill = PatternFill('solid', fgColor='C00000')
        rows = [
            [f'A模式回测汇总 ({win_fmt[0]} ~ {win_fmt[-1]}, 本金10万, 55%仓位滚动)'],
            ['选股规则', '昨涨停接力 + 板块>=2只 + 今日高开(0~10%宽窗口) → 缩量优先, 开盘价买入; 不纳入300/688 (2026-09-04用户拍板放宽)'],
            ['卖出规则', 'A卖点体系(干货合集-卖点): 低开竞价卖 | 烂板缩量加速格局/连续爆量板砸/弱转强失败卖 | 强封前爆量今缩量: 高开>=5%格局, <5%半仓出 | 连续正常量大高开>=5%分歧卖 | 断板反包格局/深水<=3板自救/其余开盘卖 | 硬止损-10%'],
            ['窗口', f'{win_fmt[0]} ~ {win_fmt[-1]}', f'{len(win_fmt)}个交易日'],
            [''],
            ['指标', '数值'],
            ['期末资金', f'{final:,.0f}'],
            ['总收益%', f'{(final/INIT-1)*100:+.1f}'],
            ['交易笔数', len(trades)],
            ['胜率%', f'{wr:.1f}'],
            ['均笔%', f'{avg:+.2f}'],
            ['期末持仓', (name_map.get(end_pos['code'], end_pos['code']) + f'@{end_pos["end_price"]:.2f}') if end_pos else '无'],
        ]
        for r in rows:
            ws.append(r)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for j in range(2, 5):
            for cell in ws[j]:
                cell.font = Font(bold=True)
        for cell in ws[6]:
            cell.font = head_font
            cell.fill = head_fill
        for col, w in (('A', 14), ('B', 110)):
            ws.column_dimensions[col].width = w
        wsx = wb.create_sheet('交易明细')
        headers = ['序号', '代码', '名称', '买入日', '卖出日', '持仓天数', '连板', '买入价', '卖出价',
                   '盈亏%', '卖出股数', '仓位%', '买入金额', '卖出后现金余额', '卖出原因']
        wsx.append(headers)
        for cell in wsx[1]:
            cell.font = head_font
            cell.fill = head_fill
        di = {d: i for i, d in enumerate(win_fmt)}
        pnl_rows = []
        for i, t in enumerate(trades, 1):
            days = di.get(t['sell_date'], 0) - di.get(t['buy_date'], 0)
            pnl_rows.append([i, t['code'], name_map.get(t['code'], ''), t['buy_date'], t['sell_date'],
                             days, t['cons'], round(t['buy_price'], 2), round(t['sell_price'], 2),
                             round(t['pnl'], 2), t.get('shares_sold', ''), f"{t['pct']*100:.0f}%",
                             t.get('amount', ''), t.get('cash_after', ''), t['reason']])
        if end_pos:
            pnl_rows.append([len(pnl_rows)+1, end_pos['code'], name_map.get(end_pos['code'], ''),
                             end_pos['buy_date'], '期末', '-', end_pos['cons'], round(end_pos['buy_price'], 2),
                             round(end_pos['end_price'], 2),
                             round((end_pos['end_price']-end_pos['buy_price'])/end_pos['buy_price']*100, 2),
                             '', f"{end_pos['pct']*100:.0f}%", end_pos.get('amount', ''),
                             f'{final:,.0f}', '期末持有(按末日收盘估值=期末账户资金)'])
        for row in pnl_rows:
            wsx.append(row)
        red = Font(color='CC0000'); green = Font(color='006100')
        for r in range(2, len(pnl_rows) + 2):
            v = wsx.cell(row=r, column=10).value
            if isinstance(v, (int, float)):
                wsx.cell(row=r, column=10).font = red if v > 0 else (green if v < 0 else Font())
        wsx.freeze_panes = 'A2'
        for c, wd in enumerate([6, 9, 11, 12, 12, 9, 6, 9, 9, 8, 10, 8, 12, 14, 32], 1):
            wsx.column_dimensions[get_column_letter(c)].width = wd
        try:
            wb.save(xlsx_path)
        except PermissionError:
            import time
            xlsx_path = os.path.join(results_dir, f'a_mode_backtest_{win_fmt[0].replace("-","")}_{win_fmt[-1].replace("-","")}_{time.strftime("%H%M%S")}.xlsx')
            wb.save(xlsx_path)
            print('⚠ 原文件名被占用, 已改用时间戳文件名')
        print(f'✓ Excel已生成: {xlsx_path}')
        return

    print('用法: python backtest_a_mode.py --excel [start_ymd] [end_ymd]')


if __name__ == '__main__':
    main()
