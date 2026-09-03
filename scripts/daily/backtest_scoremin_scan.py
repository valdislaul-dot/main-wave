"""score_min 门槛扫描 (2026-09-04)
基于 backtest_v4.py 的预计算+模拟框架, 只把买入门槛参数化:
- 窗口: ths历史池全可用段 2025-09-01 ~ 2026-08-19 (约一年)
- 仓位分段(定稿口径): 弱市段(<=2026-03-03)半仓 | 强市段(03-04~07-24)全仓 | 尾部退潮段(07-25~)半仓
- 交易口径: T日开盘价买入(含成本1.25‰) Top1优先 / 卖出=模型决策树定卖/留(硬止损-10%盘中兜底,
  昨涨停低开弱转强失败卖, 昨断板gap<4卖, 否则留) + 决定卖→开盘价成交(2026-09-04用户确认口径)
- 扫描: score_min in [40,45,50,55,60,65]
用法: python backtest_scoremin_scan.py
"""
import json, os, sys
from datetime import datetime
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_common import parse_window, has_window_args, temp_position

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
# 窗口: 缺省2025-06-01~2026-08-19, 可用 --months N / --start/--end 覆盖 (2026-09-04用户定稿)
W_START, W_END = parse_window('2025-06-01', '2026-08-19')
INIT = 100000
COST = 0.00125   # 滑点+佣金
FACTORS = ['vr', 'gap', 'board_type', 'cons', 'seal', 'zhaban', 'sector', 'divergence', 'dt_risk', 'turnover']


def gap_weight(gap, lo=4.0, hi=8.0, band=1.0):
    """梯形平滑窗口: [lo,hi]核心=1, 边缘带线性衰减到0, 带外=0
    band=1.0 → 进入带[3,4) 退出带(8,9]; band=0 → 退化为硬边界"""
    if band <= 0:
        return 1.0 if lo <= gap <= hi else 0.0
    if gap < lo - band or gap > hi + band:
        return 0.0
    if gap < lo:
        return (gap - (lo - band)) / band
    if gap > hi:
        return (hi + band - gap) / band
    return 1.0


def load_config_v4():
    with open(os.path.join(BASE, 'data', 'scoring_config.json'), encoding='utf-8') as f:
        return json.load(f)['v4']


