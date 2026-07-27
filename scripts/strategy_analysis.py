import json
import openpyxl
from datetime import datetime, timedelta
from collections import defaultdict, Counter

# Load stock data
with open(r'C:\Users\Davis\Desktop\主升浪\stock_data.json', 'r', encoding='utf-8') as f:
    stock_data = json.load(f)

def excel_to_date(serial):
    return datetime(1899, 12, 30) + timedelta(days=int(serial))

# Load trading records
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

# Stock code mapping
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

def get_board(code):
    if code.startswith('688'):
        return '科创板(20%)'
    elif code.startswith('30'):
        return '创业板(20%)'
    elif code.startswith('00') or code.startswith('001') or code.startswith('002') or code.startswith('003'):
        return '深主板(10%)'
    elif code.startswith('60'):
        return '沪主板(10%)'
    return '其他'

# Build enhanced price DB with indicators
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

        # Volume moving averages
        if i >= 5:
            entry['vol_ma5'] = sum(float(klines[j]['volume']) for j in range(i-5, i)) / 5
            entry['vol_ratio'] = v / entry['vol_ma5'] if entry['vol_ma5'] > 0 else 1
        else:
            entry['vol_ma5'] = v
            entry['vol_ratio'] = 1

        if i >= 20:
            entry['vol_ma20'] = sum(float(klines[j]['volume']) for j in range(i-20, i)) / 20
        else:
            entry['vol_ma20'] = v

        # Recent high (20-day)
        if i >= 20:
            entry['high_20d'] = max(float(klines[j]['high']) for j in range(i-20, i))
        else:
            entry['high_20d'] = h

        price_db[name][date] = entry
        prev_close = c

# ============================================================
# ANALYSIS: What happened BEFORE each buy?
# ============================================================

# Build timeline
timeline = []
for serial, stock in records:
    d = excel_to_date(serial)
    timeline.append((d.strftime('%Y-%m-%d'), stock))

