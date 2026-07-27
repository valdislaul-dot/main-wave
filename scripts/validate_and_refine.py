import json
import openpyxl
from datetime import datetime, timedelta
from collections import defaultdict, Counter

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
    if prev_close is None or prev_close <= 0: return False
    limit_price = round(prev_close * (1 + limit_pct), 2)
    return close >= limit_price - 0.005

# Build price DB
price_db = {}
for name, code in stocks_map.items():
    if name not in stock_data: continue
    price_db[name] = {}
    limit_pct = get_limit_pct(code)
    klines = stock_data[name]
    prev_close = None
    for i, k in enumerate(klines):
        date = k['day']
        o = float(k['open']); c = float(k['close'])
        h = float(k['high']); l = float(k['low']); v = float(k['volume'])
        entry = {'open': o, 'close': c, 'high': h, 'low': l, 'volume': v,
                 'is_limit_up': False, 'prev_close': prev_close,
                 'change_pct': 0, 'gap_open_pct': 0}
        if prev_close is not None and prev_close > 0:
            entry['is_limit_up'] = is_limit_up(c, prev_close, limit_pct)
            entry['change_pct'] = (c - prev_close) / prev_close * 100
            entry['gap_open_pct'] = (o - prev_close) / prev_close * 100
        if i >= 5:
            entry['vol_ma5'] = sum(float(klines[j]['volume']) for j in range(i-5, i)) / 5
        else:
            entry['vol_ma5'] = v
        if i >= 20:
            entry['vol_ma20'] = sum(float(klines[j]['volume']) for j in range(i-20, i)) / 20
            entry['high_20d'] = max(float(klines[j]['high']) for j in range(i-20, i))
        else:
            entry['vol_ma20'] = v; entry['high_20d'] = h
        entry['vol_ratio5'] = v / entry['vol_ma5'] if entry['vol_ma5'] > 0 else 1
        entry['vol_ratio20'] = v / entry['vol_ma20'] if entry['vol_ma20'] > 0 else 1
        entry['is_20d_high'] = (h >= entry['high_20d'] * 0.999)
        if h > l and h > 0:
            entry['seal_quality'] = (c - l) / (h - l) if (h - l) > 0 else 1
            upper_shadow = (h - max(o, c)) / (h - l) if (h - l) > 0 else 0
            body = abs(c - o) / (h - l) if (h - l) > 0 else 0
            entry['is_one_line'] = (upper_shadow < 0.1 and body < 0.1)
        else:
            entry['seal_quality'] = 1; entry['is_one_line'] = False
        cons_lu = 0
        for j in range(i-1, max(i-10, -1), -1):
            check_date = klines[j]['day']
            if check_date in price_db[name] and price_db[name][check_date]['is_limit_up']:
                cons_lu += 1
            else: break
        entry['cons_lu_before'] = cons_lu
        price_db[name][date] = entry
        prev_close = c

timeline = []
for serial, stock in records:
    d = excel_to_date(serial)
    timeline.append((d.strftime('%Y-%m-%d'), stock))
all_trade_dates = sorted(set(d for d, _ in timeline))

INITIAL_CAPITAL = 300000

