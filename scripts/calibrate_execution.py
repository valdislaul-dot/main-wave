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
        price_db[name][date] = entry
        prev_close = c

timeline = []
for serial, stock in records:
    d = excel_to_date(serial)
    timeline.append((d.strftime('%Y-%m-%d'), stock))
all_trade_dates = sorted(set(d for d, _ in timeline))
INITIAL_CAPITAL = 300000
TARGET_FINAL = 1000000

out_path = r'C:\Users\Davis\Desktop\主升浪\calibrate_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*100 + "\n")
    f.write("买卖规则校准 — 反推交易员真实执行规则\n")
    f.write(f"目标: 用交易员实际选股达到约{TARGET_FINAL:,} (实际已知结果)\n")
    f.write("="*100 + "\n\n")

    # ================================================================
    # Test different execution rule combinations
    # ================================================================

    def simulate_with_rules(buy_price_fn, sell_trigger_fn, sell_price_fn, position_pct=1.0):
        """
        buy_price_fn(date, name) -> buy price
        sell_trigger_fn(positions, date, prev_date, price_db) -> list of positions to sell
        sell_price_fn(date, name) -> sell price
        position_pct: fraction of cash to deploy (1.0 = all-in)
        """
        positions = []  # {name, buy_date, buy_price, shares}
        cash = INITIAL_CAPITAL
        daily_log = []

        for date_idx, date in enumerate(all_trade_dates):
            record = dict(timeline).get(date, '休息')
            prev_date = all_trade_dates[date_idx - 1] if date_idx > 0 else None

            # SELL
            to_sell = sell_trigger_fn(positions, date, prev_date, price_db)
            for pos in to_sell:
                if pos in positions:
                    sell_price = sell_price_fn(date, pos['name'])
                    if sell_price and sell_price > 0:
                        proceeds = sell_price * pos['shares']
                        cash += proceeds
                        positions.remove(pos)

            # BUY
            stock_bought = None
            if record != '休息':
                buy_name = record
                buy_price = buy_price_fn(date, buy_name)
                if buy_price and buy_price > 0:
                    deploy_cash = cash * position_pct
                    shares = int(deploy_cash / buy_price / 100) * 100
                    if shares > 0:
                        cost = shares * buy_price
                        cash -= cost
                        positions.append({
                            'name': buy_name, 'buy_date': date,
                            'buy_price': buy_price, 'shares': shares
                        })
                        stock_bought = {'name': buy_name, 'price': buy_price,
                                       'shares': shares, 'cost': cost}

            # Portfolio value (use close for valuation)
            pv = sum(pos['shares'] * price_db.get(pos['name'], {}).get(date, {}).get('close', pos['buy_price'])
                    for pos in positions)
            daily_log.append({
                'date': date, 'held': [(p['name'], p['buy_date']) for p in positions],
                'cash': cash, 'total': cash + pv, 'bought': stock_bought
            })
        return daily_log

    # === SELL TRIGGER FUNCTIONS ===

    def trigger_sell_if_not_lu(positions, date, prev_date, price_db):
        """Current model: sell all if prev day wasn't limit-up"""
        to_sell = []
        for pos in positions:
            should_sell = True
            if prev_date and prev_date in price_db.get(pos['name'], {}):
                if price_db[pos['name']][prev_date]['is_limit_up']:
                    should_sell = False
            if should_sell:
                to_sell.append(pos)
        return to_sell

    def trigger_sell_if_gap_down(positions, date, prev_date, price_db):
        """Sell only if stock opens below previous close"""
        to_sell = []
        for pos in positions:
            should_sell = True
            if prev_date and prev_date in price_db.get(pos['name'], {}):
                if price_db[pos['name']][prev_date]['is_limit_up']:
                    should_sell = False
            # Even if not limit-up, only sell if gap is negative
            if not should_sell:
                continue
            if date in price_db.get(pos['name'], {}) and prev_date in price_db.get(pos['name'], {}):
                today_open = price_db[pos['name']][date]['open']
                prev_close = price_db[pos['name']][prev_date]['close']
                if today_open >= prev_close * 0.98:  # gap up or flat, hold
                    should_sell = False
            if should_sell:
                to_sell.append(pos)
        return to_sell

    def trigger_hold_min_days(positions, date, prev_date, price_db, min_days=2):
        """Hold at least min_days before considering selling"""
        to_sell = []
        for pos in positions:
            hold_days = (datetime.strptime(date, '%Y-%m-%d') -
                        datetime.strptime(pos['buy_date'], '%Y-%m-%d')).days
            if hold_days < min_days:
                continue  # must hold minimum days
            should_sell = True
            if prev_date and prev_date in price_db.get(pos['name'], {}):
                if price_db[pos['name']][prev_date]['is_limit_up']:
                    should_sell = False
            if should_sell:
                to_sell.append(pos)
        return to_sell

    def trigger_sell_stop_loss(positions, date, prev_date, price_db, stop_pct=-5):
        """Sell if loss exceeds stop_pct, or if not limit-up"""
        to_sell = []
        for pos in positions:
            should_sell = True
            if prev_date and prev_date in price_db.get(pos['name'], {}):
                if price_db[pos['name']][prev_date]['is_limit_up']:
                    should_sell = False
            if not should_sell:
                continue
            # Check stop loss
            if date in price_db.get(pos['name'], {}):
                current_open = price_db[pos['name']][date]['open']
                loss_pct = (current_open - pos['buy_price']) / pos['buy_price'] * 100
                # Even if not limit-up, if loss is small, maybe still hold?
                if loss_pct > stop_pct:  # not yet hit stop
                    should_sell = False
            if should_sell:
                to_sell.append(pos)
        return to_sell

    # === PRICE FUNCTIONS ===
    def buy_at_open(date, name):
        if name in price_db and date in price_db[name]:
            return price_db[name][date]['open']
        return None

    def buy_at_prev_close(date, name):
        """Buy at previous day's close (like after-hours decision)"""
        klines = stock_data[name]
        date_indices = [i for i, k in enumerate(klines) if k['day'] == date]
        if date_indices and date_indices[0] > 0:
            prev_date = klines[date_indices[0] - 1]['day']
            if prev_date in price_db[name]:
                return price_db[name][prev_date]['close']
        return None

    def sell_at_open(date, name):
        if name in price_db and date in price_db[name]:
            return price_db[name][date]['open']
        return None

    def sell_at_close(date, name):
        if name in price_db and date in price_db[name]:
            return price_db[name][date]['close']
        return None

    def sell_at_high(date, name):
        if name in price_db and date in price_db[name]:
            return price_db[name][date]['high']
        return None

    def sell_at_vwap(date, name):
        """Approximate VWAP as (H+L+C)/3"""
        if name in price_db and date in price_db[name]:
            info = price_db[name][date]
            return (info['high'] + info['low'] + info['close']) / 3
        return None

    # ================================================================
    # TEST GRID
    # ================================================================
    f.write("1. 买卖规则网格搜索 (目标: 达到 ~1,000,000)\n")
    f.write("-"*80 + "\n")
    f.write(f"{'买入价':<14} {'卖出触发':<30} {'卖出价':<12} {'仓位%':>6} {'最终资产':>12} {'收益率':>10} {'距目标':>10}\n")
    f.write("-"*95 + "\n")

    results = []

    buy_fns = [
        ('开盘价', buy_at_open),
        ('T-1收盘价', buy_at_prev_close),
    ]

    sell_configs = [
        ('不涨停就卖(基准)', trigger_sell_if_not_lu, sell_at_open),
        ('不涨停就卖', trigger_sell_if_not_lu, sell_at_close),
        ('不涨停就卖', trigger_sell_if_not_lu, sell_at_high),
        ('不涨停就卖', trigger_sell_if_not_lu, sell_at_vwap),
        ('低开才卖(高开持有)', trigger_sell_if_gap_down, sell_at_open),
        ('低开才卖(高开持有)', trigger_sell_if_gap_down, sell_at_close),
        ('低开才卖(高开持有)', trigger_sell_if_gap_down, sell_at_high),
        ('持有>=2天+不涨停卖', lambda p,d,pd,db: trigger_hold_min_days(p,d,pd,db,2), sell_at_open),
        ('持有>=2天+不涨停卖', lambda p,d,pd,db: trigger_hold_min_days(p,d,pd,db,2), sell_at_close),
        ('持有>=2天+不涨停卖', lambda p,d,pd,db: trigger_hold_min_days(p,d,pd,db,2), sell_at_high),
        ('止损-5%+不涨停卖', lambda p,d,pd,db: trigger_sell_stop_loss(p,d,pd,db,-5), sell_at_open),
        ('止损-5%+不涨停卖', lambda p,d,pd,db: trigger_sell_stop_loss(p,d,pd,db,-5), sell_at_close),
        ('止损-5%+不涨停卖', lambda p,d,pd,db: trigger_sell_stop_loss(p,d,pd,db,-5), sell_at_vwap),
        # The key one: sell at close when not limit-up
        ('不涨停就卖(收盘卖)', trigger_sell_if_not_lu, sell_at_close),
    ]

    # Deduplicate sell configs
    seen = set()
    unique_configs = []
    for label, trigger, price_fn in sell_configs:
        key = (label, trigger.__name__ if hasattr(trigger, '__name__') else str(trigger),
               price_fn.__name__)
        if key not in seen:
            seen.add(key)
            unique_configs.append((label, trigger, price_fn))

    for buy_label, buy_fn in buy_fns:
        for sell_label, sell_trigger, sell_price_fn in unique_configs[:15]:  # limit combinations
            for pos_pct in [1.0]:
                log = simulate_with_rules(buy_fn, sell_trigger, sell_price_fn, pos_pct)
                final_val = log[-1]['total']
                ret = (final_val - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
                diff_from_target = final_val - TARGET_FINAL
                results.append({
                    'buy': buy_label, 'sell_trigger': sell_label,
                    'sell_price': sell_price_fn.__name__,
                    'pos_pct': pos_pct, 'final': final_val, 'ret': ret,
                    'diff': diff_from_target, 'log': log
                })

    # Sort by proximity to target
    results.sort(key=lambda x: abs(x['diff']))

    for r in results[:20]:
        f.write(f"{r['buy']:<14} {r['sell_trigger']:<30} {r['sell_price']:<12} "
                f"{r['pos_pct']:>5.0%} {r['final']:>12,.0f} {r['ret']:>+9.1f}% {r['diff']:>+10,.0f}\n")

    # ================================================================
    # DEEP DIVE: Best matching rule
    # ================================================================
    best = results[0]
    f.write(f"\n\n2. 最接近交易员真实结果的规则组合\n")
    f.write("-"*60 + "\n")
    f.write(f"买入: {best['buy']} | 卖出触发: {best['sell_trigger']} | 卖出价: {best['sell_price']}\n")
    f.write(f"最终资产: {best['final']:,.0f} | 收益率: {best['ret']:+.1f}% | 距目标: {best['diff']:+,.0f}\n\n")

    # Show trade-by-trade log
    f.write("逐笔交易明细:\n")
    f.write(f"{'买入日':<12} {'标的':<10} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'盈亏':>8} {'持有天':>6}\n")
    f.write("-"*70 + "\n")

    trades = []
    current = None
    for log in best['log']:
        if log['bought']:
            current = {
                'buy_date': log['date'],
                'name': log['bought']['name'],
                'buy_price': log['bought']['price'],
                'shares': log['bought']['shares'],
                'cost': log['bought']['cost'],
            }
        if log['held'] == [] and current is not None:
            # Was sold — find sell date/price
            sell_date = log['date']
            sell_price = 0
            if current['name'] in price_db and sell_date in price_db[current['name']]:
                sell_price = price_db[current['name']][sell_date]['open']
            pnl = (sell_price - current['buy_price']) / current['buy_price'] * 100
            hold_days = (datetime.strptime(sell_date, '%Y-%m-%d') -
                        datetime.strptime(current['buy_date'], '%Y-%m-%d')).days
            trades.append({**current, 'sell_date': sell_date, 'sell_price': sell_price,
                          'pnl': pnl, 'hold_days': hold_days})
            current = None

    total_pnl = 0
    wins = 0
    for t in trades:
        pnl_amt = (t['sell_price'] - t['buy_price']) * t['shares']
        total_pnl += pnl_amt
        if t['pnl'] > 0: wins += 1
        f.write(f"{t['buy_date']:<12} {t['name']:<10} {t['buy_price']:>8.2f} "
                f"{t['sell_date']:<12} {t['sell_price']:>8.2f} {t['pnl']:>+7.1f}% {t['hold_days']:>6}\n")

    f.write(f"\n总交易: {len(trades)}笔 | 盈利: {wins} | 胜率: {wins/len(trades)*100:.0f}%\n")
    f.write(f"总PnL: {total_pnl:+,.0f}\n")

    # ================================================================
    # NOW: Apply best execution rules to OUR model picks
    # ================================================================
    f.write(f"\n\n3. 应用最佳执行规则到模型选股\n")
    f.write("-"*60 + "\n")

    # Build candidate scoring (same as before, using V2 scoring)
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
        vol20 = t1['vol_ratio20'] if 'vol_ratio20' in t1 else 1
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
        cons = t1['cons_lu_before'] if 'cons_lu_before' in t1 else 0
        if cons == 0: score += 3
        elif cons == 1: score += 10
        elif cons == 2: score += 12
        elif cons == 3: score += 8
        elif cons >= 4: score += 4
        dow = datetime.strptime(date, '%Y-%m-%d').weekday()
        if dow == 0: score += 18
        elif dow == 4: score -= 5
        seal = t1['seal_quality'] if 'seal_quality' in t1 else 1
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
        # Top 3, pick lowest volume
        top3 = candidates[:3]
        top3.sort(key=lambda x: x['t1_vol20'])
        return top3[0]['name']

    # Simulate with model picks + best execution rules
    best_buy_fn = buy_at_open  # from best match
    best_sell_trigger = best['sell_trigger'] if isinstance(best['sell_trigger'], str) else trigger_sell_if_not_lu
    best_sell_price_fn = sell_at_open  # default

    # Actually, let me re-run the best config from the grid search but with model picks
    # Find the actual best config
    best_config = results[0]

    # Build a proper simulation for model picks
    # We need to use the actual best trigger function, not just its label
    # Let me find the right one from the results
    for r in results[:5]:
        f.write(f"\n--- 规则: {r['buy']} + {r['sell_trigger']} + {r['sell_price']} ---\n")

        # Determine which trigger function to use
        if '低开才卖' in r['sell_trigger']:
            trigger_fn = trigger_sell_if_gap_down
        elif '持有>=2' in r['sell_trigger']:
            trigger_fn = lambda p,d,pd,db: trigger_hold_min_days(p,d,pd,db,2)
        elif '止损' in r['sell_trigger']:
            trigger_fn = lambda p,d,pd,db: trigger_sell_stop_loss(p,d,pd,db,-5)
        else:
            trigger_fn = trigger_sell_if_not_lu

        # Price functions
        if r['sell_price'] == 'sell_at_open':
            sp_fn = sell_at_open
        elif r['sell_price'] == 'sell_at_close':
            sp_fn = sell_at_close
        elif r['sell_price'] == 'sell_at_high':
            sp_fn = sell_at_high
        elif r['sell_price'] == 'sell_at_vwap':
            sp_fn = sell_at_vwap
        else:
            sp_fn = sell_at_open

        if r['buy'] == '开盘价':
            bp_fn = buy_at_open
        else:
            bp_fn = buy_at_prev_close

        # Now simulate with model picks instead of trader picks
        positions = []
        cash = INITIAL_CAPITAL
        for date_idx, date in enumerate(all_trade_dates):
            record = dict(timeline).get(date, '休息')
            prev_date = all_trade_dates[date_idx - 1] if date_idx > 0 else None

            # SELL using the calibrated rule
            to_sell = trigger_fn(positions, date, prev_date, price_db)
            for pos in to_sell:
                if pos in positions:
                    sp = sp_fn(date, pos['name'])
                    if sp and sp > 0:
                        cash += sp * pos['shares']
                        positions.remove(pos)

            # BUY using model pick (not trader pick)
            if record != '休息' and len(positions) == 0:
                model_pick = get_model_pick(date)
                if model_pick:
                    bp = bp_fn(date, model_pick)
                    if bp and bp > 0:
                        shares = int(cash / bp / 100) * 100
                        if shares > 0:
                            cash -= shares * bp
                            positions.append({'name': model_pick, 'buy_date': date,
                                            'buy_price': bp, 'shares': shares})

            pv = sum(pos['shares'] * price_db.get(pos['name'], {}).get(date, {}).get('close', pos['buy_price'])
                    for pos in positions)
        final = cash + pv
        ret = (final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        f.write(f"模型选股 + 交易员规则: 最终={final:,.0f} 收益={ret:+.1f}%\n")

print(f"Calibration complete! Output: {out_path}")