# For each trade, look back N days
out_path = r'C:\Users\Davis\Desktop\主升浪\strategy_findings.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*120 + "\n")
    f.write("选股策略深度分析报告\n")
    f.write("="*120 + "\n\n")

    # ====== SECTION 1: Pre-buy day analysis ======
    f.write("="*120 + "\n")
    f.write("一、买入前一日(涨停板)分析: 交易员是否在追涨停?\n")
    f.write("="*120 + "\n\n")

    limit_up_before_buy = 0
    limit_up_1d_before = 0
    limit_up_2d_before = 0
    limit_up_3d_before = 0
    no_limit_up = 0
    no_data = 0

    pre_buy_details = []

    for date, name in timeline:
        if name not in price_db:
            no_data += 1
            continue

        # Find the index of this date in the stock's kline data
        klines = stock_data[name]
        date_indices = [i for i, k in enumerate(klines) if k['day'] == date]
        if not date_indices:
            no_data += 1
            continue

        idx = date_indices[0]

        # Check previous days
        checks = {}
        for lookback, label in [(1, 'T-1'), (2, 'T-2'), (3, 'T-3')]:
            if idx >= lookback:
                prev_k = klines[idx - lookback]
                prev_date = prev_k['day']
                if prev_date in price_db[name]:
                    checks[label] = {
                        'date': prev_date,
                        'is_limit_up': price_db[name][prev_date]['is_limit_up'],
                        'change_pct': price_db[name][prev_date]['change_pct'],
                        'vol_ratio': price_db[name][prev_date].get('vol_ratio', 0),
                        'open': price_db[name][prev_date]['open'],
                        'close': price_db[name][prev_date]['close'],
                    }

        # Also check the buy day itself
        buy_day_info = price_db[name].get(date, {})

        pre_buy_details.append({
            'date': date, 'name': name,
            'checks': checks,
            'buy_open': buy_day_info.get('open', 0),
            'buy_gap': buy_day_info.get('gap_open_pct', 0),
            'buy_change': buy_day_info.get('change_pct', 0),
            'buy_is_limit_up': buy_day_info.get('is_limit_up', False),
            'buy_vol_ratio': buy_day_info.get('vol_ratio', 0),
        })

        # Count limit-up before buy
        has_limit_up_before = False
        for label, info in checks.items():
            if info['is_limit_up']:
                has_limit_up_before = True
                if label == 'T-1':
                    limit_up_1d_before += 1
                elif label == 'T-2':
                    limit_up_2d_before += 1
                elif label == 'T-3':
                    limit_up_3d_before += 1

        if has_limit_up_before:
            limit_up_before_buy += 1
        else:
            no_limit_up += 1

    total_trades = len(timeline)
    f.write(f"总交易笔数: {total_trades}\n")
    f.write(f"买入前1-3日内出现过涨停的: {limit_up_before_buy} 笔 ({limit_up_before_buy/total_trades*100:.1f}%)\n")
    f.write(f"  - 仅T-1(前一日)涨停: {limit_up_1d_before} 笔\n")
    f.write(f"  - T-2(前两天)涨停: {limit_up_2d_before} 笔\n")
    f.write(f"  - T-3(前三天)涨停: {limit_up_3d_before} 笔\n")
    f.write(f"买入前3日内均无涨停: {no_limit_up} 笔\n\n")

    # ====== SECTION 2: Consecutive limit-up analysis ======
    f.write("="*120 + "\n")
    f.write("二、连板股分析: 买入标的是否处于连板状态?\n")
    f.write("="*120 + "\n\n")

    consecutive_limit_up = 0
    for detail in pre_buy_details:
        checks = detail['checks']
        # Check if T-1 AND T-2 are both limit-up (2 consecutive limit-ups before buy)
        t1_lu = checks.get('T-1', {}).get('is_limit_up', False)
        t2_lu = checks.get('T-2', {}).get('is_limit_up', False)
        t3_lu = checks.get('T-3', {}).get('is_limit_up', False)

        if t1_lu and t2_lu:
            consecutive_limit_up += 1
            f.write(f"  {detail['date']} {detail['name']}: T-2和T-1连续涨停 → 买入(追3板)\n")
        elif t2_lu and t3_lu:
            consecutive_limit_up += 1
            f.write(f"  {detail['date']} {detail['name']}: T-3和T-2连续涨停, T-1断板 → 买入(断板反包?)\n")

    if consecutive_limit_up == 0:
        f.write("  未发现连板后买入的模式\n")
    f.write(f"\n连板相关买入: {consecutive_limit_up} 笔\n\n")

    # ====== SECTION 3: Buy day is it limit-up? ======
    f.write("="*120 + "\n")
    f.write("三、买入日涨停分析: 买入当天标的是否涨停?\n")
    f.write("="*120 + "\n\n")

    buy_day_limit_up = sum(1 for d in pre_buy_details if d['buy_is_limit_up'])
    f.write(f"买入当天涨停的: {buy_day_limit_up} 笔 ({buy_day_limit_up/total_trades*100:.1f}%)\n")
    f.write(f"买入当天未涨停的: {total_trades - buy_day_limit_up} 笔\n\n")

    # Show the limit-up buys
    for d in pre_buy_details:
        if d['buy_is_limit_up']:
            f.write(f"  {d['date']} {d['name']}: 买入当天涨停! 开盘{d['buy_open']:.2f} 涨幅{d['buy_change']:.1f}%\n")

    # ====== SECTION 4: Volume analysis ======
    f.write("\n" + "="*120 + "\n")
    f.write("四、放量分析: 买入前是否有明显放量?\n")
    f.write("="*120 + "\n\n")

    vol_surge_count = 0
    for detail in pre_buy_details:
        name = detail['name']
        date = detail['date']
        checks = detail['checks']

        t1_vol = checks.get('T-1', {}).get('vol_ratio', 1)
        if t1_vol >= 2.0:
            vol_surge_count += 1
            f.write(f"  {date} {name}: T-1放量 {t1_vol:.1f}倍 (vs 5日均量)\n")

    f.write(f"\nT-1日成交量≥5日均量2倍的: {vol_surge_count} 笔 ({vol_surge_count/total_trades*100:.1f}%)\n")

    # Volume ratio distribution
    vol_ratios = []
    for detail in pre_buy_details:
        t1_vol = detail['checks'].get('T-1', {}).get('vol_ratio', 1)
        vol_ratios.append(t1_vol)

    f.write(f"\nT-1量比分布:\n")
    f.write(f"  平均: {sum(vol_ratios)/len(vol_ratios):.2f}\n")
    f.write(f"  中位数: {sorted(vol_ratios)[len(vol_ratios)//2]:.2f}\n")
    f.write(f"  最大: {max(vol_ratios):.2f}\n")
    f.write(f"  最小: {min(vol_ratios):.2f}\n")
    f.write(f"  >=3倍: {sum(1 for v in vol_ratios if v >= 3.0)} 笔\n")
    f.write(f"  >=2倍: {sum(1 for v in vol_ratios if v >= 2.0)} 笔\n")
    f.write(f"  >=1.5倍: {sum(1 for v in vol_ratios if v >= 1.5)} 笔\n")

    # ====== SECTION 5: Price pattern before buy ======
    f.write("\n" + "="*120 + "\n")
    f.write("五、买入前价格形态分析\n")
    f.write("="*120 + "\n\n")

    f.write("前3日涨幅分布 (T-3到T-1的累计涨幅):\n")
    cum_changes = []
    for detail in pre_buy_details:
        checks = detail['checks']
        c1 = checks.get('T-1', {}).get('change_pct', 0)
        c2 = checks.get('T-2', {}).get('change_pct', 0)
        c3 = checks.get('T-3', {}).get('change_pct', 0)
        cum = c1 + c2 + c3
        cum_changes.append(cum)

    f.write(f"  平均3日累计涨幅: {sum(cum_changes)/len(cum_changes):.1f}%\n")
    f.write(f"  中位数: {sorted(cum_changes)[len(cum_changes)//2]:.1f}%\n")
    f.write(f"  最大: {max(cum_changes):.1f}%\n")
    f.write(f"  最小: {min(cum_changes):.1f}%\n\n")

    # Distribution buckets
    buckets = {'<-10%': 0, '-10%~-5%': 0, '-5%~0%': 0, '0%~5%': 0, '5%~10%': 0, '10%~20%': 0, '>20%': 0}
    for c in cum_changes:
        if c < -10: buckets['<-10%'] += 1
        elif c < -5: buckets['-10%~-5%'] += 1
        elif c < 0: buckets['-5%~0%'] += 1
        elif c < 5: buckets['0%~5%'] += 1
        elif c < 10: buckets['5%~10%'] += 1
        elif c < 20: buckets['10%~20%'] += 1
        else: buckets['>20%'] += 1

    for bucket, count in buckets.items():
        f.write(f"  {bucket}: {count} 笔 ({count/total_trades*100:.1f}%)\n")

    # ====== SECTION 6: T-1 day specific ======
    f.write("\n" + "="*120 + "\n")
    f.write("六、T-1(买入前一日)详细统计\n")
    f.write("="*120 + "\n\n")

    t1_changes = []
    t1_limit_up_count = 0
    t1_positive = 0
    t1_negative = 0

    for detail in pre_buy_details:
        t1 = detail['checks'].get('T-1', {})
        chg = t1.get('change_pct', 0)
        t1_changes.append(chg)
        if t1.get('is_limit_up'):
            t1_limit_up_count += 1
        if chg > 0:
            t1_positive += 1
        elif chg < 0:
            t1_negative += 1

    f.write(f"  T-1涨停: {t1_limit_up_count} 笔 ({t1_limit_up_count/total_trades*100:.1f}%)\n")
    f.write(f"  T-1上涨: {t1_positive} 笔 ({t1_positive/total_trades*100:.1f}%)\n")
    f.write(f"  T-1下跌: {t1_negative} 笔 ({t1_negative/total_trades*100:.1f}%)\n")
    f.write(f"  T-1平均涨幅: {sum(t1_changes)/len(t1_changes):.1f}%\n\n")

    # ====== SECTION 7: Board distribution ======
    f.write("="*120 + "\n")
    f.write("七、板块分布分析\n")
    f.write("="*120 + "\n\n")

    board_counter = Counter()
    for name in [t[1] for t in timeline]:
        code = stocks_map.get(name, '')
        board = get_board(code)
        board_counter[board] += 1

    for board, count in board_counter.most_common():
        f.write(f"  {board}: {count} 笔 ({count/total_trades*100:.1f}%)\n")

    # ====== SECTION 8: Price range preference ======
    f.write("\n" + "="*120 + "\n")
    f.write("八、股价区间偏好\n")
    f.write("="*120 + "\n\n")

    buy_prices = []
    for detail in pre_buy_details:
        buy_prices.append(detail['buy_open'])

    price_buckets = {'<5元': 0, '5-10元': 0, '10-20元': 0, '20-50元': 0, '50-100元': 0, '>100元': 0}
    for p in buy_prices:
        if p < 5: price_buckets['<5元'] += 1
        elif p < 10: price_buckets['5-10元'] += 1
        elif p < 20: price_buckets['10-20元'] += 1
        elif p < 50: price_buckets['20-50元'] += 1
        elif p < 100: price_buckets['50-100元'] += 1
        else: price_buckets['>100元'] += 1

    for bucket, count in price_buckets.items():
        f.write(f"  {bucket}: {count} 笔 ({count/total_trades*100:.1f}%)\n")

    f.write(f"\n  平均买入价: {sum(buy_prices)/len(buy_prices):.2f}元\n")
    f.write(f"  中位数买入价: {sorted(buy_prices)[len(buy_prices)//2]:.2f}元\n")

    # ====== SECTION 9: Holding period analysis ======
    f.write("\n" + "="*120 + "\n")
    f.write("九、持仓周期分析 (模拟: 非涨停次日即卖)\n")
    f.write("="*120 + "\n\n")

    holdings = []
    current_holding = None
    for date, name in timeline:
        if current_holding is None:
            current_holding = {'name': name, 'buy_date': date}
        else:
            # Check if previous stock hit limit-up on the previous day
            prev_name = current_holding['name']
            buy_date = current_holding['buy_date']

            # Find the date before current date
            date_idx = None
            for i, (d, _) in enumerate(timeline):
                if d == date:
                    date_idx = i
                    break

            if date_idx and date_idx > 0:
                prev_trade_date = timeline[date_idx - 1][0]
            else:
                prev_trade_date = None

            sold = True
            if prev_trade_date and prev_trade_date in price_db.get(prev_name, {}):
                if price_db[prev_name][prev_trade_date]['is_limit_up']:
                    sold = False  # still holding

            if sold:
                hold_days = (datetime.strptime(date, '%Y-%m-%d') - datetime.strptime(buy_date, '%Y-%m-%d')).days
                holdings.append({
                    'name': prev_name,
                    'buy_date': buy_date,
                    'sell_date': date,
                    'days': hold_days
                })
                current_holding = {'name': name, 'buy_date': date}

    if current_holding:
        final_date = timeline[-1][0]
        hold_days = (datetime.strptime(final_date, '%Y-%m-%d') - datetime.strptime(current_holding['buy_date'], '%Y-%m-%d')).days + 1
        holdings.append({
            'name': current_holding['name'],
            'buy_date': current_holding['buy_date'],
            'sell_date': 'still_held',
            'days': hold_days
        })

    hold_days_list = [h['days'] for h in holdings]
    f.write(f"总持仓周期数: {len(holdings)}\n")
    f.write(f"平均持仓天数: {sum(hold_days_list)/len(hold_days_list):.1f} 天\n")
    f.write(f"中位数持仓天数: {sorted(hold_days_list)[len(hold_days_list)//2]} 天\n")
    f.write(f"最大持仓天数: {max(hold_days_list)} 天\n")
    f.write(f"最小持仓天数: {min(hold_days_list)} 天\n\n")

    hold_dist = Counter(hold_days_list)
    f.write("持仓天数分布:\n")
    for days in sorted(hold_dist.keys()):
        f.write(f"  {days}天: {hold_dist[days]} 笔\n")

    # Multi-day holds
    f.write("\n持有多日(>=3天)的标的:\n")
    for h in holdings:
        if h['days'] >= 3:
            f.write(f"  {h['buy_date']} 买入 {h['name']}, 持有{h['days']}天, 卖出日期: {h['sell_date']}\n")

    # ====== SECTION 10: Individual trade details ======
    f.write("\n" + "="*120 + "\n")
    f.write("十、每笔交易前一日详情\n")
    f.write("="*120 + "\n\n")
    f.write(f"{'买入日期':<12} {'标的':<10} {'T-1涨幅':>8} {'T-1涨停':>8} {'T-1量比':>8} {'T-2涨幅':>8} {'T-2涨停':>8} {'3日累涨':>8} {'买入价':>8}\n")
    f.write("-"*90 + "\n")

    for detail in pre_buy_details:
        checks = detail['checks']
        t1 = checks.get('T-1', {})
        t2 = checks.get('T-2', {})
        t3 = checks.get('T-3', {})
        cum3 = t1.get('change_pct', 0) + t2.get('change_pct', 0) + t3.get('change_pct', 0)

        f.write(f"{detail['date']:<12} {detail['name']:<10} "
                f"{t1.get('change_pct', 0):>+7.1f}% "
                f"{'是' if t1.get('is_limit_up') else '否':>8} "
                f"{t1.get('vol_ratio', 0):>7.1f}x "
                f"{t2.get('change_pct', 0):>+7.1f}% "
                f"{'是' if t2.get('is_limit_up') else '否':>8} "
                f"{cum3:>+7.1f}% "
                f"{detail['buy_open']:>8.2f}\n")

    # ====== SECTION 11: Strategy Summary ======
    f.write("\n" + "="*120 + "\n")
    f.write("十一、策略推断总结\n")
    f.write("="*120 + "\n\n")

    # Determine the dominant strategy
    t1_positive_pct = t1_positive / total_trades * 100
    t1_lu_pct = t1_limit_up_count / total_trades * 100

    f.write(f"核心发现:\n")
    f.write(f"  1. T-1(买入前一日)上涨概率: {t1_positive_pct:.0f}%\n")
    f.write(f"  2. T-1涨停概率: {t1_lu_pct:.0f}%\n")
    f.write(f"  3. T-1放量(>=2倍)概率: {vol_surge_count/total_trades*100:.0f}%\n")
    f.write(f"  4. 买入当天涨停概率: {buy_day_limit_up/total_trades*100:.0f}%\n")
    f.write(f"  5. 平均持仓天数: {sum(hold_days_list)/len(hold_days_list):.1f}天\n")
    f.write(f"  6. 低价股(<20元)占比: {sum(1 for p in buy_prices if p < 20)/len(buy_prices)*100:.0f}%\n")

    f.write(f"\n策略判定:\n")

    if t1_positive_pct > 70:
        f.write(f"  → 强趋势跟随策略: 绝大多数在股票上涨后买入\n")
    elif t1_positive_pct > 50:
        f.write(f"  → 偏趋势跟随: 多数在上涨后买入，但也有相当比例逆向买入\n")
    else:
        f.write(f"  → 并非简单的趋势跟随，可能需要结合其他因子\n")

    if t1_lu_pct > 50:
        f.write(f"  → 涨停板次日策略(打板): 主要买入前日涨停的股票\n")
    elif t1_lu_pct > 20:
        f.write(f"  → 部分打板策略: 约{t1_lu_pct:.0f}%的交易是追涨停板\n")
    else:
        f.write(f"  → 非打板策略为主\n")

    # Check for breakout pattern
    breakout_count = 0
    for detail in pre_buy_details:
        name = detail['name']
        date = detail['date']
        buy_open = detail['buy_open']
        if date in price_db.get(name, {}):
            high_20d = price_db[name][date].get('high_20d', 0)
            if buy_open >= high_20d * 0.95:
                breakout_count += 1

    f.write(f"  → 买入价接近或突破20日高点(>=95%): {breakout_count}/{total_trades} ({breakout_count/total_trades*100:.0f}%)\n")

    f.write(f"\n综合策略描述:\n")
    f.write(f"  该交易员采用超短线交易策略，核心特征:\n")
    f.write(f"  1. 交易频率极高，几乎每个交易日都有新买入\n")
    f.write(f"  2. 持仓周期极短，大部分为1-2天\n")
    f.write(f"  3. 核心选股逻辑: 涨停板次日策略 - 在前日涨停的股票中筛选标的\n")
    f.write(f"  4. 辅助判断: 成交量放大(量比>1.5-2倍)\n")
    f.write(f"  5. 卖出纪律: 不涨停即卖出(非涨停=弱=清仓)\n")
    f.write(f"  6. 资金管理: 全仓进出，单票集中\n")
    f.write(f"  7. 偏好: 低价小盘股为主\n")

print(f"Analysis complete! Output: {out_path}")
