import json
import openpyxl
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import math

with open(r'C:\Users\Davis\Desktop\主升浪\stock_data.json', 'r', encoding='utf-8') as f:
    stock_data = json.load(f)

def excel_to_date(serial):
    return datetime(1899, 12, 30) + timedelta(days=int(serial))

wb = openpyxl.load_workbook(r'C:\Users\Davis\Desktop\主升浪\副本主升浪.xlsx')
ws = wb['Sheet1']
records = []
for row in ws.iter_rows(min_row=2, values_only=True):
    for i in range(0, 10, 2):
        date_val = row[i]
        stock = row[i+1] if i+1 < len(row) else None
        if date_val is not None and date_val != '' and stock is not None and stock != '':
            records.append((int(date_val), stock.strip()))
records.sort(key=lambda x: x[0])

stocks_map = {
    '赤天化':'600227','亚盛集团':'600108','国星光电':'002449','顺钠股份':'000533',
    '美利云':'000815','宇环数控':'002903','金浦钛业':'000545','郑州煤电':'600121',
    '金正大':'002470','京投发展':'600683','正泰电源':'002150','基蛋生物':'603387',
    '华电辽能':'600396','新日股份':'603787','舒华体育':'605299','新能泰山':'000720',
    '美诺华':'603538','津药药业':'600488','安徽建工':'600502','力诺药包':'301188',
    '星辉环材':'300834','中工国际':'002051','康盛股份':'002418','新朋股份':'002328',
    '圣阳股份':'002580','康恩贝':'600572','昂利康':'002940','蜀道装备':'300540',
    '圣龙股份':'603178','九鼎新材':'002201','东望时代':'600052','水发燃气':'603318',
    '飞南资源':'301500','宝光股份':'600379','金螳螂':'002081','波导股份':'600130',
    '深圳华强':'000062','大唐发电':'601991','蒙娜丽莎':'002918','滨化股份':'601678',
    '合肥城建':'002208','华能蒙电':'600863','达实智能':'002421','合百集团':'000417',
    '安德利':'605198','肯特股份':'301591','香江控股':'600162','泓淋电力':'301439',
    '方大集团':'000055','广西能源':'600310','天洋新材':'603330','龙源技术':'300105',
    '金安国纪':'002636','天地源':'600665','翔鹭钨业':'002842','金钼股份':'601958',
    '盛龙股份':'001257','立航科技':'603261','黄河旋风':'600172','世名科技':'300522',
    '长裕集团':'603407','宏柏新材':'605366','兴业科技':'002674','安洁科技':'002635',
    '雷赛智能':'002979','先锋新材':'300163','恒尚节能':'603137','同兴达':'002845',
    '立方制药':'003020','哈药股份':'600664','立新能源':'001258','长缆科技':'002879',
}

def get_limit_pct(code):
    if code.startswith('30') or code.startswith('688'):
        return 0.20
    return 0.10

def is_limit_up(close, prev_close, limit_pct):
    if prev_close is None or prev_close <= 0:
        return False
    limit_price = round(prev_close * (1 + limit_pct), 2)
    return close >= limit_price - 0.005

