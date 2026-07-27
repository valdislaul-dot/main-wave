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
    if prev_close is None or prev_close <= 0:
        return False
    limit_price = round(prev_close * (1 + limit_pct), 2)
    return close >= limit_price - 0.005

# Build price DB with more indicators
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
            'high_low_pct': 0,  # intraday range
        }
        if prev_close is not None and prev_close > 0:
            entry['is_limit_up'] = is_limit_up(c, prev_close, limit_pct)
            entry['change_pct'] = (c - prev_close) / prev_close * 100
            entry['gap_open_pct'] = (o - prev_close) / prev_close * 100
        if h > 0 and l > 0:
            entry['high_low_pct'] = (h - l) / l * 100

        # Volume MAs
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

        price_db[name][date] = entry
        prev_close = c

# Build timeline
timeline = []
for serial, stock in records:
    d = excel_to_date(serial)
    timeline.append((d.strftime('%Y-%m-%d'), stock))

# ================================================================
# DEEP ANALYSIS: Test multiple hypotheses about filtering criteria
# ================================================================
out_path = r'C:\Users\Davis\Desktop\主升浪\deep_strategy_analysis.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*120 + "\n")
    f.write("选股策略深度分析 V2 — 筛选条件推测与验证\n")
    f.write("="*120 + "\n\n")

    # First, build detailed trade-level data
    trades = []
    for date, name in timeline:
        if name not in price_db or name == '休息':
            continue
        if date not in price_db[name]:
            continue

        klines = stock_data[name]
        date_indices = [i for i, k in enumerate(klines) if k['day'] == date]
        if not date_indices:
            continue
        idx = date_indices[0]

        buy_info = price_db[name][date]

        # Collect pre-buy data for T-1 through T-5
        pre_days = {}
        for lookback in [1, 2, 3, 4, 5]:
            if idx >= lookback:
                prev_date = klines[idx - lookback]['day']
                if prev_date in price_db[name]:
                    pre_days[lookback] = price_db[name][prev_date]

        # Count consecutive limit-ups before buy
        cons_lu = 0
        for lb in [1, 2, 3, 4, 5]:
            if lb in pre_days and pre_days[lb]['is_limit_up']:
                cons_lu += 1
            else:
                break

        # Check if stock has had ANY limit-up in the past 10 days
        lu_in_10d = 0
        for lb in range(1, min(11, idx+1)):
            check_date = klines[idx - lb]['day']
            if check_date in price_db[name]:
                if price_db[name][check_date]['is_limit_up']:
                    lu_in_10d += 1

        t1 = pre_days.get(1, {})
        t2 = pre_days.get(2, {})

        trades.append({
            'date': date, 'name': name,
            'buy_open': buy_info['open'],
            'buy_close': buy_info['close'],
            'buy_change': buy_info['change_pct'],
            'buy_gap': buy_info['gap_open_pct'],
            'buy_is_lu': buy_info['is_limit_up'],
            'buy_vol_ratio5': buy_info['vol_ratio5'],
            'buy_vol_ratio20': buy_info['vol_ratio20'],
            'buy_is_20d_high': buy_info['is_20d_high'],
            't1_change': t1.get('change_pct', 0),
            't1_is_lu': t1.get('is_limit_up', False),
            't1_vol_ratio5': t1.get('vol_ratio5', 1),
            't1_vol_ratio20': t1.get('vol_ratio20', 1),
            't1_gap_open': t1.get('gap_open_pct', 0),
            't1_high_low': t1.get('high_low_pct', 0),
            't1_is_20d_high': t1.get('is_20d_high', False),
            't2_is_lu': t2.get('is_limit_up', False),
            't2_change': t2.get('change_pct', 0),
            'cons_lu': cons_lu,
            'lu_in_10d': lu_in_10d,
            'pre_days': pre_days,
        })

    total = len(trades)
    f.write(f"有效交易笔数: {total}\n\n")

    # ============================================================
    # HYPOTHESIS 1: T-1 MUST be limit-up (strong form)
    # The 29% non-limit-up T-1 cases need explanation
    # ============================================================
    f.write("="*120 + "\n")
    f.write("假设1: T-1必须涨停? 如果不是，那29%的例外有什么共同特征?\n")
    f.write("="*120 + "\n\n")

    t1_not_lu = [t for t in trades if not t['t1_is_lu']]
    t1_is_lu = [t for t in trades if t['t1_is_lu']]

    f.write(f"T-1涨停: {len(t1_is_lu)}笔, T-1非涨停: {len(t1_not_lu)}笔\n\n")

    # What do non-limit-up cases have in common?
    f.write("T-1非涨停的交易详情:\n")
    f.write(f"{'日期':<12} {'标的':<10} {'T-1涨幅':>8} {'T-2涨停':>8} {'T-2涨幅':>8} {'连板数':>6} {'10日板数':>8} {'买入日涨停':>10}\n")
    f.write("-"*85 + "\n")
    for t in t1_not_lu:
        f.write(f"{t['date']:<12} {t['name']:<10} {t['t1_change']:>+7.1f}% "
                f"{'是' if t['t2_is_lu'] else '否':>8} {t['t2_change']:>+7.1f}% "
                f"{t['cons_lu']:>6} {t['lu_in_10d']:>8} "
                f"{'是' if t['buy_is_lu'] else '否':>10}\n")

    # Key stats for non-lu group
    f.write(f"\nT-1非涨停组统计 (n={len(t1_not_lu)}):\n")
    f.write(f"  T-1平均涨幅: {sum(t['t1_change'] for t in t1_not_lu)/len(t1_not_lu):.1f}%\n")
    f.write(f"  T-2涨停比例: {sum(1 for t in t1_not_lu if t['t2_is_lu'])}/{len(t1_not_lu)}\n")
    f.write(f"  T-2平均涨幅: {sum(t['t2_change'] for t in t1_not_lu)/len(t1_not_lu):.1f}%\n")
    f.write(f"  10日内有涨停: {sum(1 for t in t1_not_lu if t['lu_in_10d'] > 1)}/{len(t1_not_lu)}\n")
    f.write(f"  买入日涨停: {sum(1 for t in t1_not_lu if t['buy_is_lu'])}/{len(t1_not_lu)}\n")

    # ============================================================
    # HYPOTHESIS 2: Gap-up filter — only buy if opening is strong
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设2: 开盘涨幅筛选 — 是否只买入高开的股票?\n")
    f.write("="*120 + "\n\n")

    gap_positive = [t for t in trades if t['buy_gap'] > 0]
    gap_negative = [t for t in trades if t['buy_gap'] <= 0]
    f.write(f"开盘高开(>0): {len(gap_positive)}笔 ({len(gap_positive)/total*100:.0f}%)\n")
    f.write(f"开盘平开/低开(<=0): {len(gap_negative)}笔 ({len(gap_negative)/total*100:.0f}%)\n")

    f.write(f"\n开盘涨幅分布:\n")
    gap_buckets = {'<0%':0, '0-2%':0, '2-5%':0, '5-8%':0, '8-10%':0, '>10%':0}
    for t in trades:
        g = t['buy_gap']
        if g < 0: gap_buckets['<0%'] += 1
        elif g < 2: gap_buckets['0-2%'] += 1
        elif g < 5: gap_buckets['2-5%'] += 1
        elif g < 8: gap_buckets['5-8%'] += 1
        elif g < 10: gap_buckets['8-10%'] += 1
        else: gap_buckets['>10%'] += 1
    for b, c in gap_buckets.items():
        f.write(f"  {b}: {c}笔 ({c/total*100:.0f}%)\n")

    f.write(f"\n低开买入的交易 (gap<=0):\n")
    for t in gap_negative:
        f.write(f"  {t['date']} {t['name']}: 开盘{t['buy_open']:.2f} gap={t['buy_gap']:.1f}% "
                f"T-1涨停={'是' if t['t1_is_lu'] else '否'} 当日涨停={'是' if t['buy_is_lu'] else '否'}\n")

    # ============================================================
    # HYPOTHESIS 3: Volume filter — T-1 must show significant volume expansion
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设3: 量能筛选 — T-1成交量必须显著放大?\n")
    f.write("="*120 + "\n\n")

    f.write("T-1量比(vs 5日均量)分布:\n")
    vol_buckets = {'<0.5x':0, '0.5-1x':0, '1-1.5x':0, '1.5-2x':0, '2-3x':0, '3-5x':0, '>5x':0}
    for t in trades:
        v = t['t1_vol_ratio5']
        if v < 0.5: vol_buckets['<0.5x'] += 1
        elif v < 1: vol_buckets['0.5-1x'] += 1
        elif v < 1.5: vol_buckets['1-1.5x'] += 1
        elif v < 2: vol_buckets['1.5-2x'] += 1
        elif v < 3: vol_buckets['2-3x'] += 1
        elif v < 5: vol_buckets['3-5x'] += 1
        else: vol_buckets['>5x'] += 1
    for b, c in vol_buckets.items():
        f.write(f"  {b}: {c}笔 ({c/total*100:.0f}%)\n")

    # Low volume trades
    low_vol = [t for t in trades if t['t1_vol_ratio5'] < 1.0]
    f.write(f"\nT-1缩量(<1x)仍买入的交易:\n")
    for t in low_vol:
        f.write(f"  {t['date']} {t['name']}: T-1量比{t['t1_vol_ratio5']:.1f}x "
                f"T-1涨停={'是' if t['t1_is_lu'] else '否'} 当日涨停={'是' if t['buy_is_lu'] else '否'}\n")

    # ============================================================
    # HYPOTHESIS 4: Breakout — stock breaking 20-day high?
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设4: 突破筛选 — T-1是否突破20日最高价?\n")
    f.write("="*120 + "\n\n")

    t1_breakout = [t for t in trades if t['t1_is_20d_high']]
    f.write(f"T-1突破20日高点: {len(t1_breakout)}笔 ({len(t1_breakout)/total*100:.0f}%)\n")
    f.write(f"T-1未突破20日高点: {total - len(t1_breakout)}笔\n")

    buy_breakout = [t for t in trades if t['buy_is_20d_high']]
    f.write(f"买入日突破20日高点: {len(buy_breakout)}笔 ({len(buy_breakout)/total*100:.0f}%)\n\n")

    # ============================================================
    # HYPOTHESIS 5: Consecutive limit-up count — avoid too many?
    # ============================================================
    f.write("="*120 + "\n")
    f.write("假设5: 连板数筛选 — 是否回避连板过多的股票?\n")
    f.write("="*120 + "\n\n")

    cons_dist = Counter(t['cons_lu'] for t in trades)
    f.write("T-1之前的连续涨停天数分布:\n")
    for days in sorted(cons_dist.keys()):
        these = [t for t in trades if t['cons_lu'] == days]
        lu_on_buy = sum(1 for t in these if t['buy_is_lu'])
        f.write(f"  {days}连板: {cons_dist[days]}笔 → 买入日涨停率: {lu_on_buy}/{len(these)} ({lu_on_buy/len(these)*100:.0f}%)\n")

    # ============================================================
    # HYPOTHESIS 6: First board vs continuation
    # Is the trader buying first-time limit-ups or continuation boards?
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设6: 首板 vs 连板偏好 — 更喜欢首板次日还是连板接力?\n")
    f.write("="*120 + "\n\n")

    first_board = [t for t in trades if t['cons_lu'] == 0]  # T-1 is first board
    second_board = [t for t in trades if t['cons_lu'] == 1]  # buying after 2nd board
    third_plus = [t for t in trades if t['cons_lu'] >= 2]    # buying after 3rd+ board

    f.write(f"首板次日买入 (cons=0): {len(first_board)}笔, 当日涨停率: {sum(1 for t in first_board if t['buy_is_lu'])}/{len(first_board)}\n")
    f.write(f"二板次日买入 (cons=1): {len(second_board)}笔, 当日涨停率: {sum(1 for t in second_board if t['buy_is_lu'])}/{len(second_board)}\n")
    f.write(f"三板+次日买入 (cons>=2): {len(third_plus)}笔, 当日涨停率: {sum(1 for t in third_plus if t['buy_is_lu'])}/{len(third_plus)}\n")

    # ============================================================
    # HYPOTHESIS 7: T-1 board quality — was it a strong board?
    # Measured by: gap open of T-1, intraday range, volume
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设7: T-1涨停质量筛选 — 强板(早盘封板) vs 弱板(尾盘封板)?\n")
    f.write("="*120 + "\n\n")
    f.write("以T-1开盘涨幅为代理指标(高开越多≈封板越早):\n\n")

    strong_board = [t for t in trades if t['t1_is_lu'] and t['t1_gap_open'] >= 5]
    weak_board = [t for t in trades if t['t1_is_lu'] and t['t1_gap_open'] < 2]

    f.write(f"T-1强板(开盘涨幅>=5%): {len(strong_board)}笔, 买入日涨停率: {sum(1 for t in strong_board if t['buy_is_lu'])}/{len(strong_board)} ({sum(1 for t in strong_board if t['buy_is_lu'])/max(len(strong_board),1)*100:.0f}%)\n")
    f.write(f"T-1弱板(开盘涨幅<2%): {len(weak_board)}笔, 买入日涨停率: {sum(1 for t in weak_board if t['buy_is_lu'])}/{len(weak_board)} ({sum(1 for t in weak_board if t['buy_is_lu'])/max(len(weak_board),1)*100:.0f}%)\n")

    # ============================================================
    # HYPOTHESIS 8: Open price relative to T-1 close
    # Does the trader require a gap-up from T-1 close?
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设8: T日开盘 vs T-1收盘 — 是否要求跳空高开?\n")
    f.write("="*120 + "\n\n")

    t1_close = []
    for t in trades:
        if 1 in t['pre_days']:
            t1_c = t['pre_days'][1]['close']
            gap_from_t1c = (t['buy_open'] - t1_c) / t1_c * 100 if t1_c > 0 else 0
            t1_close.append(gap_from_t1c)

    if t1_close:
        f.write(f"T日开盘价 vs T-1收盘价:\n")
        f.write(f"  平均gap: {sum(t1_close)/len(t1_close):.1f}%\n")
        f.write(f"  中位数: {sorted(t1_close)[len(t1_close)//2]:.1f}%\n")
        f.write(f"  正gap(跳空高开): {sum(1 for g in t1_close if g > 0)}笔 ({sum(1 for g in t1_close if g > 0)/len(t1_close)*100:.0f}%)\n")
        f.write(f"  负gap(低开): {sum(1 for g in t1_close if g < 0)}笔\n")

    # ============================================================
    # HYPOTHESIS 9: Day of week pattern
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设9: 周几效应 — 是否有特定的星期偏好?\n")
    f.write("="*120 + "\n\n")

    dow_map = {0:'周一',1:'周二',2:'周三',3:'周四',4:'周五',5:'周六',6:'周日'}
    dow_counter = Counter()
    dow_lu_counter = Counter()
    for t in trades:
        dt = datetime.strptime(t['date'], '%Y-%m-%d')
        dow = dow_map[dt.weekday()]
        dow_counter[dow] += 1
        if t['buy_is_lu']:
            dow_lu_counter[dow] += 1

    for dow in ['周一','周二','周三','周四','周五']:
        c = dow_counter.get(dow, 0)
        lu = dow_lu_counter.get(dow, 0)
        f.write(f"  {dow}: {c}笔, 涨停率: {lu}/{c} ({lu/c*100:.0f}%)\n" if c > 0 else f"  {dow}: 0笔\n")

    # ============================================================
    # HYPOTHESIS 10: "Rest" day pattern — why does trader rest?
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设10: 休息日规律 — 交易员为什么在某些交易日休息?\n")
    f.write("="*120 + "\n\n")

    rest_dates = []
    all_dates = sorted(set(d for d, _ in timeline))
    for i, (date, name) in enumerate(timeline):
        if name == '休息':
            # What was the previous trade?
            prev_trade = None
            for j in range(i-1, -1, -1):
                if timeline[j][1] != '休息':
                    prev_trade = timeline[j]
                    break
            rest_dates.append({'date': date, 'prev_trade': prev_trade})

    f.write("休息日及前一笔交易:\n")
    for r in rest_dates:
        prev_name = r['prev_trade'][1] if r['prev_trade'] else 'N/A'
        prev_date = r['prev_trade'][0] if r['prev_trade'] else 'N/A'

        # Check if prev stock hit limit-up on the day before rest
        prev_day_status = 'N/A'
        if prev_name in price_db:
            # Find the trading day before the rest date
            prev_trade_date_idx = all_dates.index(prev_date) if prev_date in all_dates else -1
            rest_date_idx = all_dates.index(r['date']) if r['date'] in all_dates else -1
            # The day between prev_trade_date and rest_date
            if prev_date in price_db.get(prev_name, {}):
                prev_day_status = f"涨幅{price_db[prev_name][prev_date]['change_pct']:.1f}%"
                if price_db[prev_name][prev_date]['is_limit_up']:
                    prev_day_status += ' 涨停'

        f.write(f"  {r['date']}: 前一笔={prev_name}({prev_date}), 状态={prev_day_status}\n")

    # ============================================================
    # HYPOTHESIS 11: What makes a WINNING trade?
    # Compare trades where buy-day hits limit-up vs not
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设11: 成功vs失败 — 买入日涨停的交易有什么不同?\n")
    f.write("="*120 + "\n\n")

    winners = [t for t in trades if t['buy_is_lu']]
    losers = [t for t in trades if not t['buy_is_lu']]

    f.write(f"成功(买入日涨停): {len(winners)}笔\n")
    f.write(f"失败(买入日未涨停): {len(losers)}笔\n\n")

    metrics = [
        ('T-1涨停比例', lambda t: t['t1_is_lu'], lambda v: f"{sum(1 for x in v if x)/len(v)*100:.0f}%"),
        ('T-1平均涨幅', lambda t: t['t1_change'], lambda v: f"{sum(v)/len(v):.1f}%"),
        ('T-1量比(均值)', lambda t: t['t1_vol_ratio5'], lambda v: f"{sum(v)/len(v):.1f}x"),
        ('T-1量比(中位数)', lambda t: t['t1_vol_ratio5'], lambda v: f"{sorted(v)[len(v)//2]:.1f}x"),
        ('T-2涨停比例', lambda t: t['t2_is_lu'], lambda v: f"{sum(1 for x in v if x)/len(v)*100:.0f}%"),
        ('连板数(均值)', lambda t: t['cons_lu'], lambda v: f"{sum(v)/len(v):.1f}"),
        ('开盘涨幅(均值)', lambda t: t['buy_gap'], lambda v: f"{sum(v)/len(v):.1f}%"),
        ('T-1突破20日高', lambda t: t['t1_is_20d_high'], lambda v: f"{sum(1 for x in v if x)/len(v)*100:.0f}%"),
        ('10日内涨停次数', lambda t: t['lu_in_10d'], lambda v: f"{sum(v)/len(v):.1f}"),
    ]

    f.write(f"{'指标':<25} {'成功组':>15} {'失败组':>15} {'差异':>15}\n")
    f.write("-"*70 + "\n")
    for name, fn, fmt in metrics:
        w_val = fmt([fn(t) for t in winners])
        l_val = fmt([fn(t) for t in losers])
        f.write(f"{name:<25} {w_val:>15} {l_val:>15}\n")

    # ============================================================
    # HYPOTHESIS 12: Market environment — was the overall market favorable?
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设12: 月度表现差异 — 不同月份策略效果是否不同?\n")
    f.write("="*120 + "\n\n")

    month_stats = defaultdict(lambda: {'total':0, 'win':0, 't1_lu':0, 'cons_lu':[], 'vol':[]})
    for t in trades:
        month = t['date'][:7]
        month_stats[month]['total'] += 1
        if t['buy_is_lu']:
            month_stats[month]['win'] += 1
        if t['t1_is_lu']:
            month_stats[month]['t1_lu'] += 1
        month_stats[month]['cons_lu'].append(t['cons_lu'])
        month_stats[month]['vol'].append(t['t1_vol_ratio5'])

    f.write(f"{'月份':<10} {'交易数':>6} {'涨停率':>8} {'T-1涨停率':>10} {'平均连板':>8} {'平均量比':>8}\n")
    f.write("-"*55 + "\n")
    for month in sorted(month_stats.keys()):
        s = month_stats[month]
        win_rate = s['win']/s['total']*100
        t1_rate = s['t1_lu']/s['total']*100
        avg_cons = sum(s['cons_lu'])/len(s['cons_lu'])
        avg_vol = sum(s['vol'])/len(s['vol'])
        f.write(f"{month:<10} {s['total']:>6} {win_rate:>7.0f}% {t1_rate:>9.0f}% {avg_cons:>8.1f} {avg_vol:>8.1f}x\n")

    # ============================================================
    # HYPOTHESIS 13: Combined filter analysis
    # What combination of filters best predicts success?
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设13: 组合筛选效果 — 不同条件组合下的成功率\n")
    f.write("="*120 + "\n\n")

    filters_to_test = [
        ("所有交易", lambda t: True),
        ("T-1涨停", lambda t: t['t1_is_lu']),
        ("T-1涨停 + 量比>=1.5x", lambda t: t['t1_is_lu'] and t['t1_vol_ratio5'] >= 1.5),
        ("T-1涨停 + 量比>=2x", lambda t: t['t1_is_lu'] and t['t1_vol_ratio5'] >= 2.0),
        ("T-1涨停 + T-2涨停(连板)", lambda t: t['t1_is_lu'] and t['t2_is_lu']),
        ("T-1涨停 + 量比>=1.5x + 连板", lambda t: t['t1_is_lu'] and t['t1_vol_ratio5'] >= 1.5 and t['t2_is_lu']),
        ("T-1涨停 + 开盘高开>0", lambda t: t['t1_is_lu'] and t['buy_gap'] > 0),
        ("T-1涨停 + 强板(开盘>=5%)", lambda t: t['t1_is_lu'] and t['t1_gap_open'] >= 5),
        ("T-1涨停 + 首板(非连板)", lambda t: t['t1_is_lu'] and t['cons_lu'] == 0),
        ("T-1涨停 + 2连板", lambda t: t['t1_is_lu'] and t['cons_lu'] == 1),
        ("T-1非涨停但T-2涨停", lambda t: not t['t1_is_lu'] and t['t2_is_lu']),
        ("T-1涨停 + 20日新高", lambda t: t['t1_is_lu'] and t['t1_is_20d_high']),
        ("T-1涨停 + 量比1-3x(适中)", lambda t: t['t1_is_lu'] and 1.0 <= t['t1_vol_ratio5'] <= 3.0),
        ("T-1涨停 + 量比>3x(巨量)", lambda t: t['t1_is_lu'] and t['t1_vol_ratio5'] > 3.0),
    ]

    f.write(f"{'筛选条件':<40} {'数量':>5} {'涨停数':>6} {'成功率':>8}\n")
    f.write("-"*62 + "\n")
    for name, fn in filters_to_test:
        matched = [t for t in trades if fn(t)]
        wins = sum(1 for t in matched if t['buy_is_lu'])
        rate = wins / len(matched) * 100 if matched else 0
        f.write(f"{name:<40} {len(matched):>5} {wins:>6} {rate:>7.1f}%\n")

    # ============================================================
    # HYPOTHESIS 14: What about multi-stock holding days (June)?
    # Are there different selection criteria in June?
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设14: 6月多票模式 — 选股标准是否与非6月不同?\n")
    f.write("="*120 + "\n\n")

    june_trades = [t for t in trades if t['date'].startswith('2026-06')]
    non_june = [t for t in trades if not t['date'].startswith('2026-06')]

    f.write(f"6月交易: {len(june_trades)}笔, 非6月: {len(non_june)}笔\n")
    f.write(f"6月当日涨停率: {sum(1 for t in june_trades if t['buy_is_lu'])}/{len(june_trades)} ({sum(1 for t in june_trades if t['buy_is_lu'])/len(june_trades)*100:.0f}%)\n")
    f.write(f"非6月当日涨停率: {sum(1 for t in non_june if t['buy_is_lu'])}/{len(non_june)} ({sum(1 for t in non_june if t['buy_is_lu'])/len(non_june)*100:.0f}%)\n")

    for label, group in [('6月', june_trades), ('非6月', non_june)]:
        if group:
            f.write(f"\n{label}:\n")
            f.write(f"  T-1涨停率: {sum(1 for t in group if t['t1_is_lu'])/len(group)*100:.0f}%\n")
            f.write(f"  平均量比: {sum(t['t1_vol_ratio5'] for t in group)/len(group):.1f}x\n")
            f.write(f"  平均连板: {sum(t['cons_lu'] for t in group)/len(group):.1f}\n")
            f.write(f"  平均开盘涨幅: {sum(t['buy_gap'] for t in group)/len(group):.1f}%\n")

    # ============================================================
    # HYPOTHESIS 15: Turnover rate proxy (volume / typical volume)
    # Use vol_ratio20 (vs 20-day average) as a cleaner signal
    # ============================================================
    f.write("\n" + "="*120 + "\n")
    f.write("假设15: 换手率指标 — 以20日均量比作为换手率代理\n")
    f.write("="*120 + "\n\n")

    f.write("T-1量比(vs 20日均量)与成功率:\n")
    vol20_buckets = {'<1x': [], '1-2x': [], '2-3x': [], '3-5x': [], '>5x': []}
    for t in trades:
        v = t['t1_vol_ratio20']
        if v < 1: vol20_buckets['<1x'].append(t)
        elif v < 2: vol20_buckets['1-2x'].append(t)
        elif v < 3: vol20_buckets['2-3x'].append(t)
        elif v < 5: vol20_buckets['3-5x'].append(t)
        else: vol20_buckets['>5x'].append(t)

    for b, group in vol20_buckets.items():
        if group:
            wins = sum(1 for t in group if t['buy_is_lu'])
            f.write(f"  {b}: {len(group)}笔, 涨停率: {wins}/{len(group)} ({wins/len(group)*100:.0f}%)\n")

print(f"Deep analysis complete! Output: {out_path}")
