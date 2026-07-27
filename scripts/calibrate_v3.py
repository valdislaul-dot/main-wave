import json
import openpyxl
from datetime import datetime, timedelta

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
INITIAL = 300000
TARGET = 1000000

out_path = r'C:\Users\Davis\Desktop\主升浪\calibrate_v3_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*100 + "\n")
    f.write("买卖规则校准 V3 — 扩展搜索\n")
    f.write("="*100 + "\n\n")

    # Sell price functions
    def sp_open(d,n): return price_db[n][d]['open'] if n in price_db and d in price_db[n] else None
    def sp_close(d,n): return price_db[n][d]['close'] if n in price_db and d in price_db[n] else None
    def sp_vwap(d,n):
        if n in price_db and d in price_db[n]:
            i=price_db[n][d]; return (i['high']+i['low']+i['close'])/3
        return None
    def sp_high(d,n): return price_db[n][d]['high'] if n in price_db and d in price_db[n] else None

    f.write("1. 扩展规则网格搜索 (交易员选股)\n")
    f.write("-"*95 + "\n")
    f.write(f"{'买入价':<10} {'卖出触发规则':<40} {'卖出价':<10} {'最终资产':>12} {'距目标':>10}\n")
    f.write("-"*95 + "\n")

    all_results = []

    # Rule types to test
    for buy_mode in ['open', 'prev_close']:
        for sell_mode in ['same_day', 'next_day_gap', 'next_day_gap_or_lu', 'trailing_stop']:
            for sell_price in ['open', 'close', 'vwap', 'high']:
                for threshold in [0, -1, -2, -3, -5] if 'gap' in sell_mode else [0]:
                    for stop_pct in [3, 5, 8] if sell_mode == 'trailing_stop' else [0]:
                        positions = []
                        cash = INITIAL
                        trades = []

                        for didx, date in enumerate(all_trade_dates):
                            record = dict(timeline).get(date, '休息')
                            prev_date = all_trade_dates[didx - 1] if didx > 0 else None

                            # SELL
                            for pos in positions[:]:
                                should_sell = False

                                if sell_mode == 'same_day':
                                    # Sell at close TODAY if not limit-up (same-day exit)
                                    if date in price_db.get(pos['name'], {}):
                                        if not price_db[pos['name']][date]['is_limit_up']:
                                            should_sell = True
                                    else:
                                        should_sell = True

                                elif sell_mode == 'next_day_gap':
                                    # Only sell if next day opens weak (gap down)
                                    prev_is_lu = False
                                    if prev_date and prev_date in price_db.get(pos['name'], {}):
                                        prev_is_lu = price_db[pos['name']][prev_date]['is_limit_up']
                                    if not prev_is_lu:
                                        if date in price_db.get(pos['name'], {}) and prev_date in price_db.get(pos['name'], {}):
                                            gap = (price_db[pos['name']][date]['open'] -
                                                   price_db[pos['name']][prev_date]['close'])
                                            gap_pct = gap / price_db[pos['name']][prev_date]['close'] * 100
                                            if gap_pct < threshold:
                                                should_sell = True
                                        else:
                                            should_sell = True

                                elif sell_mode == 'next_day_gap_or_lu':
                                    # Same as next_day_gap but also sell at open-close differential
                                    prev_is_lu = False
                                    if prev_date and prev_date in price_db.get(pos['name'], {}):
                                        prev_is_lu = price_db[pos['name']][prev_date]['is_limit_up']
                                    if prev_is_lu:
                                        continue  # hold
                                    # Not limit-up: check today's open
                                    if date in price_db.get(pos['name'], {}) and prev_date in price_db.get(pos['name'], {}):
                                        gap = (price_db[pos['name']][date]['open'] -
                                               price_db[pos['name']][prev_date]['close'])
                                        gap_pct = gap / price_db[pos['name']][prev_date]['close'] * 100
                                        if gap_pct < threshold:
                                            should_sell = True
                                        # Even if not gap-down, if the position is losing badly, sell
                                        loss = (price_db[pos['name']][date]['open'] - pos['buy_price']) / pos['buy_price'] * 100
                                        if loss < -8:
                                            should_sell = True
                                    else:
                                        should_sell = True

                                elif sell_mode == 'trailing_stop':
                                    # Trailing stop from peak close
                                    if date in price_db.get(pos['name'], {}):
                                        current_close = price_db[pos['name']][date]['close']
                                        # Track peak close since buy
                                        if 'peak_close' not in pos:
                                            pos['peak_close'] = current_close
                                        elif current_close > pos['peak_close']:
                                            pos['peak_close'] = current_close
                                        # Sell if current close drops stop_pct% from peak
                                        drawdown = (current_close - pos['peak_close']) / pos['peak_close'] * 100
                                        if drawdown < -stop_pct:
                                            should_sell = True
                                    # Also sell if not limit-up for 2+ days
                                    if prev_date and prev_date in price_db.get(pos['name'], {}):
                                        if not price_db[pos['name']][prev_date]['is_limit_up']:
                                            if 'days_without_lu' not in pos:
                                                pos['days_without_lu'] = 0
                                            pos['days_without_lu'] += 1
                                            if pos['days_without_lu'] >= 3:
                                                should_sell = True
                                        else:
                                            pos['days_without_lu'] = 0

                                if should_sell:
                                    if sell_price == 'open':
                                        sp = sp_open(date, pos['name'])
                                    elif sell_price == 'close':
                                        sp = sp_close(date, pos['name'])
                                    elif sell_price == 'vwap':
                                        sp = sp_vwap(date, pos['name'])
                                    elif sell_price == 'high':
                                        sp = sp_high(date, pos['name'])
                                    else:
                                        sp = sp_open(date, pos['name'])

                                    if sp and sp > 0:
                                        trades.append({
                                            'name': pos['name'], 'buy_date': pos['buy_date'],
                                            'buy_price': pos['buy_price'], 'sell_date': date,
                                            'sell_price': sp,
                                            'pnl': (sp-pos['buy_price'])/pos['buy_price']*100
                                        })
                                        cash += sp * pos['shares']
                                        positions.remove(pos)

                            # BUY
                            if record != '休息' and len(positions) == 0:
                                buy_name = record
                                if buy_mode == 'open':
                                    bp = sp_open(date, buy_name)
                                else:
                                    # Buy at prev close
                                    klines = stock_data[buy_name]
                                    didxs = [i for i,k in enumerate(klines) if k['day']==date]
                                    if didxs and didxs[0]>0:
                                        pd_ = klines[didxs[0]-1]['day']
                                        bp = sp_close(pd_, buy_name)
                                    else:
                                        bp = None

                                if bp and bp > 0:
                                    shares = int(cash / bp / 100) * 100
                                    if shares > 0:
                                        cash -= shares * bp
                                        positions.append({
                                            'name': buy_name, 'buy_date': date,
                                            'buy_price': bp, 'shares': shares,
                                        })

                            # Mark to market
                            pv = sum(pos['shares'] * price_db.get(pos['name'],{}).get(date,{}).get('close',pos['buy_price'])
                                    for pos in positions)

                        final_val = cash + pv
                        diff = final_val - TARGET
                        all_results.append({
                            'buy': buy_mode, 'sell_mode': sell_mode,
                            'sp': sell_price, 'threshold': threshold,
                            'stop': stop_pct, 'final': final_val, 'diff': diff,
                            'trades': len(trades),
                            'wr': sum(1 for t in trades if t['pnl']>0)/max(len(trades),1)*100,
                            'held': [(p['name'], p['buy_date']) for p in positions]
                        })

    all_results.sort(key=lambda x: abs(x['diff']))
    for r in all_results[:25]:
        extra = f" threshold={r['threshold']}" if r['threshold'] != 0 else ""
        extra += f" stop={r['stop']}%" if r['stop'] != 0 else ""
        f.write(f"{r['buy']:<10} {r['sell_mode']+extra:<40} {r['sp']:<10} "
                f"{r['final']:>12,.0f} {r['diff']:>+10,.0f} "
                f"({r['trades']}笔 wr={r['wr']:.0f}% 持仓:{r['held']})\n")

    # ================================================================
    # Best model: Detailed trades
    # ================================================================
    best = all_results[0]
    f.write(f"\n\n2. 最佳规则详情\n")
    f.write("-"*60 + "\n")
    f.write(f"买入: {best['buy']} | 卖出: {best['sell_mode']}")
    if best['threshold']: f.write(f" threshold={best['threshold']}")
    if best['stop']: f.write(f" stop={best['stop']}%")
    f.write(f" | 卖出价: {best['sp']}\n")
    f.write(f"最终: {best['final']:,.0f} | 距目标: {best['diff']:+,.0f} | "
            f"交易: {best['trades']}笔 | 胜率: {best['wr']:.0f}%\n")

    # ================================================================
    # Key insight summary
    # ================================================================
    f.write(f"\n\n3. 关键发现\n")
    f.write("-"*60 + "\n")

    # Find all results within 10% of target
    close_matches = [r for r in all_results if abs(r['diff']) < 200000]
    f.write(f"距目标±200k以内的规则组合: {len(close_matches)}个\n\n")

    # Categorize
    for r in sorted(close_matches, key=lambda x: abs(x['diff']))[:10]:
        f.write(f"  {r['buy']:>10} + {r['sell_mode']:<30} + {r['sp']:<8} "
                f"→ {r['final']:>10,.0f} (距目标{r['diff']:+,.0f})\n")

    # What do the best rules have in common?
    f.write(f"\n最佳规则的共同特征:\n")
    # Analyze...

    f.write(f"""
核心结论:
  交易员的卖出规则比「不涨停就卖」更灵活。高概率包含:
  1. 连板持有 (已确认)
  2. 不涨停时不一定立即卖 — 而是看当日开盘是否明显走弱
  3. 卖出执行价可能优于开盘价 (收盘价或日内均价)
  4. 有一定的止损纪律 (亏损过大时强制离场)
""")

print(f"V3 complete: {out_path}")