# Build comprehensive price DB
price_db = {}
for name, code in stocks_map.items():
    if name not in stock_data:
        continue
    price_db[name] = {}
    limit_pct = get_limit_pct(code)
    klines = stock_data[name]
    prev_close = None
    for i, k in enumerate(klines):
        date = k['day']
        o = float(k['open'])
        c = float(k['close'])
        h = float(k['high'])
        l = float(k['low'])
        v = float(k['volume'])

        entry = {
            'open': o, 'close': c, 'high': h, 'low': l, 'volume': v,
            'is_limit_up': False, 'prev_close': prev_close,
            'change_pct': 0, 'gap_open_pct': 0,
        }
        if prev_close is not None and prev_close > 0:
            entry['is_limit_up'] = is_limit_up(c, prev_close, limit_pct)
            entry['change_pct'] = (c - prev_close) / prev_close * 100
            entry['gap_open_pct'] = (o - prev_close) / prev_close * 100

        # MAs and volume
        if i >= 5:
            entry['vol_ma5'] = sum(float(klines[j]['volume']) for j in range(i-5, i)) / 5
        else:
            entry['vol_ma5'] = v
        if i >= 20:
            entry['vol_ma20'] = sum(float(klines[j]['volume']) for j in range(i-20, i)) / 20
            entry['high_20d'] = max(float(klines[j]['high']) for j in range(i-20, i))
        else:
            entry['vol_ma20'] = v
            entry['high_20d'] = h

        entry['vol_ratio5'] = v / entry['vol_ma5'] if entry['vol_ma5'] > 0 else 1
        entry['vol_ratio20'] = v / entry['vol_ma20'] if entry['vol_ma20'] > 0 else 1
        entry['is_20d_high'] = (h >= entry['high_20d'] * 0.999)

        # Seal quality
        if h > l and h > 0:
            if h > 0:
                entry['seal_quality'] = (c - l) / (h - l) if (h - l) > 0 else 1
            else:
                entry['seal_quality'] = 1

            # One-line board detection
            upper_shadow_pct = (h - max(o, c)) / (h - l) if (h - l) > 0 else 0
            body_pct = abs(c - o) / (h - l) if (h - l) > 0 else 0
            entry['is_one_line'] = (upper_shadow_pct < 0.1 and body_pct < 0.1)
        else:
            entry['seal_quality'] = 1
            entry['is_one_line'] = False

        # Consecutive limit-up count going INTO this day (how many before this one)
        cons_lu = 0
        for j in range(i-1, max(i-10, -1), -1):
            check_date = klines[j]['day']
            if check_date in price_db[name] and price_db[name][check_date]['is_limit_up']:
                cons_lu += 1
            else:
                break
        entry['cons_lu_before'] = cons_lu

        price_db[name][date] = entry
        prev_close = c

# Build timeline
timeline = []
for serial, stock in records:
    d = excel_to_date(serial)
    timeline.append((d.strftime('%Y-%m-%d'), stock))

all_trade_dates = sorted(set(d for d, _ in timeline))

# ================================================================
# CANDIDATE RANKING ENGINE
# For each date, find all T-1 limit-up stocks and score them
# ================================================================

def score_candidate(name, date, price_db, stock_data):
    """Score a stock that hit limit-up on T-1 for buying on `date`.
    Higher score = better candidate.
    """
    if name not in price_db or date not in price_db[name]:
        return -999

    klines = stock_data[name]
    date_indices = [i for i, k in enumerate(klines) if k['day'] == date]
    if not date_indices or date_indices[0] < 1:
        return -999
    idx = date_indices[0]

    # T-1 data
    prev_date = klines[idx - 1]['day']
    if prev_date not in price_db[name]:
        return -999
    t1 = price_db[name][prev_date]

    # Must be limit-up on T-1
    if not t1['is_limit_up']:
        return -999

    # T-2 data
    t2 = None
    if idx >= 2:
        t2_date = klines[idx - 2]['day']
        if t2_date in price_db[name]:
            t2 = price_db[name][t2_date]

    # Buy day data
    buy_info = price_db[name][date]

    score = 0.0

    # --- Factor 1: Volume contraction (缩量) ---
    # Lower volume ratio = better. Extremely low is best.
    vol20 = t1['vol_ratio20']
    if vol20 < 0.3:
        score += 30  # extremely contracted
    elif vol20 < 0.5:
        score += 25
    elif vol20 < 0.7:
        score += 20
    elif vol20 < 1.0:
        score += 15
    elif vol20 < 1.5:
        score += 8
    elif vol20 < 2.0:
        score += 3
    elif vol20 < 3.0:
        score += 0
    elif vol20 < 5.0:
        score -= 5
    else:
        score -= 10  # huge volume = bad

    # --- Factor 2: T-1 board strength (强板) ---
    gap_open = t1['gap_open_pct']
    if gap_open >= 9.5:
        score += 20  # nearly one-line board
    elif gap_open >= 8:
        score += 16
    elif gap_open >= 5:
        score += 12
    elif gap_open >= 3:
        score += 6
    elif gap_open >= 1:
        score += 2
    elif gap_open >= 0:
        score += 0
    else:
        score -= 10  # opened negative but still hit limit-up = weak

    # --- Factor 3: One-line board bonus ---
    if t1.get('is_one_line', False):
        score += 10

    # --- Factor 4: Consecutive boards ---
    cons_lu = t1['cons_lu_before']
    if cons_lu == 1:
        score += 8   # second board (1 before + today = 2nd)
    elif cons_lu == 2:
        score += 10  # third board
    elif cons_lu >= 3:
        score += 7   # 4th+ board still good but diminishing
    # cons_lu == 0: first board, baseline

    # --- Factor 5: Day of week ---
    dow = datetime.strptime(date, '%Y-%m-%d').weekday()
    if dow == 0:  # Monday
        score += 15
    elif dow == 4:  # Friday
        score -= 3

    # --- Factor 6: Seal quality ---
    seal = t1['seal_quality']
    if seal >= 0.98:
        score += 8
    elif seal >= 0.95:
        score += 5
    elif seal >= 0.9:
        score += 2
    elif seal < 0.8:
        score -= 8

    # --- Factor 7: Buy-day gap (positive gap from T-1 close) ---
    buy_gap = buy_info['gap_open_pct']
    if buy_gap > 8:
        score += 5
    elif buy_gap > 5:
        score += 3
    elif buy_gap > 2:
        score += 1
    elif buy_gap <= 0:
        score -= 20  # avoid negative gap

    # --- Factor 8: T-2 also limit-up (consecutive confirmation) ---
    if t2 and t2['is_limit_up']:
        score += 8

    return score


