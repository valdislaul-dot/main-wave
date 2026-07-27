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
    if code.startswith('30') or code.startswith('688'): return 0.20
    return 0.10

def is_limit_up(close, prev_close, limit_pct):
    if prev_close is None or prev_close <= 0: return False
    limit_price = round(prev_close * (1 + limit_pct), 2)
    return close >= limit_price - 0.005

# Build price DB
price_db = {}
all_klines_map = {}
for name, code in stocks_map.items():
    if name not in stock_data: continue
    all_klines_map[name] = stock_data[name]
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

# ================================================================
# IMPROVED: Analyze what predicts MULTI-BOARD (sustained limit-up)
# ================================================================
# For each T-1 limit-up stock on each day, track how many MORE
# consecutive limit-ups it has starting from the buy day

out_path = r'C:\Users\Davis\Desktop\主升浪\optimized_model_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*100 + "\n")
    f.write("多板预测因子分析 + 优化模型回测\n")
    f.write("="*100 + "\n\n")

    # Build a dataset: for every stock-day where T-1 was limit-up AND
    # the trader was active (record != '休息'), what happened next?
    f.write("1. 多板预测因子分析\n")
    f.write("-"*60 + "\n")

    multi_board_data = []
    for date in all_trade_dates:
        record = dict(timeline).get(date, '休息')
        if record == '休息': continue

        for name in price_db:
            if name not in stock_data: continue
            klines = stock_data[name]
            date_indices = [i for i, k in enumerate(klines) if k['day'] == date]
            if not date_indices or date_indices[0] < 1: continue
            idx = date_indices[0]

            prev_date = klines[idx - 1]['day']
            if prev_date not in price_db[name]: continue
            t1 = price_db[name][prev_date]
            if not t1['is_limit_up']: continue  # Only T-1 limit-up stocks

            # Count how many consecutive limit-ups starting from buy day
            future_lu = 0
            for j in range(idx, min(idx + 10, len(klines))):
                check_date = klines[j]['day']
                if check_date in price_db[name] and price_db[name][check_date]['is_limit_up']:
                    future_lu += 1
                else:
                    break

            buy_info = price_db[name][date]
            t2_is_lu = False
            if idx >= 2:
                t2_date = klines[idx - 2]['day']
                if t2_date in price_db[name]:
                    t2_is_lu = price_db[name][t2_date]['is_limit_up']

            dow = datetime.strptime(date, '%Y-%m-%d').weekday()
            is_monday = (dow == 0)

            multi_board_data.append({
                'name': name, 'date': date,
                'future_lu': future_lu,
                't1_vol20': t1['vol_ratio20'],
                't1_gap': t1['gap_open_pct'],
                't1_cons': t1['cons_lu_before'],
                't1_one_line': t1.get('is_one_line', False),
                't1_seal': t1['seal_quality'],
                'buy_gap': buy_info['gap_open_pct'],
                't2_is_lu': t2_is_lu,
                'is_monday': is_monday,
            })

    f.write(f"总样本: T-1涨停 + 交易员有操作的天 = {len(multi_board_data)}个候选\n\n")

    # Group by future_lu count
    f.write("未来连板数分布:\n")
    lu_dist = Counter(d['future_lu'] for d in multi_board_data)
    for k in sorted(lu_dist.keys()):
        f.write(f"  {k}板(含当日): {lu_dist[k]}个\n")

    # What factors correlate with multi-board (>=2 future boards)?
    f.write("\n多板(>=2连板) vs 单板(0-1板) 因子对比:\n")
    f.write(f"{'因子':<30} {'多板组(>=2)':>15} {'单板组(<=1)':>15} {'差异':>10}\n")
    f.write("-"*75 + "\n")

    multi = [d for d in multi_board_data if d['future_lu'] >= 2]
    single = [d for d in multi_board_data if d['future_lu'] <= 1]

    comparisons = [
        ('样本数', lambda g: len(g), lambda v: str(v)),
        ('T-1量比(均值)', lambda g: sum(d['t1_vol20'] for d in g)/len(g), lambda v: f"{v:.2f}x"),
        ('T-1量比<1x占比', lambda g: sum(1 for d in g if d['t1_vol20'] < 1.0)/len(g)*100, lambda v: f"{v:.0f}%"),
        ('T-1开盘涨幅(均值)', lambda g: sum(d['t1_gap'] for d in g)/len(g), lambda v: f"{v:.1f}%"),
        ('T-1一字板占比', lambda g: sum(1 for d in g if d['t1_one_line'])/len(g)*100, lambda v: f"{v:.0f}%"),
        ('T-1连板数(均值)', lambda g: sum(d['t1_cons'] for d in g)/len(g), lambda v: f"{v:.1f}"),
        ('T-2涨停占比', lambda g: sum(1 for d in g if d['t2_is_lu'])/len(g)*100, lambda v: f"{v:.0f}%"),
        ('周一占比', lambda g: sum(1 for d in g if d['is_monday'])/len(g)*100, lambda v: f"{v:.0f}%"),
        ('买入日高开>5%占比', lambda g: sum(1 for d in g if d['buy_gap'] > 5)/len(g)*100, lambda v: f"{v:.0f}%"),
    ]

    for name, fn, fmt in comparisons:
        m_val = fmt(fn(multi))
        s_val = fmt(fn(single))
        f.write(f"{name:<30} {m_val:>15} {s_val:>15}\n")

    # ================================================================
    # NEW SCORING V2 — optimized for multi-board prediction
    # ================================================================
    f.write("\n\n2. 优化评分模型 V2 (多板导向)\n")
    f.write("-"*60 + "\n")

    def score_v2(name, date, price_db, stock_data):
        """V2 scoring — tuned to predict multi-board sustainability"""
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
        t3_is_lu = False
        if idx >= 2:
            t2_d = klines[idx - 2]['day']
            if t2_d in price_db[name]: t2_is_lu = price_db[name][t2_d]['is_limit_up']
        if idx >= 3:
            t3_d = klines[idx - 3]['day']
            if t3_d in price_db[name]: t3_is_lu = price_db[name][t3_d]['is_limit_up']

        score = 0.0

        # === Factor 1: Extreme volume contraction (strongest signal) ===
        vol20 = t1['vol_ratio20']
        if vol20 < 0.3: score += 35
        elif vol20 < 0.5: score += 28
        elif vol20 < 0.7: score += 22
        elif vol20 < 1.0: score += 16
        elif vol20 < 1.5: score += 8
        elif vol20 < 2.0: score += 2
        elif vol20 < 3.0: score -= 3
        elif vol20 < 5.0: score -= 10
        else: score -= 18  # heavy penalty for extreme volume

        # === Factor 2: Board strength (higher gap = stronger control) ===
        gap = t1['gap_open_pct']
        if gap >= 9.5: score += 22
        elif gap >= 8: score += 18
        elif gap >= 5: score += 13
        elif gap >= 3: score += 7
        elif gap >= 1: score += 2
        elif gap >= 0: score += 0
        else: score -= 12

        # === Factor 3: One-line board (ultimate strength signal) ===
        if t1.get('is_one_line', False): score += 12

        # === Factor 4: Consecutive board count (2nd-3rd board = sweet spot) ===
        cons = t1['cons_lu_before']
        if cons == 0: score += 3    # first board
        elif cons == 1: score += 10  # second board (sweet spot)
        elif cons == 2: score += 12  # third board (still good)
        elif cons == 3: score += 8   # fourth board
        elif cons >= 4: score += 4   # diminishing returns

        # === Factor 5: Monday effect (strong) ===
        dow = datetime.strptime(date, '%Y-%m-%d').weekday()
        if dow == 0: score += 18  # Monday
        elif dow == 4: score -= 5  # Friday

        # === Factor 6: T-2/T-3 consecutive confirmation ===
        if t2_is_lu and t3_is_lu: score += 12   # 3 consecutive boards
        elif t2_is_lu: score += 6                # at least 2

        # === Factor 7: Buy-day strength ===
        buy_gap = buy_info['gap_open_pct']
        if buy_gap > 8: score += 8
        elif buy_gap > 5: score += 5
        elif buy_gap > 2: score += 2
        elif buy_gap > 0: score += 0
        elif buy_gap > -2: score -= 5
        else: score -= 25  # strong penalty for negative open

        # === Factor 8: Seal quality (close at high = strong close) ===
        seal = t1['seal_quality']
        if seal >= 0.99: score += 6
        elif seal >= 0.95: score += 3
        elif seal < 0.85: score -= 10

        return score

    def get_candidates_v2(date, price_db, stock_data, top_n=10):
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
                    't1_vol20': t1['vol_ratio20'],
                    't1_gap': t1['gap_open_pct'],
                    't1_cons': t1['cons_lu_before'],
                    't1_one_line': t1.get('is_one_line', False),
                    'buy_open': price_db[name][date]['open'],
                })
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:top_n]

    # ================================================================
    # BACKTEST V2
    # ================================================================
    def simulate_v2(pick_fn):
        positions = []
        cash = INITIAL_CAPITAL
        daily_log = []
        for date_idx, date in enumerate(all_trade_dates):
            record = dict(timeline).get(date, '休息')
            prev_date = all_trade_dates[date_idx - 1] if date_idx > 0 else None

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

            stock_bought = None
            if record != '休息' and len(positions) == 0:
                candidates = get_candidates_v2(date, price_db, stock_data, top_n=10)
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

            pv = sum(pos['shares'] * price_db.get(pos['name'], {}).get(date, {}).get('close', 0) for pos in positions)
            daily_log.append({'date': date, 'held': [(p['name'], p['buy_date']) for p in positions],
                             'cash': cash, 'total': cash + pv, 'bought': stock_bought})
        return daily_log

    # --- V2 Model: Pick #1 ---
    log_v2 = simulate_v2(lambda d, c: c[0]['name'] if c else None)
    final_v2 = log_v2[-1]['total']
    ret_v2 = (final_v2 - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    f.write(f"V2评分模型 #1候选: {final_v2:,.0f} ({ret_v2:+.1f}%)\n")

    # --- V2 Model: Pick from top 3, choose the one with lowest volume ---
    def pick_lowest_vol(date, candidates):
        if not candidates: return None
        top3 = candidates[:3]
        top3.sort(key=lambda x: x['t1_vol20'])  # lowest vol first
        return top3[0]['name']

    log_v2_lowvol = simulate_v2(pick_lowest_vol)
    final_lowvol = log_v2_lowvol[-1]['total']
    ret_lowvol = (final_lowvol - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    f.write(f"V2评分 Top3中选量最小: {final_lowvol:,.0f} ({ret_lowvol:+.1f}%)\n")

    # --- V2 with hard filter: only buy if score > threshold ---
    def pick_high_score(date, candidates):
        if not candidates: return None
        if candidates[0]['score'] >= 80:
            return candidates[0]['name']
        return None  # Skip if not confident

    log_v2_filtered = simulate_v2(pick_high_score)
    final_filtered = log_v2_filtered[-1]['total']
    ret_filtered = (final_filtered - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    f.write(f"V2评分 仅选>=80分: {final_filtered:,.0f} ({ret_filtered:+.1f}%)\n")

    # --- Detailed V2 picks ---
    f.write("\n\nV2模型每日选股(#1)详情:\n")
    f.write(f"{'日期':<12} {'标的':<10} {'V2评分':>6} {'量比':>6} {'T-1gap':>7} {'连板':>4} {'一字':>4} {'结果':>8}\n")
    f.write("-"*68 + "\n")

    v2_wins = 0; v2_count = 0
    for log in log_v2:
        if log['bought']:
            v2_count += 1
            name = log['bought']['name']
            date = log['date']
            if name in price_db and date in price_db[name]:
                is_lu = price_db[name][date]['is_limit_up']
                chg = price_db[name][date]['change_pct']
            else:
                is_lu = False; chg = 0
            if is_lu: v2_wins += 1

            cands = get_candidates_v2(date, price_db, stock_data, top_n=3)
            c0 = cands[0] if cands else {}
            f.write(f"{date:<12} {name:<10} {c0.get('score',0):>6.0f} "
                    f"{c0.get('t1_vol20',0):>5.1f}x {c0.get('t1_gap',0):>+6.1f}% "
                    f"{c0.get('t1_cons',0):>4} {'是' if c0.get('t1_one_line') else '否':>4} "
                    f"{'✓涨停' if is_lu else f'{chg:+.1f}%':>8}\n")

    f.write(f"\nV2胜率: {v2_wins}/{v2_count} ({v2_wins/v2_count*100:.0f}%)\n")

    # ================================================================
    # FINAL COMPARISON
    # ================================================================
    f.write("\n\n3. 最终模型对比总表\n")
    f.write("-"*70 + "\n")
    f.write(f"{'模型':<35} {'最终资产':>12} {'收益率':>10} {'vs交易员':>12}\n")
    f.write("-"*70 + "\n")

    # Re-run trader baseline
    def pick_trader(date, candidates):
        return dict(timeline).get(date, None)
    trader_log = simulate_v2(pick_trader)
    trader_final = trader_log[-1]['total']

    models = [
        ('交易员实际', trader_final),
        ('V1纯评分(原模型)', 1906933),  # from previous run
        ('V2多板导向评分', final_v2),
        ('V2+Top3选最低量', final_lowvol),
        ('V2+仅选>=80分', final_filtered),
    ]
    for name, final in models:
        ret = (final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        vs = final - trader_final
        f.write(f"{name:<35} {final:>12,.0f} {ret:>+9.1f}% {vs:>+12,.0f}\n")

    # ================================================================
    # TOP 3 SHOWCASE for last few days
    # ================================================================
    f.write("\n\n4. 最近5个交易日 前三候选展示\n")
    f.write("-"*70 + "\n")

    for date in all_trade_dates[-5:]:
        record = dict(timeline).get(date, '休息')
        if record == '休息': continue
        top3 = get_candidates_v2(date, price_db, stock_data, top_n=3)
        f.write(f"\n{date} | 交易员选: {record}\n")
        for r, c in enumerate(top3):
            mark = " ←" if c['name'] == record else ""
            f.write(f"  #{r+1} {c['name']:<10} 评分{c['score']:.0f} "
                    f"量比{c['t1_vol20']:.1f}x gap{c['t1_gap']:+.1f}% "
                    f"连板{c['t1_cons']}{mark}\n")

print(f"Optimized model complete! Output: {out_path}")