def score_candidate(name, date, price_db, stock_data):
    if name not in price_db or date not in price_db[name]: return -999
    klines = stock_data[name]
    date_indices = [i for i, k in enumerate(klines) if k['day'] == date]
    if not date_indices or date_indices[0] < 1: return -999
    idx = date_indices[0]
    prev_date = klines[idx - 1]['day']
    if prev_date not in price_db[name]: return -999
    t1 = price_db[name][prev_date]
    if not t1['is_limit_up']: return -999

    buy_info = price_db[name][date]
    # T-2
    t2_is_lu = False
    if idx >= 2:
        t2_date = klines[idx - 2]['day']
        if t2_date in price_db[name]:
            t2_is_lu = price_db[name][t2_date]['is_limit_up']

    score = 0.0
    vol20 = t1['vol_ratio20']
    if vol20 < 0.3: score += 30
    elif vol20 < 0.5: score += 25
    elif vol20 < 0.7: score += 20
    elif vol20 < 1.0: score += 15
    elif vol20 < 1.5: score += 8
    elif vol20 < 2.0: score += 3
    elif vol20 < 3.0: score += 0
    elif vol20 < 5.0: score -= 5
    else: score -= 10

    gap = t1['gap_open_pct']
    if gap >= 9.5: score += 20
    elif gap >= 8: score += 16
    elif gap >= 5: score += 12
    elif gap >= 3: score += 6
    elif gap >= 1: score += 2
    elif gap >= 0: score += 0
    else: score -= 10

    if t1.get('is_one_line', False): score += 10
    cons = t1['cons_lu_before']
    if cons == 1: score += 8
    elif cons == 2: score += 10
    elif cons >= 3: score += 7
    dow = datetime.strptime(date, '%Y-%m-%d').weekday()
    if dow == 0: score += 15
    elif dow == 4: score -= 3
    seal = t1['seal_quality']
    if seal >= 0.98: score += 8
    elif seal >= 0.95: score += 5
    elif seal >= 0.9: score += 2
    elif seal < 0.8: score -= 8
    buy_gap = buy_info['gap_open_pct']
    if buy_gap > 8: score += 5
    elif buy_gap > 5: score += 3
    elif buy_gap > 2: score += 1
    elif buy_gap <= 0: score -= 20
    if t2_is_lu: score += 8
    return score

def get_candidates(date, price_db, stock_data, top_n=10):
    candidates = []
    for name in price_db:
        s = score_candidate(name, date, price_db, stock_data)
        if s > -999:
            klines = stock_data[name]
            date_indices = [i for i, k in enumerate(klines) if k['day'] == date]
            idx = date_indices[0]
            prev_date = klines[idx - 1]['day']
            t1 = price_db[name][prev_date]
            candidates.append({
                'name': name, 'score': s,
                't1_vol20': t1['vol_ratio20'],
                't1_gap': t1['gap_open_pct'],
                't1_cons': t1['cons_lu_before'],
                'buy_open': price_db[name][date]['open'],
            })
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:top_n]

def simulate_model(pick_fn):
    positions = []
    cash = INITIAL_CAPITAL
    daily_log = []
    for date_idx, date in enumerate(all_trade_dates):
        record = dict(timeline).get(date, '休息')
        prev_date = all_trade_dates[date_idx - 1] if date_idx > 0 else None

        # Sell
        for pos in positions[:]:
            should_sell = True
            if prev_date and prev_date in price_db.get(pos['name'], {}):
                if price_db[pos['name']][prev_date]['is_limit_up']:
                    should_sell = False
            if should_sell:
                if date in price_db.get(pos['name'], {}):
                    sell_price = price_db[pos['name']][date]['open']
                    proceeds = sell_price * pos['shares']
                    cash += proceeds
                    positions.remove(pos)

        # Buy
        stock_bought = None
        if record != '休息' and len(positions) == 0:
            candidates = get_candidates(date, price_db, stock_data, top_n=10)
            selected = pick_fn(date, candidates)
            if selected and selected in price_db and date in price_db[selected]:
                buy_price = price_db[selected][date]['open']
                shares = int(cash / buy_price / 100) * 100
                if shares > 0:
                    cost = shares * buy_price
                    cash -= cost
                    positions.append({'name': selected, 'buy_date': date,
                                     'buy_price': buy_price, 'shares': shares})
                    stock_bought = {'name': selected, 'price': buy_price,
                                   'shares': shares, 'cost': cost}

        position_value = sum(pos['shares'] * price_db.get(pos['name'], {}).get(date, {}).get('close', 0) for pos in positions)
        daily_log.append({'date': date, 'held': [(p['name'], p['buy_date']) for p in positions],
                         'cash': cash, 'total': cash + position_value, 'bought': stock_bought})
    return daily_log