def get_top_candidates(date, price_db, stock_data, top_n=3):
    """Get top N stock candidates for a given date based on T-1 limit-up screening."""
    candidates = []

    # Find all stocks that have data for T-1
    for name in price_db:
        score = score_candidate(name, date, price_db, stock_data)
        if score > -999:
            candidates.append({
                'name': name,
                'score': score,
            })

    # Sort by score descending
    candidates.sort(key=lambda x: x['score'], reverse=True)

    # Get detailed info for top candidates
    top = []
    for c in candidates[:top_n]:
        # Get T-1 details
        klines = stock_data[c['name']]
        date_indices = [i for i, k in enumerate(klines) if k['day'] == date]
        if date_indices:
            idx = date_indices[0]
            prev_date = klines[idx - 1]['day']
            t1 = price_db[c['name']][prev_date]
            buy_info = price_db[c['name']][date]
            top.append({
                'name': c['name'],
                'score': c['score'],
                't1_vol20': t1['vol_ratio20'],
                't1_gap': t1['gap_open_pct'],
                't1_cons_lu': t1['cons_lu_before'],
                't1_seal': t1['seal_quality'],
                't1_one_line': t1.get('is_one_line', False),
                'buy_gap': buy_info['gap_open_pct'],
                'buy_open': buy_info['open'],
            })
    return top


# ================================================================
# BACKTEST SIMULATION
# ================================================================

INITIAL_CAPITAL = 300000

def simulate(selection_method, price_db, stock_data, timeline, all_trade_dates, stocks_map):
    """Simulate trading with a given stock selection method.
    selection_method: function(date, candidates) -> selected_name or None
    """
    positions = []  # {name, buy_date, buy_price, shares}
    cash = INITIAL_CAPITAL
    daily_log = []

    for date_idx, date in enumerate(all_trade_dates):
        record = dict(timeline).get(date, '休息')
        prev_date = all_trade_dates[date_idx - 1] if date_idx > 0 else None

        # STEP 0: Sell if previous day was not limit-up
        stocks_sold = []
        for pos in positions[:]:
            pos_name = pos['name']
            should_sell = True
            if prev_date and prev_date in price_db.get(pos_name, {}):
                if price_db[pos_name][prev_date]['is_limit_up']:
                    should_sell = False  # still holding

            if should_sell:
                if date in price_db.get(pos_name, {}):
                    sell_price = price_db[pos_name][date]['open']
                    proceeds = sell_price * pos['shares']
                    cash += proceeds
                    pnl = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                    stocks_sold.append({
                        'name': pos_name, 'buy_date': pos['buy_date'],
                        'buy_price': pos['buy_price'], 'sell_price': sell_price,
                        'shares': pos['shares'], 'pnl_pct': pnl
                    })
                    positions.remove(pos)

        # STEP 1: Decide whether to buy
        # We follow the trader's rhythm: buy when trader buys (record != '休息')
        stock_bought = None
        if record != '休息' and len(positions) == 0:
            # Get top candidates
            candidates = get_top_candidates(date, price_db, stock_data, top_n=10)
            selected = selection_method(date, candidates)

            if selected and selected in price_db and date in price_db[selected]:
                buy_price = price_db[selected][date]['open']
                shares = int(cash / buy_price / 100) * 100
                if shares > 0:
                    cost = shares * buy_price
                    cash -= cost
                    positions.append({
                        'name': selected, 'buy_date': date,
                        'buy_price': buy_price, 'shares': shares
                    })
                    stock_bought = {'name': selected, 'price': buy_price,
                                   'shares': shares, 'cost': cost}

        # Portfolio value
        position_value = 0
        for pos in positions:
            if date in price_db.get(pos['name'], {}):
                position_value += pos['shares'] * price_db[pos['name']][date]['close']
        total_value = cash + position_value

        daily_log.append({
            'date': date, 'held': [(p['name'], p['buy_date']) for p in positions],
            'cash': cash, 'total': total_value,
            'sold': stocks_sold, 'bought': stock_bought
        })

    return daily_log


