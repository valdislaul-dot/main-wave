"""当前实盘模型回测 (2026-08-25) — 用当前V3评分全因子回测3-7月经典区间
评分: scoring.compute_score v3 (含封板时间/炸板/拆词共振/分歧因子 — 同花顺历史池还原details)
规则: 真一字跳过 + 4板+一字过滤 + 评分≥10 → D+1竞价4-8%开盘买入Top3
卖出: V4.1简化 — 昨涨停:低开卖/高开持有收盘卖 | 昨断板:gap≥4%持有/gap<4%卖 | 硬止损-10%
区间: 2026-03-04 ~ 2026-07-24 (与经典回测v2.1/v2.2对齐)
对照: V2.1 +743~966% / v2.2 +1171% / A实盘 +411%
"""
import json, os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import compute_score, load_config, sector_resonance_count, is_limit_up

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
START, END = '2026-03-04', '2026-07-24'
INIT = 200000


def load_klines(code):
    for enc in ('utf-8', 'gbk'):
        try:
            p = os.path.join(KLINE_DIR, f'{code}.json')
            with open(p, encoding=enc) as f:
                raw = json.load(f)
            kls = raw.get('data', raw) if isinstance(raw, dict) else raw
            return kls
        except Exception:
            continue
    return None


def load_ths_pool(date_ymd):
    p = os.path.join(THS_DIR, f'{date_ymd}.json')
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            info = json.load(f)
        return info
    except Exception:
        return None


