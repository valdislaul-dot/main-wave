"""
v2.2 回测 — 第5版同款: 原始compute_v2_score + Excel执行模型
"""
import json, os, sys
from datetime import datetime, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'daily'))
from screen_candidates import compute_v2_score, is_limit_up, get_lp, load_kline

START_DATE = '2026-03-03'
END_DATE = '2026-08-03'
INITIAL_CASH = 200_000


def load_db():
    with open(os.path.join(BASE, 'data', 'stock_db.json')) as f:
        db = json.load(f)
    for code in db:
        db[code].sort(key=lambda x: x['date'])
        for k in db[code]:
            for fld in ['open', 'close', 'high', 'low', 'volume']:
                if fld in k: k[fld] = float(k[fld])

    # 补充每日收盘快照 (7/28-7/31)
    daily_dir = os.path.join(BASE, 'data', 'daily_close')
    for ds in ['2026-07-28', '2026-07-29', '2026-07-30', '2026-07-31']:
        fp = os.path.join(daily_dir, ds, 'daily_data.json')
        if os.path.exists(fp):
            with open(fp) as f:
                snap = json.load(f)
            for code in snap:
                if code in db:
                    bar = {'date': ds}
                    for fld in ['open', 'close', 'high', 'low', 'volume']:
                        bar[fld] = float(snap[code].get(fld, 0))
                    if not any(b['date'] == ds for b in db[code]):
                        db[code].append(bar)

    for code in db:
        db[code].sort(key=lambda x: x['date'])

    return {c: b for c, b in db.items()
            if not str(c).startswith(('300', '301', '688'))}


def run(db, start, end):
    """v2.2 + 质量过滤 + 分数区间: T-1涨停评分 → T日开盘买+卖 → 每日重复"""
    cash = INITIAL_CASH
    position = None
    trades = []

    # 预建涨停历史索引
    lu_dates = defaultdict(list)
    for code, bars in db.items():
        for i in range(1, len(bars)):
            k = bars[i]; p = bars[i-1]
            if is_limit_up(float(k['close']), float(p['close']), get_lp(code)):
                lu_dates[code].append(k['date'])

    def lu_count_40d(code, ref_date):
        cutoff = (datetime.strptime(ref_date, '%Y-%m-%d') - timedelta(days=40)).strftime('%Y-%m-%d')
        return sum(1 for d in lu_dates.get(code, []) if cutoff <= d <= ref_date)

    all_dates = set()
    for code in db:
        for k in db[code]:
            all_dates.add(k['date'])
    trading_days = sorted(d for d in all_dates if start <= d <= end)

    print(f'[BT] {len(trading_days)} days | {len(db)} stocks')

    for di, today in enumerate(trading_days):
        prev_day = trading_days[di - 1] if di > 0 else None
        if prev_day is None: continue

        # === T-1涨停股扫描 ===
        lu_stocks = []
        for code, bars in db.items():
            prev_idx = next((i for i, b in enumerate(bars) if b['date'] == prev_day), None)
            if prev_idx is None or prev_idx < 1: continue
            k = bars[prev_idx]; p = bars[prev_idx - 1]
            if is_limit_up(float(k['close']), float(p['close']), get_lp(code)):
                lu_stocks.append((code, prev_idx))

        # === 评分 + 质量过滤 ===
        candidates = []
        for code, prev_idx in lu_stocks:
            # 质量过滤: 近120日涨停≥5次
            if lu_count_40d(code, prev_day) < 3:
                continue
            sliced = db[code][:prev_idx + 1]
            result = compute_v2_score(code, sliced)
            if result is None or result[0] is None: continue
            score, det = result
            if det['true_one_line']: continue
            # 3年数据: -10~30分胜率最高, ≥30分陷阱
            if score < -10 or score >= 30: continue
            candidates.append({
                'code': code, 'score': score, 'vr': det['vr20'],
                'close': det['close'], 'one_line': det['one_line'],
                'cons': det['cons'],
            })

        # 候选太少 → 市场清淡, 不交易
        if len(candidates) < 5:
            if position:
                pc = position['code']
                if pc in db:
                    pbars = db[pc]
                    pidx = next((i for i,b in enumerate(pbars) if b['date']==today), None)
                    if pidx is not None:
                        pb = pbars[pidx]
                        sp = 0.7*(float(pb['high'])+float(pb['open']))/2 + 0.3*float(pb['close'])
                        if sp>0:
                            pnl = (sp-position['buy_price'])*position['shares']
                            pnl_pct = round((sp-position['buy_price'])/position['buy_price']*100,1)
                            cash += sp*position['shares']
                            trades.append({
                                'name':position['name'],'code':pc,
                                'buy_date':position['buy_date'],'buy_price':position['buy_price'],
                                'sell_date':today,'sell_price':sp,
                                'shares':position['shares'],'pnl':pnl,'pnl_pct':pnl_pct})
                position = None
            continue

        # === Top3评分→量比最小 ===
        candidates.sort(key=lambda x: x['score'], reverse=True)
        non_ol = [c for c in candidates if not c['one_line']]
        pool = non_ol if len(non_ol) >= 3 else candidates
        top3 = sorted(pool, key=lambda x: x['score'], reverse=True)[:min(3, len(pool))]
        best = min(top3, key=lambda x: x['vr'])

        # === T日开盘买入 ===
        if best['code'] not in db: continue
        tbars = db[best['code']]
        bidx = next((i for i, b in enumerate(tbars) if b['date'] == today), None)
        if bidx is None: continue
        buy_price = tbars[bidx]['open']
        if buy_price <= 0: continue

        # === 卖出昨日 (每日换股, 同股持有) ===
        if position and position['code'] != best['code']:
            pc = position['code']
            if pc in db:
                pbars = db[pc]
                pidx = next((i for i, b in enumerate(pbars) if b['date'] == today), None)
                if pidx is not None:
                    pb = pbars[pidx]
                    sp = 0.7 * (float(pb['high']) + float(pb['open'])) / 2 + 0.3 * float(pb['close'])
                    if sp > 0:
                        pnl = (sp - position['buy_price']) * position['shares']
                        pnl_pct = round((sp - position['buy_price']) / position['buy_price'] * 100, 1)
                        cash += sp * position['shares']
                        trades.append({
                            'name': position['name'], 'code': pc,
                            'buy_date': position['buy_date'], 'buy_price': position['buy_price'],
                            'sell_date': today, 'sell_price': sp,
                            'shares': position['shares'], 'pnl': pnl, 'pnl_pct': pnl_pct,
                        })
            position = None

        # === 买入 ===
        if position is None and cash > 0:
            shares = int(cash / buy_price / 100) * 100
            if shares > 0:
                cash -= shares * buy_price
                position = {
                    'code': best['code'], 'name': best['code'],
                    'buy_price': buy_price, 'shares': shares, 'buy_date': today,
                }

    fp = 0
    if position and position['code'] in db:
        fp = db[position['code']][-1]['close'] * position['shares']
    return trades, cash + fp


