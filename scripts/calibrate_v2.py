import json
import openpyxl
from datetime import datetime, timedelta
from collections import defaultdict

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
    if code.startswith('30') or code.startswith('688'): return 0.20
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
        else:
            entry['vol_ma20'] = v
        entry['vol_ratio5'] = v / entry['vol_ma5'] if entry['vol_ma5'] > 0 else 1
        entry['vol_ratio20'] = v / entry['vol_ma20'] if entry['vol_ma20'] > 0 else 1
        price_db[name][date] = entry
        prev_close = c

timeline = []
for serial, stock in records:
    d = excel_to_date(serial)
    timeline.append((d.strftime('%Y-%m-%d'), stock))
all_trade_dates = sorted(set(d for d, _ in timeline))
INITIAL_CAPITAL = 300000
TARGET = 1000000

out_path = r'C:\Users\Davis\Desktop\主升浪\calibrate_v2_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*100 + "\n")
    f.write("买卖规则精细校准 V2\n")
    f.write(f"目标: 用交易员实际选股达到约{TARGET:,}\n")
    f.write("="*100 + "\n\n")

    # Key question: what is the SELL rule?
    # Hypothesis: trader is PATIENT — only sells on clear weakness, not just "not limit-up"
    # This means: 连板持有 (hold through limit-ups) + 不破位持有 (hold through minor pullbacks)

    f.write("1. 「低开才卖」阈值搜索\n")
    f.write("规则: 前日不涨停 + 今日开盘跌幅超过X% → 才卖出\n")
    f.write("-"*80 + "\n")
    f.write(f"{'卖出阈值':<12} {'卖出价':<12} {'最终资产':>12} {'收益率':>10} {'交易笔数':>8} {'胜率':>8} {'距目标':>10}\n")
    f.write("-"*80 + "\n")

    # Sell price functions
    def sp_open(date, name):
        return price_db[name][date]['open'] if name in price_db and date in price_db[name] else None
    def sp_close(date, name):
        return price_db[name][date]['close'] if name in price_db and date in price_db[name] else None
    def sp_vwap(date, name):
        if name in price_db and date in price_db[name]:
            i = price_db[name][date]
            return (i['high'] + i['low'] + i['close']) / 3
        return None
    def sp_mid(date, name):
        if name in price_db and date in price_db[name]:
            i = price_db[name][date]
            return (i['open'] + i['close']) / 2
        return None

    best_results = []

    for gap_threshold in [0, -0.5, -1, -1.5, -2, -3, -5, -8, -10]:
        for sell_price_fn, sp_label in [(sp_open, '开盘价'), (sp_vwap, 'VWAP'), (sp_mid, '开盘收盘均'), (sp_close, '收盘价')]:
            # Simulate with trader picks
            positions = []
            cash = INITIAL_CAPITAL
            trade_count = 0
            win_count = 0

            for date_idx, date in enumerate(all_trade_dates):
                record = dict(timeline).get(date, '休息')
                prev_date = all_trade_dates[date_idx - 1] if date_idx > 0 else None

                # SELL
                for pos in positions[:]:
                    should_sell = False
                    # Rule 1: If prev day was limit-up, hold
                    prev_is_lu = False
                    if prev_date and prev_date in price_db.get(pos['name'], {}):
                        if price_db[pos['name']][prev_date]['is_limit_up']:
                            prev_is_lu = True

                    if not prev_is_lu:
                        # Rule 2: Check gap from prev close
                        if date in price_db.get(pos['name'], {}) and prev_date in price_db.get(pos['name'], {}):
                            today_open = price_db[pos['name']][date]['open']
                            prev_close_val = price_db[pos['name']][prev_date]['close']
                            if prev_close_val > 0:
                                gap_pct = (today_open - prev_close_val) / prev_close_val * 100
                                if gap_pct < gap_threshold:  # Gap is worse than threshold
                                    should_sell = True
                        else:
                            should_sell = True  # No data, sell

                    if should_sell:
                        sp = sell_price_fn(date, pos['name'])
                        if sp and sp > 0:
                            pnl = (sp - pos['buy_price']) / pos['buy_price'] * 100
                            if pnl > 0: win_count += 1
                            trade_count += 1
                            cash += sp * pos['shares']
                            positions.remove(pos)

                # BUY (trader picks)
                if record != '休息' and len(positions) == 0:
                    buy_name = record
                    if buy_name in price_db and date in price_db[buy_name]:
                        buy_price = price_db[buy_name][date]['open']
                        shares = int(cash / buy_price / 100) * 100
                        if shares > 0:
                            cash -= shares * buy_price
                            positions.append({
                                'name': buy_name, 'buy_date': date,
                                'buy_price': buy_price, 'shares': shares
                            })

                pv = sum(pos['shares'] * price_db.get(pos['name'], {}).get(date, {}).get('close', pos['buy_price'])
                        for pos in positions)

            final_val = cash + pv
            ret = (final_val - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
            diff = final_val - TARGET
            wr = win_count / trade_count * 100 if trade_count > 0 else 0

            best_results.append({
                'gap': gap_threshold, 'sp': sp_label, 'final': final_val,
                'ret': ret, 'diff': diff, 'trades': trade_count, 'wr': wr,
            })

    best_results.sort(key=lambda x: abs(x['diff']))
    for r in best_results[:15]:
        f.write(f"{r['gap']:>+6.1f}%     {r['sp']:<12} {r['final']:>12,.0f} {r['ret']:>+9.1f}% "
                f"{r['trades']:>8} {r['wr']:>7.0f}% {r['diff']:>+10,.0f}\n")

    # ================================================================
    # Detailed log of best match
    # ================================================================
    best = best_results[0]
    f.write(f"\n\n2. 最佳匹配规则详情\n")
    f.write("-"*60 + "\n")
    f.write(f"规则: 前日不涨停 + 今日开盘跌幅 < {best['gap']:+.1f}% → 卖出\n")
    f.write(f"卖出价格: {best['sp']}\n")
    f.write(f"最终资产: {best['final']:,.0f} | 收益: {best['ret']:+.1f}% | 距目标: {best['diff']:+,.0f}\n\n")

    # Re-run with best rule and log every trade
    gap_t = best['gap']
    sp_label = best['sp']
    if sp_label == '开盘价': sp_fn = sp_open
    elif sp_label == 'VWAP': sp_fn = sp_vwap
    elif sp_label == '开盘收盘均': sp_fn = sp_mid
    else: sp_fn = sp_close

    positions = []
    cash = INITIAL_CAPITAL
    trades_log = []

    for date_idx, date in enumerate(all_trade_dates):
        record = dict(timeline).get(date, '休息')
        prev_date = all_trade_dates[date_idx - 1] if date_idx > 0 else None

        for pos in positions[:]:
            should_sell = False
            prev_is_lu = False
            if prev_date and prev_date in price_db.get(pos['name'], {}):
                if price_db[pos['name']][prev_date]['is_limit_up']:
                    prev_is_lu = True
            if not prev_is_lu:
                if date in price_db.get(pos['name'], {}) and prev_date in price_db.get(pos['name'], {}):
                    today_open = price_db[pos['name']][date]['open']
                    prev_close_val = price_db[pos['name']][prev_date]['close']
                    if prev_close_val > 0:
                        gap_pct = (today_open - prev_close_val) / prev_close_val * 100
                        if gap_pct < gap_t:
                            should_sell = True
                else:
                    should_sell = True
            if should_sell:
                sp = sp_fn(date, pos['name'])
                if sp and sp > 0:
                    pnl = (sp - pos['buy_price']) / pos['buy_price'] * 100
                    hold_days = (datetime.strptime(date, '%Y-%m-%d') -
                                datetime.strptime(pos['buy_date'], '%Y-%m-%d')).days
                    trades_log.append({
                        'name': pos['name'], 'buy_date': pos['buy_date'],
                        'buy_price': pos['buy_price'], 'sell_date': date,
                        'sell_price': sp, 'pnl': pnl, 'hold_days': hold_days
                    })
                    cash += sp * pos['shares']
                    positions.remove(pos)

        if record != '休息' and len(positions) == 0:
            buy_name = record
            if buy_name in price_db and date in price_db[buy_name]:
                buy_price = price_db[buy_name][date]['open']
                shares = int(cash / buy_price / 100) * 100
                if shares > 0:
                    cash -= shares * buy_price
                    positions.append({
                        'name': buy_name, 'buy_date': date,
                        'buy_price': buy_price, 'shares': shares
                    })

        pv = sum(pos['shares'] * price_db.get(pos['name'], {}).get(date, {}).get('close', pos['buy_price'])
                for pos in positions)

    f.write(f"{'买入日':<12} {'标的':<10} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'盈亏':>8} {'持天':>4}\n")
    f.write("-"*65 + "\n")
    total_pnl_amt = 0
    wins = 0
    for t in trades_log:
        pnl_amt = (t['sell_price'] - t['buy_price']) * 100  # approximate per 100 shares
        total_pnl_amt += (t['sell_price'] - t['buy_price']) * (INITIAL_CAPITAL / t['buy_price'] / 100)  # rough
        if t['pnl'] > 0: wins += 1
        f.write(f"{t['buy_date']:<12} {t['name']:<10} {t['buy_price']:>8.2f} "
                f"{t['sell_date']:<12} {t['sell_price']:>8.2f} {t['pnl']:>+7.1f}% {t['hold_days']:>4}\n")

    f.write(f"\n总交易: {len(trades_log)}笔 | 盈利: {wins} | 胜率: {wins/len(trades_log)*100:.0f}%\n")
    final_val_with_trader = cash + pv
    f.write(f"剩余持仓: {[(p['name'], p['buy_date']) for p in positions]}\n")
    f.write(f"最终资产: {final_val_with_trader:,.0f}\n")

    # ================================================================
    # Apply best execution to MODEL picks
    # ================================================================
    f.write(f"\n\n3. 应用校准后的规则到模型选股\n")
    f.write("-"*60 + "\n")

    def score_v2(name, date, price_db, stock_data):
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
        t2_is_lu = False
        if idx >= 2:
            t2_d = klines[idx - 2]['day']
            if t2_d in price_db[name]: t2_is_lu = price_db[name][t2_d]['is_limit_up']
        score = 0.0
        vol20 = t1.get('vol_ratio20', 1)
        if vol20 < 0.3: score += 35
        elif vol20 < 0.5: score += 28
        elif vol20 < 0.7: score += 22
        elif vol20 < 1.0: score += 16
        elif vol20 < 1.5: score += 8
        elif vol20 < 2.0: score += 2
        elif vol20 < 3.0: score -= 3
        elif vol20 < 5.0: score -= 10
        else: score -= 18
        gap = t1['gap_open_pct']
        if gap >= 9.5: score += 22
        elif gap >= 8: score += 18
        elif gap >= 5: score += 13
        elif gap >= 3: score += 7
        elif gap >= 1: score += 2
        elif gap >= 0: score += 0
        else: score -= 12
        if t1.get('is_one_line', False): score += 12
        cons = t1.get('cons_lu_before', 0)
        if cons == 0: score += 3
        elif cons == 1: score += 10
        elif cons == 2: score += 12
        elif cons >= 3: score += 7
        dow = datetime.strptime(date, '%Y-%m-%d').weekday()
        if dow == 0: score += 18
        elif dow == 4: score -= 5
        seal = t1.get('seal_quality', 1)
        if seal >= 0.99: score += 6
        elif seal >= 0.95: score += 3
        elif seal < 0.85: score -= 10
        buy_gap = buy_info['gap_open_pct']
        if buy_gap > 8: score += 8
        elif buy_gap > 5: score += 5
        elif buy_gap > 2: score += 2
        elif buy_gap > 0: score += 0
        elif buy_gap > -2: score -= 5
        else: score -= 25
        if t2_is_lu: score += 6
        return score

    def get_model_pick(date):
        candidates = []
        for name in price_db:
            s = score_v2(name, date, price_db, stock_data)
            if s > -999:
                klines = stock_data[name]
                date_indices = [i for i, k in enumerate(klines) if k['day'] == date]
                idx = date_indices[0]
                prev_date = klines[idx - 1]['day']
                t1 = price_db[name][prev_date]
                candidates.append({
                    'name': name, 'score': s,
                    't1_vol20': t1.get('vol_ratio20', 1),
                })
        candidates.sort(key=lambda x: x['score'], reverse=True)
        if not candidates: return None
        top3 = candidates[:3]
        top3.sort(key=lambda x: x['t1_vol20'])
        return top3[0]['name']

    # Simulate model picks with calibrated rules
    positions = []
    cash = INITIAL_CAPITAL
    model_trades = []

    for date_idx, date in enumerate(all_trade_dates):
        record = dict(timeline).get(date, '休息')
        prev_date = all_trade_dates[date_idx - 1] if date_idx > 0 else None

        for pos in positions[:]:
            should_sell = False
            prev_is_lu = False
            if prev_date and prev_date in price_db.get(pos['name'], {}):
                if price_db[pos['name']][prev_date]['is_limit_up']:
                    prev_is_lu = True
            if not prev_is_lu:
                if date in price_db.get(pos['name'], {}) and prev_date in price_db.get(pos['name'], {}):
                    today_open = price_db[pos['name']][date]['open']
                    prev_close_val = price_db[pos['name']][prev_date]['close']
                    if prev_close_val > 0:
                        gap_pct = (today_open - prev_close_val) / prev_close_val * 100
                        if gap_pct < gap_t:
                            should_sell = True
                else:
                    should_sell = True
            if should_sell:
                sp = sp_fn(date, pos['name'])
                if sp and sp > 0:
                    pnl = (sp - pos['buy_price']) / pos['buy_price'] * 100
                    model_trades.append({
                        'name': pos['name'], 'buy_date': pos['buy_date'],
                        'buy_price': pos['buy_price'], 'sell_date': date,
                        'sell_price': sp, 'pnl': pnl
                    })
                    cash += sp * pos['shares']
                    positions.remove(pos)

        if record != '休息' and len(positions) == 0:
            model_pick = get_model_pick(date)
            if model_pick and model_pick in price_db and date in price_db[model_pick]:
                buy_price = price_db[model_pick][date]['open']
                shares = int(cash / buy_price / 100) * 100
                if shares > 0:
                    cash -= shares * buy_price
                    positions.append({
                        'name': model_pick, 'buy_date': date,
                        'buy_price': buy_price, 'shares': shares
                    })

        pv = sum(pos['shares'] * price_db.get(pos['name'], {}).get(date, {}).get('close', pos['buy_price'])
                for pos in positions)

    model_final = cash + pv
    model_ret = (model_final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    model_wins = sum(1 for t in model_trades if t['pnl'] > 0)
    f.write(f"模型选股 + 校准后的卖出规则:\n")
    f.write(f"  最终资产: {model_final:,.0f} | 收益: {model_ret:+.1f}%\n")
    f.write(f"  交易笔数: {len(model_trades)} | 胜率: {model_wins/len(model_trades)*100:.0f}%\n")
    f.write(f"  剩余持仓: {[(p['name'], p['buy_date']) for p in positions]}\n")

    # ================================================================
    # Also test: what if trader also uses our model picks?
    # ================================================================
    f.write(f"\n\n4. 总结: 校准后的交易员真实规则\n")
    f.write("-"*60 + "\n")
    f.write(f"""
从回测校准推断的交易员真实执行规则:

【买入规则】
  - 时机: 每个交易日只要有候选标的就买入
  - 价格: 开盘价买入 (与之前假设一致)
  - 仓位: 全仓单票

【卖出规则】← 这是与之前假设最大的不同
  - 如果前日涨停 → 继续持有 (连板持有, 与之前一致)
  - 如果前日不涨停 → 不立即卖出! 而是看今日开盘强弱:
    · 如果今日开盘跌幅 < {gap_t:+.1f}% → 继续持有 (忍受小幅回调)
    · 如果今日开盘跌幅 ≥ {gap_t:+.1f}% → 卖出
  - 卖出价格: {sp_label}

【关键差异 vs 之前假设】
  旧模型: 不涨停 = 次日开盘无条件卖出
  真实规则: 不涨停 + 低开超过阈值才卖出
  → 交易员比我们假设的更有耐心!
  → 这让股票有机会经历短暂回调后继续上涨
""")

    # Final comparison table
    f.write(f"\n5. 完整对比\n")
    f.write("-"*70 + "\n")
    f.write(f"{'模型':<40} {'最终资产':>12} {'收益率':>10}\n")
    f.write("-"*70 + "\n")
    f.write(f"{'交易员选股 + 旧卖出规则(不涨停就卖)':<40} {108912:>12,.0f} {'-63.7%':>10}\n")
    f.write(f"{'交易员选股 + 校准后卖出规则':<40} {final_val_with_trader:>12,.0f} {((final_val_with_trader-300000)/300000*100):>+9.1f}%\n")
    f.write(f"{'模型选股 + 校准后卖出规则':<40} {model_final:>12,.0f} {model_ret:>+9.1f}%\n")

print(f"Calibration V2 complete! Output: {out_path}")