def ts_to_hhmm(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%H%M')
    except Exception:
        return None


def main():
    cfg = load_config()
    # 交易日历(从同花顺池文件推)
    all_dates = sorted(fn.replace('.json', '') for fn in os.listdir(THS_DIR)
                       if fn.endswith('.json') and START.replace('-', '') <= fn.replace('.json', '') <= END.replace('-', ''))
    print(f'回测区间: {START} ~ {END} | 交易日: {len(all_dates)} | 初始: {INIT:,}')

    # 每日评分存档: {date: [{code, name, score, cons, one_line, true_ol}]}
    daily_scores = {}
    for ymd in all_dates:
        info = load_ths_pool(ymd)
        if not info:
            continue
        date_fmt = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
        stocks = []
        industries = [s.get('reason_type', '') for s in info
                      if not str(s.get('code', '')).startswith(('300', '301', '688', '8', '9'))]
        for s in info:
            code = str(s.get('code', ''))
            if not code or code.startswith(('300', '301', '688', '8', '9')):
                continue
            kls = load_klines(code)
            if not kls:
                continue
            # K线切片到当日
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
            # 一字判定
            true_ol = (abs(k['high'] - k['low']) < 0.001 and abs(k['close'] - k['high']) < 0.001)
            stocks.append({'code': code, 'name': s.get('name', ''), 'score': score,
                           'cons': det.get('cons', 1) if det else 1,
                           'one_line': true_ol})
        stocks.sort(key=lambda x: -x['score'])
        daily_scores[date_fmt] = stocks
    print(f'评分存档: {len(daily_scores)} 天')

    # 模拟交易(修正版2): 涨停持有跨日(v2.2口径) — 昨涨停:低开卖/高开持有,收盘涨停继续持有
    # 昨断板: gap≥4%持有收盘卖/gap<4%开盘卖; 收盘浮亏≤-10%止损
    def run_sim(pick_mode):
        cash = INIT
        position = None
        trades = []
        dates_fmt = sorted(daily_scores.keys())
        for i, d in enumerate(dates_fmt):
            # 持仓卖出决策(每天)
            if position and i > 0:
                prev_d = dates_fmt[i - 1]
                kls = load_klines(position['code'])
                if kls:
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    if idx1 is not None and idx0 is not None:
                        k1, k0 = kls[idx1], kls[idx0]
                        open_pct = (k0['open'] - k1['close']) / k1['close'] * 100
                        yest_lu = (k1.get('pct_change') or 0) >= 9.8 or (
                            idx1 > 0 and (k1['close'] - kls[idx1 - 1]['close']) / kls[idx1 - 1]['close'] >= 0.098)
                        today_lu = (k0.get('pct_change') or 0) >= 9.8 or (
                            idx0 > 0 and (k0['close'] - kls[idx0 - 1]['close']) / kls[idx0 - 1]['close'] >= 0.098)
                        close_loss = (k0['close'] - position['buy_price']) / position['buy_price'] * 100
                        if close_loss <= -10:
                            sell_price, reason = k0['close'], '硬止损'
                        elif yest_lu and open_pct < 0:
                            sell_price, reason = k0['open'], '昨涨停低开卖'
                        elif yest_lu and today_lu:
                            # 今日再涨停 → 继续持有(让利润奔跑)
                            continue
                        elif yest_lu:
                            sell_price, reason = k0['close'], '昨涨停今断板收盘卖'
                        elif open_pct >= 4:
                            sell_price, reason = k0['close'], '断板gap≥4%持有收盘卖'
                        else:
                            sell_price, reason = k0['open'], '断板gap<4%开盘卖'
                        pnl = (sell_price - position['buy_price']) / position['buy_price'] * 100
                        cash += position['shares'] * sell_price
                        trades.append({'buy': position['buy_date'], 'sell': d, 'name': position['name'],
                                       'code': position['code'], 'pnl': round(pnl, 2), 'reason': reason})
                        position = None
            # 买入
            if position is None and i > 0:
                prev_d = dates_fmt[i - 1]
                cands = [c for c in daily_scores.get(prev_d, [])
                         if c['score'] >= 10 and not c['one_line'] and c['cons'] < 4]
                if pick_mode == 'top1':
                    pool = cands[:1]
                else:   # top3_lowest_vr: v2.1验证口径
                    top3 = cands[:3]
                    vr_map = {}
                    for c in top3:
                        kls = load_klines(c['code'])
                        if not kls:
                            continue
                        idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                        idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                        if idx0 is None or idx1 is None:
                            continue
                        vols = [x.get('volume', 0) for x in kls[max(0, idx0 - 20):idx0] if isinstance(x, dict)]
                        vol = kls[idx0].get('volume', 0)
                        vr = vol / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 99
                        vr_map[c['code']] = vr
                    if vr_map:
                        pool = [min(top3, key=lambda c: vr_map.get(c['code'], 99))]
                    else:
                        pool = []
                for c in pool:
                    kls = load_klines(c['code'])
                    if not kls:
                        continue
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    if idx0 is None or idx1 is None:
                        continue
                    gap = (kls[idx0]['open'] - kls[idx1]['close']) / kls[idx1]['close'] * 100
                    if 4.0 <= gap <= 8.0:
                        price = kls[idx0]['open']
                        shares = int(cash / price / 100) * 100
                        if shares <= 0:
                            continue
                        cash -= shares * price
                        position = {'code': c['code'], 'name': c['name'],
                                    'buy_date': d, 'buy_price': price, 'shares': shares}
                        break
        final = cash
        if position:
            kls = load_klines(position['code'])
            if kls:
                final += position['shares'] * kls[-1]['close']
        return final, trades

    results = {}
    for mode, label in (('top1', 'Top1评分最高(当前实盘口径)'), ('top3_lowest_vr', 'Top3最低量比(v2.1验证口径)')):
        final, trades = run_sim(mode)
        wins = [t for t in trades if t['pnl'] > 0]
        results[mode] = (final, trades, wins)
        out = []
        out.append('=' * 72)
        out.append(f'当前V3评分回测: {START} ~ {END} | {label}')
        out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 初始 {INIT:,}')
        out.append('=' * 72)
        out.append(f'最终资产: {final:,.0f} | 收益率: {(final/INIT-1)*100:+.1f}%')
        out.append(f'笔数: {len(trades)} | 胜率: {len(wins)/len(trades)*100 if trades else 0:.0f}% | '
                   f'均盈亏: {sum(t["pnl"] for t in trades)/len(trades) if trades else 0:+.2f}%')
        out.append(f'对照: V2.1 +743~966% / v2.2 +1171% / A实盘 +411% (同区间)')
        for t in trades:
            out.append(f'  {t["buy"]}→{t["sell"]} {t["name"]}({t["code"]}) {t["pnl"]:+.1f}% [{t["reason"]}]')
        with open(os.path.join(BASE, 'logs', f'backtest_current_model_{mode}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(out))
        print('\n'.join(out[:12]))
        print()

    # 统计已在run_sim内输出
    print()
    print('Done: 结果已写入 logs/backtest_current_model_top1.txt 与 top3_lowest_vr.txt')


if __name__ == '__main__':
    main()
