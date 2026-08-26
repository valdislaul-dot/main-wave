"""四象限回测 (2026-08-25, 用户定稿口径)
口径:
  买入: T日开盘价(含佣金万2.5+滑点0.1%), 评分Top1优先买不进(一字/无K线/竞价窗口外)依次向下
  卖出: 引擎决策卖出时以开盘价成交(含成本); 昨涨停低开卖/断板gap<4%卖/硬止损-10%/昨涨停高开持有
  仓位: 弱市象限半仓 | 强市象限全仓 (区间级判断: 日均涨停<70=弱市半仓, ≥70=强市全仓)
矩阵: 强市短期(5月) / 强市长期(12月) / 弱市短期(5月) / 弱市长期(12月)
锚: 全市场竞价4-8%无差别买入基线(同区间同口径)
评分: 当前scoring_config的V3全因子(同花顺历史池还原details)
"""
import json, os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import compute_score, load_config, sector_resonance_count, is_limit_up

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
INIT = 200000
COST = 0.001 + 0.00025   # 滑点0.1% + 佣金万2.5


def load_klines(code):
    for enc in ('utf-8', 'gbk'):
        try:
            with open(os.path.join(KLINE_DIR, f'{code}.json'), encoding=enc) as f:
                raw = json.load(f)
            return raw.get('data', raw) if isinstance(raw, dict) else raw
        except Exception:
            continue
    return None