def main():
    cfg4 = load_config_v4()
    norm = cfg4['normalize']
    weights = cfg4['weights']

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

    # 加载1年K线表(内存)
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

    # 全部ths文件 (2026-09-04已用同花顺API补齐6月缺失段; 窗口参数化)
    ths_files = sorted(fn for fn in os.listdir(THS_DIR) if fn.endswith('.json')
                       and W_START.replace('-', '') <= fn.replace('.json', '') <= W_END.replace('-', ''))
    all_dates = [fn.replace('.json', '') for fn in ths_files]
    print(f'回测窗口: {all_dates[0]} ~ {all_dates[-1]} ({len(all_dates)}个交易日)')

    def seg_of(ymd):
        if ymd <= '20260303':
            return 'weak', 0.5
        if ymd <= '20260724':
            return 'strong', 1.0
        return 'tail', 0.5

    # ===== 预计算: 每日每股票因子 =====
    ths_set = set(all_dates)
    # 交易日列表(基准K线日期列), 窗口跟随W_START/W_END (2026-09-04参数化)
    _base_kls = ktbl.get('000001') or max(ktbl.values(), key=len)
    trade_dates = [x['date'].replace('-', '') for x in _base_kls
                   if isinstance(x, dict) and x.get('date')
                   and W_START.replace('-', '') <= x['date'].replace('-', '') <= W_END.replace('-', '')]
    print(f'回测交易日: {trade_dates[0]} ~ {trade_dates[-1]} ({len(trade_dates)}天)')
    factor_days = {}
    temp_of = {}
    for ymd in trade_dates:
        date_fmt = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
        # 池数据(2026-09-04用户指令: 不自建, 只用真实拉取; 无文件=该日池空=温度0极弱不买)
        info = []
        if ymd in ths_set:
            with open(os.path.join(THS_DIR, f'{ymd}.json'), encoding='utf-8') as f:
                info = json.load(f)
        temp_of[date_fmt] = len(info)
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
            gap = (k['open'] - pk['close']) / pk['close'] * 100 if pk['close'] > 0 else 0
            lu_price = round(pk['close'] * 1.10, 2)
            is_yz = k['open'] >= lu_price - 0.005 and k['low'] >= lu_price - 0.005
            is_tz = k['open'] >= lu_price - 0.005 and k['close'] >= lu_price - 0.005 and k['low'] < lu_price - 0.005
            board_type = '一字' if is_yz else ('T字' if is_tz else '换手')
            try:
                to = float(s.get('turnover_rate', 0) or 0)
            except Exception:
                to = 0
            to_b = '<2' if to < 2 else ('2-20' if to < 20 else '>=20')
            try:
                seal_hm = datetime.fromtimestamp(int(s.get('first_limit_up_time'))).strftime('%H%M')
            except Exception:
                seal_hm = '1500'
            seal_b = '<5min' if seal_hm <= '0935' else ('5-10min' if seal_hm <= '0940' else (
                '10-30min' if seal_hm <= '1000' else ('30-60min' if seal_hm <= '1030' else '>60min')))
            zh = int(s.get('open_num', 0) or 0)
            zh_b = '0' if zh == 0 else ('1' if zh == 1 else ('2' if zh == 2 else '3+'))
            heat = max(word_freq[w] for w in ws) if ws else 0
            sec_b = '<3' if heat < 3 else ('3-4' if heat < 5 else ('5-9' if heat < 10 else '>=10'))
            div_b = '分歧' if (zh >= 1 and vr >= 1.5) else '非分歧'
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
                'seal': norm['seal'].get(seal_b, 60),
                'zhaban': norm['zhaban'].get(zh_b, 70),
                'sector': norm['sector'].get(sec_b, 70),
                'divergence': norm['divergence'].get(div_b, 55),
                'dt_risk': max(10, min(100, 100 - (dt_p - 5) * 3)),
                'turnover': norm.get('turnover', {}).get(to_b, 50),
            }
            day_map[code] = (f, board_type, cons, k, vr)
        factor_days[date_fmt] = day_map
    print(f'因子预计算: {len(factor_days)}天')

    # ===== 交易模拟(score_min参数化, gap_mode硬边界/平滑, sort_mode排序组合) =====
    def simulate(dates_fmt, score_min, pos_pct_fn, gap_mode='hard', band=1.0,
                 sort_mode='mul', add_k=10.0, buy_allow_fn=None, select_mode='v4'):
        cash = INIT
        pos = None
        trades = []
        for i, d in enumerate(dates_fmt):
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
                        # 卖出口径(2026-09-04用户确认): 模型决策树定卖/留, 决定卖→开盘前挂单开盘价成交
                        if loss_min <= -10:
                            sell_price = pos['buy_price'] * 0.90
                            reason = '硬止损-10%(盘中兜底)'
                        elif yest_lu and gap < 0 and not today_lu:
                            sell_price = k0['open'] * (1 - COST)
                            reason = '昨涨停低开弱转强失败→开盘价卖'
                        elif not yest_lu and gap < 4 and not today_lu:
                            sell_price = k0['open'] * (1 - COST)
                            reason = '昨断板gap<4→开盘价卖'
                        else:
                            reason = 'hold'
                        if reason != 'hold':
                            pnl = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                            cash += pos['shares'] * sell_price
                            trades.append({'pnl': pnl, 'buy_date': pos['buy_date'],
                                           'code': pos['code'], 'buy_price': pos['buy_price'],
                                           'sell_price': sell_price, 'sell_date': d,
                                           'gap': pos.get('gap'), 'reason': reason,
                                           'score': pos['score'], 'cons': pos['cons'],
                                           'w': pos['w'], 'cash_after': round(cash, 2),
                                           'pct': pos.get('pct'), 'temp': pos.get('temp'),
                                           'amount': pos.get('amount')})
                            pos = None
            if pos is None and i > 0 and (buy_allow_fn is None or buy_allow_fn(d)):
                prev_d = dates_fmt[i - 1]
                cands = []
                for code, (f, btype, cons, k, vr_raw) in factor_days.get(prev_d, {}).items():
                    if btype == '一字' or (cons >= 4 and btype in ('一字', 'T字')):
                        continue
                    if select_mode == 'a_shrink':
                        # A式选股(2026-09-04对比验证): 回避爆量>=2x, 缩量优先(vr升序)
                        if vr_raw >= 2.0:
                            continue
                        score = sum(weights[fac] * f[fac] for fac in FACTORS) / 100.0
                        if score < score_min:
                            continue
                        key = -vr_raw
                    else:
                        score = sum(weights[fac] * f[fac] for fac in FACTORS) / 100.0
                        if score < score_min:
                            continue
                    kls = ktbl.get(code)
                    if not kls:
                        continue
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    if idx0 is None or idx1 is None:
                        continue
                    gap = (kls[idx0]['open'] - kls[idx1]['close']) / kls[idx1]['close'] * 100
                    if gap_mode == 'smooth':
                        w = gap_weight(gap, band=band)
                        if w <= 0:
                            continue
                        if select_mode != 'a_shrink':
                            if sort_mode == 'qual':
                                key = score          # w仅作资格, 纯评分排序
                            elif sort_mode == 'add':
                                key = score + add_k * w   # 加法: gap权重只作有限加分
                            else:
                                key = score * w      # 乘法(数据裁决最优)
                    else:
                        if not (4.0 <= gap <= 8.0):
                            continue
                        w = 1.0
                        if select_mode != 'a_shrink':
                            key = score
                    cands.append((key, code, gap, score, cons, w))
                cands.sort(key=lambda x: -x[0])
                for key, code, gap, score, cons, w in cands:
                    kls = ktbl.get(code)
                    if not kls:
                        continue
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    if idx0 is None:
                        continue
                    price = kls[idx0]['open'] * (1 + COST)
                    budget = cash * pos_pct_fn(d)
                    shares = int(min(cash, budget) / price / 100) * 100
                    if shares <= 0:
                        continue
                    cash -= shares * price
                    pos = {'code': code, 'buy_date': d, 'buy_price': price, 'shares': shares,
                           'gap': gap, 'score': score, 'cons': cons, 'w': w,
                           'pct': pos_pct_fn(d), 'temp': temp_of.get(d, 0),
                           'amount': round(shares * price, 2)}
                    break
        final = cash
        end_val = 0.0
        if pos:
            kls = ktbl.get(pos['code'])
            if kls:
                last_k = next((x for x in kls if isinstance(x, dict) and x.get('date') == dates_fmt[-1]), None)
                if last_k is None:
                    last_k = kls[-1]
                end_val = pos['shares'] * last_k['close'] * (1 - COST)
                final += end_val
                pos['end_price'] = last_k['close'] * (1 - COST)
        return final, trades, pos

    def stats(final, trades, label, seg_filter=None):
        ts = [t for t in trades] if seg_filter is None else [t for t in trades if seg_of(t['buy_date'])[0] == seg_filter]
        ret = (final / INIT - 1) * 100 if seg_filter is None else None
        wr = sum(1 for t in ts if t['pnl'] > 0) / len(ts) * 100 if ts else 0
        avg = sum(t['pnl'] for t in ts) / len(ts) if ts else 0
        return ret, len(ts), wr, avg

    dates_fmt = [f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in trade_dates]
    seg_dates = {
        'weak': [d for d in dates_fmt if seg_of(d.replace('-', ''))[0] == 'weak'],
        'strong': [d for d in dates_fmt if seg_of(d.replace('-', ''))[0] == 'strong'],
        'tail': [d for d in dates_fmt if seg_of(d.replace('-', ''))[0] == 'tail'],
    }

    # ===== --detail 交易明细抽查(门槛50) =====
    if '--detail' in sys.argv:
        ms = int(sys.argv[sys.argv.index('--detail') + 1]) if len(sys.argv) > sys.argv.index('--detail') + 1 else 50
        final, trades, _pos = simulate(dates_fmt, ms, lambda d: seg_of(d.replace('-', ''))[1])
        names = {}
        for ymd, day in factor_days.items():
            pass
        # 股票名: 从ths池文件映射
        name_map = {}
        for ymd in all_dates:
            with open(os.path.join(THS_DIR, f'{ymd}.json'), encoding='utf-8') as f:
                for s in json.load(f):
                    name_map[str(s.get('code', ''))] = s.get('name', '')
        print(f'\n===== 门槛{ms} 交易明细(前25笔) =====')
        di = {d: i for i, d in enumerate(dates_fmt)}
        for t in trades[:25]:
            days = di.get(t['sell_date'], 0) - di.get(t['buy_date'], 0)
            print(f"{t['buy_date']}→{t['sell_date']} {name_map.get(t['code'], t['code'])} "
                  f"买{t['buy_price']:.2f} 卖{t['sell_price']:.2f} {t['pnl']:+6.2f}% ({days}日)")
        import statistics
        days = [di.get(t['sell_date'], 0) - di.get(t['buy_date'], 0) for t in trades]
        print(f'持仓天数: 中位{statistics.median(days):.0f} 均{statistics.mean(days):.1f} 最长{max(days)}')
        print(f'均笔{statistics.mean(t["pnl"] for t in trades):+.2f}% 胜率{sum(1 for t in trades if t["pnl"]>0)/len(trades)*100:.1f}%')
        print(f'期末(滚动复利口径): {(final/INIT-1)*100:+.1f}%  | 期末估值包含持仓')
        return

    # ===== --gapmode gap平滑窗口对比扫描 =====
    if '--gapmode' in sys.argv:
        pos_pct_fn = lambda d: seg_of(d.replace('-', ''))[1]
        print('\n' + '=' * 100)
        print('gap 窗口与排序组合对比 (无评分门槛, 窗口 %s ~ %s, 弱市半仓/强市全仓)' % (dates_fmt[0], dates_fmt[-1]))
        print('=' * 100)
        combos = [
            ('hard 4-8%硬边界', dict(gap_mode='hard', band=0)),
            ('smooth×mul 乘法', dict(gap_mode='smooth', band=1.0, sort_mode='mul')),
            ('smooth+add k=10', dict(gap_mode='smooth', band=1.0, sort_mode='add', add_k=10.0)),
            ('smooth+add k=20', dict(gap_mode='smooth', band=1.0, sort_mode='add', add_k=20.0)),
            ('smooth 资格制', dict(gap_mode='smooth', band=1.0, sort_mode='qual')),
        ]
        for label, kw in combos:
            final, trades, _pos = simulate(dates_fmt, 0, pos_pct_fn, **kw)
            wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100 if trades else 0
            avg = sum(t['pnl'] for t in trades) / len(trades) if trades else 0
            print(f'{label:<18}: 总收益{(final/INIT-1)*100:+8.1f}% | {len(trades):>3}笔 | 胜率{wr:4.1f}% | 均笔{avg:+5.2f}%')
            if kw.get('gap_mode') == 'smooth':
                edges = [t for t in trades if t.get('gap') is not None and (t['gap'] < 4 or t['gap'] > 8)]
                eavg = sum(t['pnl'] for t in edges) / len(edges) if edges else 0
                print(f'    └ 边缘带(3-4%/8-9%)交易: {len(edges)}笔 均笔{eavg:+.2f}%')
        print('=' * 100)
        print('说明: mul=score×w(重复计gap) | add=score+k×w(有限加分) | qual=w仅作资格,纯score排序')
        return

    # ===== --excel 固定窗口回测(2026-09-04用户指定: 2025-06-01~09-01, 10万本金) =====
    if '--excel' in sys.argv:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
        # 窗口参数: --excel [start_ymd] [end_ymd] [v4|a_shrink], 默认 20250601 ~ 20250901 v4
        _ai = sys.argv.index('--excel')
        _ws_, _we_ = '20250601', '20250901'
        if len(sys.argv) > _ai + 2:
            _ws_, _we_ = sys.argv[_ai + 1], sys.argv[_ai + 2]
        _sm_ = sys.argv[_ai + 3] if len(sys.argv) > _ai + 3 else 'v4'
        win_fmt = [f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in trade_dates if _ws_ <= y <= _we_]
        print(f'Excel回测窗口: {win_fmt[0]} ~ {win_fmt[-1]} ({len(win_fmt)}个交易日)')
        # 名称映射(全ths文件)
        name_map = {}
        for ymd in all_dates:
            with open(os.path.join(THS_DIR, f'{ymd}.json'), encoding='utf-8') as f:
                for s in json.load(f):
                    name_map[str(s.get('code', ''))] = s.get('name', '')
        # 温度分档动态仓位(2026-09-04拍板): <40空仓, 每10只一档仓位从40%起步, ≥100全仓
        def pos_pct(d):
            return temp_position(temp_of.get(d, 0))
        final, trades, end_pos = simulate(win_fmt, 0, pos_pct, gap_mode='smooth', band=1.0,
                                          sort_mode='mul', select_mode=_sm_)
        wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100 if trades else 0
        avg = sum(t['pnl'] for t in trades) / len(trades) if trades else 0
        edges = [t for t in trades if t.get('gap') is not None and (t['gap'] < 4 or t['gap'] > 8)]
        n_days = {'强势>=100': 0, '弱市40-99': 0, '极弱<40': 0}
        for d in win_fmt:
            n = temp_of.get(d, 0)
            if n >= 100:
                n_days['强势>=100'] += 1
            elif n >= 40:
                n_days['弱市40-99'] += 1
            else:
                n_days['极弱<40'] += 1
        results_dir = os.path.dirname(BASE)   # 桌面(2026-09-04用户要求结果放桌面)
        os.makedirs(results_dir, exist_ok=True)
        xlsx_path = os.path.join(results_dir, f'gap_smooth_backtest_{win_fmt[0].replace("-","")}_{win_fmt[-1].replace("-","")}_{_sm_}.xlsx')
        wb = Workbook()
        ws = wb.active
        ws.title = '汇总'
        head_font = Font(bold=True, color='FFFFFF')
        head_fill = PatternFill('solid', fgColor='4472C4')
        _sm_label = 'A式缩量选股(回避爆量>=2x, 缩量优先)' if _sm_ == 'a_shrink' else 'V4综合分(评分xgap权重)'
        rows = [
            [f'新规则回测汇总 ({win_fmt[0]} ~ {win_fmt[-1]}, 本金10万, 选股={_sm_label})'],
            ['买入规则', '无评分门槛 | gap平滑窗4-8%+-1%边缘带 | 过滤一字/4板+一字/300·688 | 排序: ' + _sm_label],
            ['卖出规则', '决策树定卖/留: 硬止损-10%盘中兜底 | 昨涨停低开弱转强失败卖 | 昨断板gap<4卖 | 否则留; 决定卖→开盘价成交'],
            ['仓位规则', '温度分档: <40空仓 | 每10只一档仓位从40%起步 | >=100全仓'],
            ['数据说明', '池数据全部来自同花顺真实拉取(2026-09-04补齐缺失日期); 部分日期API无炸板次数/封板时间字段走缺省档'],
            ['窗口', f'{win_fmt[0]} ~ {win_fmt[-1]}', f'{len(win_fmt)}个交易日'],
            ['温度分布', f"强势{n_days['强势>=100']}天", f"弱市{n_days['弱市40-99']}天", f"极弱{n_days['极弱<40']}天"],
            [''],
            ['指标', '数值'],
            ['期末资金', f'{final:,.0f}'],
            ['总收益%', f'{(final/INIT-1)*100:+.1f}'],
            ['交易笔数', len(trades)],
            ['胜率%', f'{wr:.1f}'],
            ['均笔%', f'{avg:+.2f}'],
            ['边缘带笔数(3-4%/8-9%)', len(edges)],
            ['期末持仓', (name_map.get(end_pos['code'], end_pos['code']) + f'@{end_pos["end_price"]:.2f}') if end_pos else '无'],
        ]
        for r in rows:
            ws.append(r)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for j in range(2, 5):
            for cell in ws[j]:
                cell.font = Font(bold=True)
        for j in (6, 7, 10):
            for cell in ws[j]:
                cell.font = Font(bold=True)
        for cell in ws[10]:
            cell.font = head_font
            cell.fill = head_fill
        for col, w in (('A', 14), ('B', 70), ('C', 14), ('D', 14), ('E', 14)):
            ws.column_dimensions[col].width = w
        # 明细sheet
        wsx = wb.create_sheet('交易明细')
        headers = ['序号', '代码', '名称', '买入日', '卖出日', '持仓天数', '连板', '评分',
                   '买入日温度(涨停数)', '温度档', '仓位%', '买入金额',
                   'gap%', 'gap权重w', '买入价', '卖出价', '盈亏%', '卖出后现金余额', '卖出原因']
        wsx.append(headers)
        for cell in wsx[1]:
            cell.font = head_font
            cell.fill = head_fill
        def _tlabel(n):
            p = temp_position(n)
            if p >= 1.0:
                return '强势'
            if p <= 0:
                return '极弱'
            return f'{int(p*100)}%仓'
        di = {d: i for i, d in enumerate(win_fmt)}
        pnl_rows = []
        for i, t in enumerate(trades, 1):
            days = di.get(t['sell_date'], 0) - di.get(t['buy_date'], 0)
            pnl_rows.append([i, t['code'], name_map.get(t['code'], ''), t['buy_date'], t['sell_date'],
                             days, t['cons'], round(t['score'], 1),
                             t.get('temp', ''), _tlabel(t.get('temp', 0)), f"{t.get('pct', 0)*100:.0f}%",
                             t.get('amount', ''),
                             round(t['gap'], 2), round(t['w'], 2),
                             round(t['buy_price'], 2), round(t['sell_price'], 2), round(t['pnl'], 2),
                             t.get('cash_after', ''), t['reason']])
        if end_pos:
            pnl_rows.append([len(pnl_rows)+1, end_pos['code'], name_map.get(end_pos['code'], ''),
                             end_pos['buy_date'], '期末', '-', end_pos['cons'], round(end_pos['score'], 1),
                             end_pos.get('temp', ''), _tlabel(end_pos.get('temp', 0)),
                             f"{end_pos.get('pct', 0)*100:.0f}%", end_pos.get('amount', ''),
                             round(end_pos['gap'], 2), round(end_pos['w'], 2), round(end_pos['buy_price'], 2),
                             round(end_pos['end_price'], 2),
                             round((end_pos['end_price']-end_pos['buy_price'])/end_pos['buy_price']*100, 2),
                             f'{final:,.0f}', '期末持有(按末日收盘估值=期末账户资金)'])
        for row in pnl_rows:
            wsx.append(row)
        red = Font(color='CC0000'); green = Font(color='006100')
        for r in range(2, len(pnl_rows) + 2):
            v = wsx.cell(row=r, column=13).value
            if isinstance(v, (int, float)):
                wsx.cell(row=r, column=13).font = red if v > 0 else (green if v < 0 else Font())
        wsx.freeze_panes = 'A2'
        for c, wd in enumerate([6, 9, 11, 12, 12, 9, 6, 7, 8, 10, 9, 9, 8, 14, 30], 1):
            wsx.column_dimensions[get_column_letter(c)].width = wd
        try:
            wb.save(xlsx_path)
        except PermissionError:
            import time
            xlsx_path = os.path.join(results_dir, f'gap_smooth_backtest_{win_fmt[0].replace("-","")}_{win_fmt[-1].replace("-","")}_{_sm_}_{time.strftime("%H%M%S")}.xlsx')
            wb.save(xlsx_path)
            print('⚠ 原文件名被占用, 已改用时间戳文件名')
        print(f'✓ Excel已生成: {xlsx_path}')
        return
    print('\n====================================================================================================')
    _wf = [f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in trade_dates]
    def _pp(d):
        return temp_position(temp_of.get(d, 0))
    print(f'score_min 门槛扫描 (窗口 {_wf[0]} ~ {_wf[-1]}, 温度分档仓位, 决策树+开盘价卖出)')
    print('=' * 100)
    for ms in (30, 40, 50, 60, 70):
        final, trades, _pos = simulate(_wf, ms, _pp, gap_mode='smooth', band=1.0, sort_mode='mul')
        wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100 if trades else 0
        avg = sum(t['pnl'] for t in trades) / len(trades) if trades else 0
        print(f'门槛{ms:>3}: 总收益{(final/INIT-1)*100:+8.1f}% | {len(trades):>3}笔 | 胜率{wr:4.1f}% | 均笔{avg:+5.2f}%')
    print('=' * 100)
    print(f'窗口 {_wf[0]} ~ {_wf[-1]} ({len(_wf)}天) | 本金{INIT:,} | 详细回测用 --excel')


if __name__ == '__main__':
    main()