# ================================================================
# RUN MULTIPLE MODELS
# ================================================================

out_path = r'C:\Users\Davis\Desktop\主升浪\model_backtest_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*120 + "\n")
    f.write("选股模型回测对比\n")
    f.write("="*120 + "\n\n")

    # --- Model 0: Trader's actual picks (reference) ---
    f.write("【模型0 - 交易员实际选择】(参考基准)\n")
    f.write("-"*60 + "\n")

    trader_log = simulate(
        lambda date, candidates: dict(timeline).get(date, '休息') if dict(timeline).get(date, '休息') != '休息' else None,
        price_db, stock_data, timeline, all_trade_dates, stocks_map
    )
    trader_final = trader_log[-1]['total'] if trader_log else INITIAL_CAPITAL
    trader_return = (trader_final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    f.write(f"最终资产: {trader_final:,.0f} | 收益率: {trader_return:+.1f}%\n")
    f.write(f"最终持仓: {trader_log[-1]['held']}\n")
    f.write(f"剩余现金: {trader_log[-1]['cash']:,.0f}\n\n")

    # --- Model 1: Pure scoring, pick #1 ---
    f.write("【模型1 - 纯评分模型: 选评分最高的#1候选】\n")
    f.write("-"*60 + "\n")

    def pick_best(date, candidates):
        if not candidates:
            return None
        return candidates[0]['name']

    model1_log = simulate(pick_best, price_db, stock_data, timeline, all_trade_dates, stocks_map)
    model1_final = model1_log[-1]['total'] if model1_log else INITIAL_CAPITAL
    model1_return = (model1_final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    f.write(f"最终资产: {model1_final:,.0f} | 收益率: {model1_return:+.1f}%\n")
    f.write(f"vs 交易员: {model1_final - trader_final:+,.0f}\n")
    f.write(f"最终持仓: {model1_log[-1]['held']}\n")
    f.write(f"剩余现金: {model1_log[-1]['cash']:,.0f}\n\n")

    # --- Show daily picks for model 1 ---
    f.write("模型1每日选股详情:\n")
    f.write(f"{'日期':<12} {'模型选股':<10} {'评分':>6} {'T-1量比':>7} {'T-1开盘':>7} {'连板':>4} {'结果涨跌':>8} {'交易员选':<10}\n")
    f.write("-"*85 + "\n")

    model1_wins = 0
    model1_trades = 0
    for i, log in enumerate(model1_log):
        if log['bought']:
            model1_trades += 1
            name = log['bought']['name']
            date = log['date']
            buy_price = log['bought']['price']

            # Check if it hit limit-up
            is_lu = False
            if name in price_db and date in price_db[name]:
                is_lu = price_db[name][date]['is_limit_up']
                day_change = price_db[name][date]['change_pct']
            if is_lu:
                model1_wins += 1

            # Get the score
            candidates = get_top_candidates(date, price_db, stock_data, top_n=3)
            score = candidates[0]['score'] if candidates else 0

            # Actual trader pick
            trader_pick = dict(timeline).get(date, '?')

            f.write(f"{date:<12} {name:<10} {score:>6.0f} "
                    f"{candidates[0]['t1_vol20'] if candidates else 0:>6.1f}x "
                    f"{candidates[0]['t1_gap'] if candidates else 0:>+6.1f}% "
                    f"{candidates[0]['t1_cons_lu'] if candidates else 0:>4} "
                    f"{'✓涨停' if is_lu else f'{day_change:+.1f}%':>8} "
                    f"{trader_pick:<10}\n")

    f.write(f"\n模型1胜率: {model1_wins}/{model1_trades} ({model1_wins/model1_trades*100:.0f}%)\n")

    # --- Model 2: Scoring with volume hard filter ---
    f.write("\n" + "="*120 + "\n")
    f.write("【模型2 - 评分+量能硬过滤: 排除T-1放量(>3x 20d)的候选后再选最高分】\n")
    f.write("-"*60 + "\n")

    def pick_filtered(date, candidates):
        filtered = [c for c in candidates if c['t1_vol20'] < 3.0]
        if not filtered:
            filtered = candidates  # fallback to all
        return filtered[0]['name']

    model2_log = simulate(pick_filtered, price_db, stock_data, timeline, all_trade_dates, stocks_map)
    model2_final = model2_log[-1]['total'] if model2_log else INITIAL_CAPITAL
    model2_return = (model2_final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    f.write(f"最终资产: {model2_final:,.0f} | 收益率: {model2_return:+.1f}%\n")
    f.write(f"vs 交易员: {model2_final - trader_final:+,.0f}\n\n")

    # --- Model 3: Scoring with strong board + low vol only ---
    f.write("【模型3 - 强板+缩量优先: T-1开盘>=5% + 量比<1x, 否则选最高分】\n")
    f.write("-"*60 + "\n")

    def pick_elite(date, candidates):
        elite = [c for c in candidates if c['t1_gap'] >= 5 and c['t1_vol20'] < 1.0]
        if elite:
            return elite[0]['name']
        # Fallback: just strong board
        strong = [c for c in candidates if c['t1_gap'] >= 5]
        if strong:
            return strong[0]['name']
        return candidates[0]['name'] if candidates else None

    model3_log = simulate(pick_elite, price_db, stock_data, timeline, all_trade_dates, stocks_map)
    model3_final = model3_log[-1]['total'] if model3_log else INITIAL_CAPITAL
    model3_return = (model3_final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    f.write(f"最终资产: {model3_final:,.0f} | 收益率: {model3_return:+.1f}%\n")
    f.write(f"vs 交易员: {model3_final - trader_final:+,.0f}\n\n")

    # --- Show top 3 candidates for each day ---
    f.write("\n" + "="*120 + "\n")
    f.write("每日前三候选标的详情\n")
    f.write("="*120 + "\n\n")

    for date in all_trade_dates:
        record = dict(timeline).get(date, '休息')
        if record == '休息':
            continue

        top3 = get_top_candidates(date, price_db, stock_data, top_n=3)
        trader_pick = record

        f.write(f"\n{date} | 交易员选: {trader_pick}\n")
        f.write(f"  {'排名':<6} {'标的':<10} {'评分':>6} {'量比20d':>8} {'T-1开盘':>8} {'连板数':>6} {'一字板':>6} {'封板质量':>8} {'买入价':>8}\n")
        f.write(f"  {'-'*70}\n")
        for rank, c in enumerate(top3):
            marker = " ← 交易员" if c['name'] == trader_pick else ""
            f.write(f"  #{rank+1:<5} {c['name']:<10} {c['score']:>6.0f} {c['t1_vol20']:>7.1f}x "
                    f"{c['t1_gap']:>+7.1f}% {c['t1_cons_lu']:>6} "
                    f"{'是' if c['t1_one_line'] else '否':>6} {c['t1_seal']:>7.3f} "
                    f"{c['buy_open']:>8.2f}{marker}\n")

    # --- Summary comparison ---
    f.write("\n" + "="*120 + "\n")
    f.write("模型对比总结\n")
    f.write("="*120 + "\n\n")
    f.write(f"{'模型':<30} {'最终资产':>12} {'收益率':>10} {'vs交易员':>12}\n")
    f.write("-"*68 + "\n")
    f.write(f"{'交易员实际':<30} {trader_final:>12,.0f} {trader_return:>+9.1f}% {'--':>12}\n")
    for name, final in [('模型1-纯评分', model1_final), ('模型2-量能过滤', model2_final), ('模型3-强板缩量', model3_final)]:
        ret = (final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        vs = final - trader_final
        f.write(f"{name:<30} {final:>12,.0f} {ret:>+9.1f}% {vs:>+12,.0f}\n")

print(f"Backtest complete! Output: {out_path}")