def report(name, trades, final):
    ret = (final - INITIAL_CASH) / INITIAL_CASH * 100
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0

    print(f'\n{"="*60}')
    print(f'  [{name}]')
    print(f'{"="*60}')
    print(f'  最终: {final:,.0f} ({ret:+.1f}%) | {len(trades)}笔 | 胜率{wr:.0f}%')
    if wins:
        print(f'  盈利: 平均{sum(t["pnl"] for t in wins)/len(wins):+,.0f} 最大{max(t["pnl"] for t in wins):+,.0f}')
    if losses:
        print(f'  亏损: 平均{sum(t["pnl"] for t in losses)/len(losses):+,.0f} 最大{min(t["pnl"] for t in trades):+,.0f}')
    monthly = defaultdict(float)
    for t in trades: monthly[t['buy_date'][:7]] += t['pnl']
    print('  月度: ' + ' | '.join(f'{m[5:]}:{monthly[m]:+,.0f}' for m in sorted(monthly)))
    if trades:
        holds = [(datetime.strptime(t['sell_date'], '%Y-%m-%d') -
                  datetime.strptime(t['buy_date'], '%Y-%m-%d')).days for t in trades]
        print(f'  持有: 平均{sum(holds)/len(holds):.1f}天')
    for t in trades[-10:]:
        bd = t['buy_date']; cd = t['code']; bp = t['buy_price']
        sp = t['sell_price']; pp = t['pnl_pct']
        hd = (datetime.strptime(t['sell_date'], '%Y-%m-%d') -
              datetime.strptime(bd, '%Y-%m-%d')).days
        print(f'    {bd}(+{hd}d) {cd} {bp:.2f}->{sp:.2f} {pp:+.1f}%')


if __name__ == '__main__':
    print(f'{"="*60}')
    print(f'  原始v2.2评分 · Excel执行模型 | {START_DATE} ~ {END_DATE}')
    print(f'{"="*60}')
    db = load_db()
    trades, final = run(db, START_DATE, END_DATE)
    report('v2.2原始+Excel执行', trades, final)