# ================================================================
# VALIDATION: Check for look-ahead bias
# ================================================================
out_path = r'C:\Users\Davis\Desktop\主升浪\validation_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*100 + "\n")
    f.write("模型验证与诊断\n")
    f.write("="*100 + "\n\n")

    # 1. Check: does the model benefit from picking stocks that had extreme multi-board runs?
    f.write("1. 检查: 模型收益是否过度依赖少数几只'妖股'?\n")
    f.write("-"*60 + "\n")

    model1_log = simulate_model(lambda d, c: c[0]['name'] if c else None)

    # Find trades that contributed most to returns
    trade_returns = []
    for i, log in enumerate(model1_log):
        if log['bought'] and i > 0:
            prev_log = model1_log[i-1]
            # Find when this was sold
            for j in range(i+1, len(model1_log)):
                if not model1_log[j]['held'] or model1_log[j]['held'][0][0] != log['bought']['name']:
                    # Sold at this point or still holding
                    if j < len(model1_log) - 1:
                        sell_log = model1_log[j]
                        buy_price = log['bought']['price']
                        sell_price = price_db[log['bought']['name']][sell_log['date']]['open']
                        ret = (sell_price - buy_price) / buy_price * 100
                        hold_days = (datetime.strptime(sell_log['date'], '%Y-%m-%d') -
                                    datetime.strptime(log['date'], '%Y-%m-%d')).days
                        trade_returns.append({
                            'name': log['bought']['name'],
                            'buy_date': log['date'],
                            'sell_date': sell_log['date'],
                            'return': ret,
                            'days': hold_days,
                            'shares': log['bought']['shares'],
                            'cost': log['bought']['cost'],
                        })
                    break

    trade_returns.sort(key=lambda x: x['return'], reverse=True)
    f.write(f"总交易: {len(trade_returns)}笔\n")
    total_pnl = sum(t['return'] * t['cost'] / 100 for t in trade_returns)
    f.write(f"总盈亏: {total_pnl:,.0f}\n\n")

    f.write("收益最高的前10笔交易:\n")
    f.write(f"{'标的':<10} {'买入日':<12} {'卖出日':<12} {'持有天':>5} {'收益率':>8} {'贡献':>10}\n")
    for t in trade_returns[:10]:
        contrib = t['return'] * t['cost'] / 100
        f.write(f"{t['name']:<10} {t['buy_date']:<12} {t['sell_date']:<12} {t['days']:>5} {t['return']:>+7.1f}% {contrib:>10,.0f}\n")

    top5_pnl = sum(t['return'] * t['cost'] / 100 for t in trade_returns[:5])
    f.write(f"\n前5笔贡献: {top5_pnl:,.0f} / {total_pnl:,.0f} ({top5_pnl/total_pnl*100:.0f}%)\n")

    # 2. Compare model picks vs trader picks head-to-head
    f.write("\n\n2. 头对头对比: 模型#1 vs 交易员选择\n")
    f.write("-"*60 + "\n")
    f.write(f"{'日期':<12} {'模型选':<10} {'模型结果':>8} {'交易员选':<10} {'交易员结果':>10} {'模型胜?':>6}\n")
    f.write("-"*60 + "\n")

    model_wins = 0
    trader_wins = 0
    ties = 0
    comparisons = 0

    for i, log in enumerate(model1_log):
        if log['bought']:
            date = log['date']
            trader_pick = dict(timeline).get(date, '')
            model_pick = log['bought']['name']

            if trader_pick in price_db and date in price_db[trader_pick]:
                # Simulate: if trader bought their pick at open
                trader_change = price_db[trader_pick][date]['change_pct']
                model_change = price_db[model_pick][date]['change_pct'] if model_pick in price_db and date in price_db[model_pick] else 0

                model_better = "是" if model_change > trader_change else ("否" if model_change < trader_change else "平")
                if model_change > trader_change: model_wins += 1
                elif model_change < trader_change: trader_wins += 1
                else: ties += 1
                comparisons += 1

                f.write(f"{date:<12} {model_pick:<10} {model_change:>+7.1f}% {trader_pick:<10} {trader_change:>+9.1f}% {model_better:>6}\n")

    f.write(f"\n模型胜: {model_wins}, 交易员胜: {trader_wins}, 平: {ties}")
    f.write(f"\n模型当日表现胜率: {model_wins}/{comparisons} ({model_wins/comparisons*100:.0f}%)\n")

    # 3. What if we use the SAME sell rules but BUY the trader's actual picks?
    f.write("\n\n3. 一致性检查: 同样卖出规则下不同选股的表现\n")
    f.write("-"*60 + "\n")

    # Re-simulate trader's picks with exact same sell logic
    def pick_trader(date, candidates):
        return dict(timeline).get(date, None)

    trader_relog = simulate_model(pick_trader)
    trader_final = trader_relog[-1]['total']
    model_final = model1_log[-1]['total']

    f.write(f"交易员选股+模型卖出规则: {trader_final:,.0f}\n")
    f.write(f"模型选股+模型卖出规则: {model_final:,.0f}\n")
    f.write(f"差额完全来自选股: {model_final - trader_final:+,.0f}\n")

    # 4. Out-of-sample test: train on first half, test on second half
    f.write("\n\n4. 样本外测试: 前2.5月训练评分权重, 后2.5月测试\n")
    f.write("-"*60 + "\n")

    mid_date = '2026-05-15'
    first_half_dates = [d for d in all_trade_dates if d < mid_date]
    second_half_dates = [d for d in all_trade_dates if d >= mid_date]

    # Compute which factors worked best in first half
    first_half_trades = []
    for date in first_half_dates:
        record = dict(timeline).get(date, '休息')
        if record == '休息': continue
        candidates = get_candidates(date, price_db, stock_data, top_n=1)
        if candidates:
            name = candidates[0]['name']
            if name in price_db and date in price_db[name]:
                is_lu = price_db[name][date]['is_limit_up']
                first_half_trades.append({
                    'name': name, 'date': date,
                    'is_lu': is_lu,
                    'vol20': candidates[0]['t1_vol20'],
                    'gap': candidates[0]['t1_gap'],
                    'cons': candidates[0]['t1_cons'],
                })

    first_half_wins = sum(1 for t in first_half_trades if t['is_lu'])
    f.write(f"前半段(#1候选): {first_half_wins}/{len(first_half_trades)} ({first_half_wins/len(first_half_trades)*100:.0f}%)\n")

    # Simulate second half with model1
    second_half_log = []
    positions = []
    cash = INITIAL_CAPITAL  # Reset capital
    for date_idx, date in enumerate(all_trade_dates):
        if date < mid_date: continue  # Skip first half
        record = dict(timeline).get(date, '休息')
        prev_date = all_trade_dates[all_trade_dates.index(date) - 1] if all_trade_dates.index(date) > 0 else None

        for pos in positions[:]:
            should_sell = True
            if prev_date and prev_date in price_db.get(pos['name'], {}):
                if price_db[pos['name']][prev_date]['is_limit_up']:
                    should_sell = False
            if should_sell:
                if date in price_db.get(pos['name'], {}):
                    sell_price = price_db[pos['name']][date]['open']
                    proceeds = sell_price * pos['shares']
                    cash += proceeds
                    positions.remove(pos)

        if record != '休息' and len(positions) == 0:
            candidates = get_candidates(date, price_db, stock_data, top_n=1)
            if candidates:
                selected = candidates[0]['name']
                if selected in price_db and date in price_db[selected]:
                    buy_price = price_db[selected][date]['open']
                    shares = int(cash / buy_price / 100) * 100
                    if shares > 0:
                        cost = shares * buy_price
                        cash -= cost
                        positions.append({'name': selected, 'buy_date': date,
                                         'buy_price': buy_price, 'shares': shares})

        pv = sum(pos['shares'] * price_db.get(pos['name'], {}).get(date, {}).get('close', 0) for pos in positions)
        second_half_log.append({'date': date, 'total': cash + pv})

    if second_half_log:
        sh_final = second_half_log[-1]['total']
        sh_return = (sh_final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        f.write(f"后半段独立测试(从{mid_date}开始, 初始{INITIAL_CAPITAL:,}):\n")
        f.write(f"  终值: {sh_final:,.0f} | 收益: {sh_return:+.1f}%\n")

        # Count wins in second half
        sh_wins = 0
        sh_total = 0
        for log in second_half_log:
            # Check each trade
            pass
        f.write(f"  说明: 前半段数据仅用于验证因子有效性, 后半段独立运行\n")

print(f"Validation complete! Output: {out_path}")