def load_ths_pool(date_ymd):
    p = os.path.join(THS_DIR, f'{date_ymd}.json')
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def ts_to_hhmm(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%H%M')
    except Exception:
        return None


def is_lu_row(k, pk):
    if k.get('pct_change') is not None:
        return k['pct_change'] >= 9.8
    return pk and pk['close'] > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098


def main():
    cfg = load_config()
    ths_dates = sorted(fn.replace('.json', '') for fn in os.listdir(THS_DIR) if fn.endswith('.json'))
    print(f'同花顺池覆盖: {len(ths_dates)}天 ({ths_dates[0]} ~ {ths_dates[-1]})')

    # 每日涨停数(区间切分用)
    zt_counts = {}
    for ymd in ths_dates:
        info = load_ths_pool(ymd)
        if info:
            zt_counts[ymd] = sum(1 for s in info
                                 if not str(s.get('code', '')).startswith(('300', '301', '688', '8', '9')))

    # 月度日均涨停数
    month_avg = {}
    for ymd, n in zt_counts.items():
        m = ymd[:6]
        month_avg.setdefault(m, []).append(n)
    for m in month_avg:
        month_avg[m] = sum(month_avg[m]) / len(month_avg[m])
    months = sorted(month_avg)
    print('月度日均涨停数:')
    print('  ' + ' '.join(f'{m[2:6]}:{month_avg[m]:.0f}' for m in months))

    def find_segment(months_len, mode):
        """滑动窗口(按月)找日均涨停最高/最低的连续月段"""
        best = None
        best_avg = -1 if mode == 'strong' else 999
        for i in range(len(months) - months_len + 1):
            seg = months[i:i + months_len]
            avg = sum(month_avg[m] for m in seg) / months_len
            if mode == 'strong' and avg > best_avg:
                best_avg, best = avg, seg
            if mode == 'weak' and avg < best_avg:
                best_avg, best = avg, seg
        return best, best_avg

    segments = {}
    for label, ml, mode in (('强市短期', 5, 'strong'), ('强市长期', 12, 'strong'),
                            ('弱市短期', 5, 'weak'), ('弱市长期', 12, 'weak')):
        seg, avg = find_segment(ml, mode)
        if seg:
            start_ymd = seg[0] + '01'
            end_m = seg[-1]
            # 段末月最后一天
            end_ymd = max(ymd for ymd in ths_dates if ymd[:6] == end_m)
            segments[label] = (start_ymd, end_ymd, avg)
            print(f'{label}: {seg[0]}~{seg[-1]} 日均涨停{avg:.0f}只 ({start_ymd}~{end_ymd})')

    # 评分缓存: {ymd: {code: (score, cons, one_line)}}
    score_cache = {}
    for ymd in ths_dates:
        info = load_ths_pool(ymd)
        if not info:
            continue
        date_fmt = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
        industries = [s.get('reason_type', '') for s in info
                      if not str(s.get('code', '')).startswith(('300', '301', '688', '8', '9'))]
        day_map = {}
        for s in info:
            code = str(s.get('code', ''))
            if not code or code.startswith(('300', '301', '688', '8', '9')):
                continue
            kls = load_klines(code)
            if not kls:
                continue
            idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date_fmt), None)
            if idx is None or idx < 25:
                continue
            sub = kls[:idx + 1]
            details = {
                'seal_time': ts_to_hhmm(s.get('first_limit_up_time')) or '1459',
                'final_seal_time': ts_to_hhmm(s.get('last_limit_up_time')) or '1459',
                'zhaban': int(s.get('open_num', 0) or 0),
                'sector_count': sector_resonance_count(s.get('reason_type', ''), industries),
                'industry': s.get('reason_type', ''),
                'turnover': float(s.get('turnover_rate', 0) or 0),
            }
            score, det = compute_score(code, sub, details, 'v3', cfg)
            if score is None:
                continue
            k = sub[-1]
            true_ol = (abs(k['high'] - k['low']) < 0.001 and abs(k['close'] - k['high']) < 0.001)
            day_map[code] = {'score': score, 'one_line': true_ol,
                             'cons': (det or {}).get('cons', 1)}
        score_cache[date_fmt] = day_map
    print(f'评分缓存: {len(score_cache)}天')

    def run_segment(start_ymd, end_ymd, pos_pct):
        """pos_pct: 0.5半仓 / 1.0全仓 — 单段回测"""
        dates = [f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in ths_dates
                 if start_ymd <= y <= end_ymd]
        cash = INIT
        pos = None   # {code, name, buy_date, buy_price, shares}
        trades = []
        for i, d in enumerate(dates):
            # 卖出决策(持仓中, 每交易日)
            if pos is not None and i > 0:
                prev_d = dates[i - 1]
                kls = load_klines(pos['code'])
                if kls:
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    if idx1 is not None and idx0 is not None:
                        k1, k0 = kls[idx1], kls[idx0]
                        yest_lu = is_lu_row(k1, kls[idx1 - 1] if idx1 > 0 else None)
                        today_lu = is_lu_row(k0, kls[idx0 - 1] if idx0 > 0 else None)
                        gap = (k0['open'] - k1['close']) / k1['close'] * 100
                        loss = (k0['open'] - pos['buy_price']) / pos['buy_price'] * 100
                        if loss <= -10:
                            action, reason = 'sell', '硬止损'
                        elif yest_lu and gap < 0:
                            action, reason = 'sell', '昨涨停低开卖'
                        elif yest_lu and today_lu:
                            action, reason = 'hold', '涨停持有'
                        elif yest_lu:
                            action, reason = 'sell', '昨涨停今断板卖'
                        elif gap >= 4:
                            action, reason = 'hold', '断板gap≥4%持有'
                        else:
                            action, reason = 'sell', '断板gap<4%卖'
                        if action == 'sell':
                            sell_price = k0['open'] * (1 - COST)
                            pnl = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                            cash += pos['shares'] * sell_price
                            trades.append({'buy': pos['buy_date'], 'sell': d, 'name': pos['name'],
                                           'pnl': round(pnl, 2), 'reason': reason})
                            pos = None
            # 买入: 昨日评分Top1依次向下(竞价4-8%且可成交)
            if pos is None and i > 0:
                prev_d = dates[i - 1]
                cands = sorted(score_cache.get(prev_d, {}).items(), key=lambda x: -x[1]['score'])
                for code, meta in cands:
                    if meta['score'] < 10:
                        break
                    if meta['one_line'] or meta['cons'] >= 4:
                        continue
                    kls = load_klines(code)
                    if not kls:
                        continue
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    if idx0 is None or idx1 is None:
                        continue
                    gap = (kls[idx0]['open'] - kls[idx1]['close']) / kls[idx1]['close'] * 100
                    if not (4.0 <= gap <= 8.0):
                        continue
                    price = kls[idx0]['open'] * (1 + COST)
                    budget = (cash + (pos['shares'] * kls[idx0]['open'] if pos else 0)) * pos_pct
                    shares = int(min(cash, budget) / price / 100) * 100
                    if shares <= 0:
                        continue
                    cash -= shares * price
                    pos = {'code': code, 'name': '', 'buy_date': d,
                           'buy_price': price, 'shares': shares}
                    break
        final = cash
        if pos:
            kls = load_klines(pos['code'])
            if kls:
                final += pos['shares'] * kls[-1]['close'] * (1 - COST)
        wins = [t for t in trades if t['pnl'] > 0]
        return final, trades, wins

    out = []
    out.append('=' * 78)
    out.append('四象限回测 — 当前V3评分(用户定稿口径: 开盘价进出/Top1依次向下/弱半强全仓)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 初始 {INIT:,} | 成本{COST*100:.2f}%单边')
    out.append('=' * 78)
    for label in ('强市短期', '强市长期', '弱市短期', '弱市长期'):
        if label not in segments:
            continue
        start_ymd, end_ymd, avg = segments[label]
        pos_pct = 1.0 if '强市' in label else 0.5
        final, trades, wins = run_segment(start_ymd, end_ymd, pos_pct)
        ret = (final / INIT - 1) * 100
        n = len(trades)
        out.append(f'\n【{label}】{start_ymd}~{end_ymd} (日均涨停{avg:.0f}只, {"全仓" if pos_pct == 1 else "半仓"})')
        out.append(f'  最终资产 {final:,.0f} | 收益 {ret:+.1f}% | {n}笔 | 胜率 {len(wins)/n*100 if n else 0:.0f}% | '
                   f'均盈亏 {sum(t["pnl"] for t in trades)/n if n else 0:+.2f}%')
        for t in trades:
            out.append(f'    {t["buy"]}→{t["sell"]} {t["name"]}({t["code"] if "code" in t else ""}) '
                       f'{t["pnl"]:+.1f}% [{t["reason"]}]')
    with open(os.path.join(BASE, 'logs', 'backtest_4quadrant.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out[:60]))
    print('\nDone: logs/backtest_4quadrant.txt')


if __name__ == '__main__':
    main()
