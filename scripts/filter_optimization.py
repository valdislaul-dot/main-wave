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

# Build price DB with refined indicators
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
            'body_pct': 0, 'upper_shadow': 0, 'lower_shadow': 0,
        }
        if prev_close is not None and prev_close > 0:
            entry['is_limit_up'] = is_limit_up(c, prev_close, limit_pct)
            entry['change_pct'] = (c - prev_close) / prev_close * 100
            entry['gap_open_pct'] = (o - prev_close) / prev_close * 100

        # Candlestick body and shadows
        if h > l and h > 0:
            body = abs(c - o)
            entry['body_pct'] = body / h * 100  # body as % of range
            entry['upper_shadow'] = (h - max(c, o)) / h * 100
            entry['lower_shadow'] = (min(c, o) - l) / h * 100

        # Volume
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

        # Board seal quality: close near high = strong seal
        if h > 0:
            entry['seal_quality'] = (c - l) / (h - l) if (h - l) > 0 else 1
        else:
            entry['seal_quality'] = 1

        price_db[name][date] = entry
        prev_close = c

# Build timeline
timeline = []
for serial, stock in records:
    d = excel_to_date(serial)
    timeline.append((d.strftime('%Y-%m-%d'), stock))

# Build trade data
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
    pre_days = {}
    for lookback in [1, 2, 3, 4, 5]:
        if idx >= lookback:
            prev_date = klines[idx - lookback]['day']
            if prev_date in price_db[name]:
                pre_days[lookback] = price_db[name][prev_date]

    cons_lu = 0
    for lb in [1, 2, 3, 4, 5]:
        if lb in pre_days and pre_days[lb]['is_limit_up']:
            cons_lu += 1
        else:
            break

    t1 = pre_days.get(1, {})

    trades.append({
        'date': date, 'name': name,
        'buy_open': buy_info['open'],
        'buy_is_lu': buy_info['is_limit_up'],
        'buy_gap': buy_info['gap_open_pct'],
        't1_change': t1.get('change_pct', 0),
        't1_is_lu': t1.get('is_limit_up', False),
        't1_gap_open': t1.get('gap_open_pct', 0),
        't1_vol_ratio5': t1.get('vol_ratio5', 1),
        't1_vol_ratio20': t1.get('vol_ratio20', 1),
        't1_seal': t1.get('seal_quality', 0),
        't1_body_pct': t1.get('body_pct', 0),
        't1_upper_shadow': t1.get('upper_shadow', 0),
        't1_is_20d_high': t1.get('is_20d_high', False),
        't2_is_lu': pre_days.get(2, {}).get('is_limit_up', False),
        'cons_lu': cons_lu,
        'pre_days': pre_days,
    })

total = len(trades)

out_path = r'C:\Users\Davis\Desktop\主升浪\filter_optimization.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*120 + "\n")
    f.write("筛选条件优化分析 V3\n")
    f.write("="*120 + "\n\n")

    # ================================================================
    # SECTION A: Volume paradox — deep dive
    # ================================================================
    f.write("="*120 + "\n")
    f.write("A. 量能悖论深度分析: 缩量涨停 vs 放量涨停\n")
    f.write("="*120 + "\n\n")
    f.write("理论: 缩量涨停=筹码锁定好/主力控盘强; 放量涨停=分歧大/出货风险\n\n")

    # Only T-1 limit-up trades
    t1_lu_trades = [t for t in trades if t['t1_is_lu']]

    # By 20-day volume ratio
    f.write("按T-1 20日均量比分组 (缩量vs放量):\n")
    vol_groups = {
        '极度缩量(<0.5x)': [],
        '缩量(0.5-1x)': [],
        '正常(1-1.5x)': [],
        '温和放量(1.5-2x)': [],
        '放量(2-3x)': [],
        '巨量(3-5x)': [],
        '天量(>5x)': [],
    }
    for t in t1_lu_trades:
        v = t['t1_vol_ratio20']
        if v < 0.5: vol_groups['极度缩量(<0.5x)'].append(t)
        elif v < 1: vol_groups['缩量(0.5-1x)'].append(t)
        elif v < 1.5: vol_groups['正常(1-1.5x)'].append(t)
        elif v < 2: vol_groups['温和放量(1.5-2x)'].append(t)
        elif v < 3: vol_groups['放量(2-3x)'].append(t)
        elif v < 5: vol_groups['巨量(3-5x)'].append(t)
        else: vol_groups['天量(>5x)'].append(t)

    f.write(f"{'量能分组':<25} {'笔数':>5} {'涨停率':>8} {'均连板':>6} {'均开盘gap':>8}\n")
    f.write("-"*60 + "\n")
    for gname, group in vol_groups.items():
        if group:
            wins = sum(1 for t in group if t['buy_is_lu'])
            rate = wins / len(group) * 100
            avg_cons = sum(t['cons_lu'] for t in group) / len(group)
            avg_gap = sum(t['buy_gap'] for t in group) / len(group)
            f.write(f"{gname:<25} {len(group):>5} {rate:>7.0f}% {avg_cons:>6.1f} {avg_gap:>7.1f}%\n")

    # ================================================================
    # SECTION B: Seal quality of T-1 board
    # ================================================================
    f.write("\n" + "="*120 + "\n")
    f.write("B. T-1涨停封板质量分析\n")
    f.write("="*120 + "\n\n")
    f.write("封板质量 = (收盘-最低)/(最高-最低), 越接近1说明收盘越靠近最高价(封板越牢)\n")
    f.write("上影线占比 = (最高-max(开,收))/最高, 越大说明盘中开板/炸板\n\n")

    seal_groups = {
        '完美封板(>=0.95)': [],
        '强封板(0.8-0.95)': [],
        '一般(0.5-0.8)': [],
        '弱/炸板(<0.5)': [],
    }
    for t in t1_lu_trades:
        sq = t['t1_seal']
        if sq >= 0.95: seal_groups['完美封板(>=0.95)'].append(t)
        elif sq >= 0.8: seal_groups['强封板(0.8-0.95)'].append(t)
        elif sq >= 0.5: seal_groups['一般(0.5-0.8)'].append(t)
        else: seal_groups['弱/炸板(<0.5)'].append(t)

    f.write(f"{'封板质量':<25} {'笔数':>5} {'涨停率':>8}\n")
    f.write("-"*42 + "\n")
    for gname, group in seal_groups.items():
        if group:
            wins = sum(1 for t in group if t['buy_is_lu'])
            rate = wins / len(group) * 100
            f.write(f"{gname:<25} {len(group):>5} {rate:>7.0f}%\n")

    # ================================================================
    # SECTION C: Optimal filter combinations
    # ================================================================
    f.write("\n" + "="*120 + "\n")
    f.write("C. 最优筛选组合 — 穷举多条件组合\n")
    f.write("="*120 + "\n\n")

    combos = [
        # Single conditions
        ("1. 全部(基准)", lambda t: True),
        ("2. T-1涨停", lambda t: t['t1_is_lu']),
        # Strong board combos
        ("3. T-1涨停 + 强板(开盘>=5%)", lambda t: t['t1_is_lu'] and t['t1_gap_open'] >= 5),
        ("4. T-1涨停 + 强板 + 连板", lambda t: t['t1_is_lu'] and t['t1_gap_open'] >= 5 and t['t2_is_lu']),
        ("5. T-1涨停 + 强板 + 缩量(<1x 20d)", lambda t: t['t1_is_lu'] and t['t1_gap_open'] >= 5 and t['t1_vol_ratio20'] < 1.0),
        ("6. T-1涨停 + 强板 + 连板 + 缩量", lambda t: t['t1_is_lu'] and t['t1_gap_open'] >= 5 and t['t2_is_lu'] and t['t1_vol_ratio20'] < 1.0),
        # Volume combos
        ("7. T-1涨停 + 缩量(<1x 20d)", lambda t: t['t1_is_lu'] and t['t1_vol_ratio20'] < 1.0),
        ("8. T-1涨停 + 缩量 + 连板", lambda t: t['t1_is_lu'] and t['t1_vol_ratio20'] < 1.0 and t['t2_is_lu']),
        ("9. T-1涨停 + 温和放量(1-2x)", lambda t: t['t1_is_lu'] and 1.0 <= t['t1_vol_ratio20'] < 2.0),
        # Multi-condition
        ("10. T-1涨停 + 强板 + 完美封板(>=0.95)", lambda t: t['t1_is_lu'] and t['t1_gap_open'] >= 5 and t['t1_seal'] >= 0.95),
        ("11. T-1涨停 + 连板 + 完美封板", lambda t: t['t1_is_lu'] and t['t2_is_lu'] and t['t1_seal'] >= 0.95),
        # Combined optimal
        ("12. ★最优组合: 涨停+强板+连板+缩量+完美封板", lambda t: t['t1_is_lu'] and t['t1_gap_open'] >= 5 and t['t2_is_lu'] and t['t1_vol_ratio20'] < 1.0 and t['t1_seal'] >= 0.95),
        # Non-limit-up exceptions
        ("13. T-1非涨停(例外模式)", lambda t: not t['t1_is_lu']),
        # Day of week
        ("14. T-1涨停 + 周一", lambda t: t['t1_is_lu'] and datetime.strptime(t['date'], '%Y-%m-%d').weekday() == 0),
    ]

    f.write(f"{'筛选条件':<55} {'数量':>5} {'涨停数':>6} {'成功率':>8} {'相对基准':>8}\n")
    f.write("-"*85 + "\n")
    baseline = 33/77*100
    for name, fn in combos:
        matched = [t for t in trades if fn(t)]
        wins = sum(1 for t in matched if t['buy_is_lu'])
        rate = wins / len(matched) * 100 if matched else 0
        diff = rate - baseline
        f.write(f"{name:<55} {len(matched):>5} {wins:>6} {rate:>7.1f}% {diff:>+7.1f}%\n")

    # ================================================================
    # SECTION D: The 7 exception trades — what's the pattern?
    # ================================================================
    f.write("\n" + "="*120 + "\n")
    f.write("D. 非T-1涨停的7笔例外 — 深度分析\n")
    f.write("="*120 + "\n\n")

    exceptions = [t for t in trades if not t['t1_is_lu']]
    f.write("这7笔交易可能揭示了'涨停策略之外'的第二选股模式:\n\n")
    f.write(f"{'日期':<12} {'标的':<10} {'T-1涨':>7} {'T-2涨':>7} {'T-2涨停':>8} {'T-1量比':>7} {'模式':<20}\n")
    f.write("-"*80 + "\n")
    for t in exceptions:
        t2 = t['pre_days'].get(2, {})
        pattern = ""
        if t['t2_is_lu'] and t['t1_change'] < 5:
            pattern = "断板反包(涨停→回调→买)"
        elif t['t2_is_lu'] and t['t1_change'] >= 5:
            pattern = "涨停后冲高回落→买"
        elif not t['t2_is_lu'] and t['t1_change'] > 10:
            pattern = "近涨停(差一点封板)→买"
        else:
            pattern = "其他"
        f.write(f"{t['date']:<12} {t['name']:<10} {t['t1_change']:>+6.1f}% "
                f"{t2.get('change_pct', 0):>+6.1f}% "
                f"{'是' if t['t2_is_lu'] else '否':>8} "
                f"{t['t1_vol_ratio5']:>6.1f}x "
                f"{pattern:<20}\n")

    f.write(f"\n结论: 7笔例外中, {sum(1 for t in exceptions if t['t2_is_lu'])}笔是'T-2涨停+T-1断板'模式\n")

    # ================================================================
    # SECTION E: Forward return analysis
    # What happens AFTER the buy? (beyond just the buy day)
    # ================================================================
    f.write("\n" + "="*120 + "\n")
    f.write("E. 买入后N日表现分析\n")
    f.write("="*120 + "\n\n")

    # For each trade, track cumulative return over next 1-5 days
    for label, horizon in [('次日(T+1)', 1), ('第2日(T+2)', 2), ('第3日(T+3)', 3), ('第5日(T+5)', 5)]:
        returns = []
        for t in trades:
            name = t['name']
            klines = stock_data[name]
            date_indices = [i for i, k in enumerate(klines) if k['day'] == t['date']]
            if not date_indices:
                continue
            idx = date_indices[0]
            if idx + horizon < len(klines):
                future_close = float(klines[idx + horizon]['close'])
                ret = (future_close - t['buy_open']) / t['buy_open'] * 100
                returns.append(ret)

        if returns:
            avg_ret = sum(returns) / len(returns)
            win_pct = sum(1 for r in returns if r > 0) / len(returns) * 100
            f.write(f"{label}: 平均收益={avg_ret:+.1f}%, 胜率={win_pct:.0f}%, 样本={len(returns)}\n")

    # ================================================================
    # SECTION F: Simulate with optimal filters
    # ================================================================
    f.write("\n" + "="*120 + "\n")
    f.write("F. 应用最优筛选后的模拟效果\n")
    f.write("="*120 + "\n\n")

    # Re-run a simple simulation with the optimal filter
    # 最优: T-1涨停 + 强板(开盘>=5%) + 连板 + 缩量(<1x 20d)
    optimal_fn = lambda t: t['t1_is_lu'] and t['t1_gap_open'] >= 5 and t['t2_is_lu'] and t['t1_vol_ratio20'] < 1.0
    optimal_trades = [t for t in trades if optimal_fn(t)]

    if optimal_trades:
        f.write(f"最优筛选条件: T-1涨停 + 强板(开盘>=5%) + 连板 + 缩量(<1x 20日均量)\n")
        f.write(f"筛选出: {len(optimal_trades)}笔交易\n\n")
        for t in optimal_trades:
            f.write(f"  {t['date']} {t['name']}: T-1开盘gap={t['t1_gap_open']:.1f}% "
                    f"量比20d={t['t1_vol_ratio20']:.1f}x 封板质量={t['t1_seal']:.2f} "
                    f"→ {'✓涨停' if t['buy_is_lu'] else '✗未涨停'}\n")

        wins = sum(1 for t in optimal_trades if t['buy_is_lu'])
        f.write(f"\n成功率: {wins}/{len(optimal_trades)} ({wins/len(optimal_trades)*100:.0f}%)\n")

    # Also try a broader but still filtered version
    f.write("\n--- 放宽条件 ---\n")
    broad_fn = lambda t: t['t1_is_lu'] and t['t1_gap_open'] >= 5 and t['t1_vol_ratio20'] < 1.5
    broad_trades = [t for t in trades if broad_fn(t)]
    wins = sum(1 for t in broad_trades if t['buy_is_lu'])
    f.write(f"T-1涨停 + 强板 + 量比<1.5x(20d): {len(broad_trades)}笔, 涨停率: {wins}/{len(broad_trades)} ({wins/len(broad_trades)*100:.0f}%)\n")

    # ================================================================
    # SECTION G: All stocks limit-up on T-1 that trader DIDN'T pick
    # This reveals what the trader is filtering OUT
    # ================================================================
    f.write("\n" + "="*120 + "\n")
    f.write("G. 交易员'放弃'了什么? — 同日多股涨停时的选择\n")
    f.write("="*120 + "\n\n")
    f.write("在同一天有多个T-1涨停股可选时,交易员只选1只。分析其选择偏好:\n\n")

    # Build: for each buy date, which stocks hit limit-up on the previous day?
    all_dates = sorted(set(t['date'] for t in trades))
    selection_analysis = []

    for i, date in enumerate(all_dates):
        # Which stocks had T-1 limit-up?
        t1_lu_stocks = []
        for name in price_db:
            if name in stock_data:
                klines = stock_data[name]
                date_indices = [j for j, k in enumerate(klines) if k['day'] == date]
                if date_indices:
                    idx = date_indices[0]
                    if idx >= 1:
                        prev_date = klines[idx - 1]['day']
                        if prev_date in price_db[name] and price_db[name][prev_date]['is_limit_up']:
                            entry = price_db[name][prev_date]
                            t1_lu_stocks.append({
                                'name': name,
                                't1_change': entry['change_pct'],
                                't1_gap': entry['gap_open_pct'],
                                't1_vol20': entry['vol_ratio20'],
                                't1_seal': entry['seal_quality'],
                            })

        # Which stock did the trader actually pick?
        picked = None
        for t in trades:
            if t['date'] == date and t['t1_is_lu']:
                picked = t['name']
                break

        if picked and len(t1_lu_stocks) >= 2:
            # Rank by various metrics and see where the picked stock ranks
            by_gap = sorted(t1_lu_stocks, key=lambda x: x['t1_gap'], reverse=True)
            by_vol20 = sorted(t1_lu_stocks, key=lambda x: x['t1_vol20'])
            by_seal = sorted(t1_lu_stocks, key=lambda x: x['t1_seal'], reverse=True)

            picked_rank_gap = next((j+1 for j, s in enumerate(by_gap) if s['name'] == picked), len(by_gap))
            picked_rank_vol = next((j+1 for j, s in enumerate(by_vol20) if s['name'] == picked), len(by_vol20))
            picked_rank_seal = next((j+1 for j, s in enumerate(by_seal) if s['name'] == picked), len(by_seal))

            selection_analysis.append({
                'date': date,
                'total_options': len(t1_lu_stocks),
                'picked': picked,
                'rank_gap': picked_rank_gap,
                'rank_vol': picked_rank_vol,
                'rank_seal': picked_rank_seal,
                'top_by_gap': by_gap[0]['name'],
                'top_by_lowvol': by_vol20[0]['name'],
                'top_by_seal': by_seal[0]['name'],
            })

    if selection_analysis:
        avg_rank_gap = sum(s['rank_gap'] for s in selection_analysis) / len(selection_analysis)
        avg_rank_vol = sum(s['rank_vol'] for s in selection_analysis) / len(selection_analysis)
        avg_rank_seal = sum(s['rank_seal'] for s in selection_analysis) / len(selection_analysis)

        f.write(f"有多个T-1涨停股可选的交易日: {len(selection_analysis)}天\n")
        f.write(f"交易员选中的股票在各维度的平均排名 (1=最优):\n")
        f.write(f"  T-1开盘涨幅排名: {avg_rank_gap:.1f} (选最强开盘的? {'是' if avg_rank_gap < 2.0 else '否'})\n")
        f.write(f"  T-1缩量排名: {avg_rank_vol:.1f} (选最缩量的? {'是' if avg_rank_vol < 2.0 else '否'})\n")
        f.write(f"  T-1封板质量排名: {avg_rank_seal:.1f} (选封板最牢的? {'是' if avg_rank_seal < 2.0 else '否'})\n")

        f.write(f"\n具体每天的选择:\n")
        f.write(f"{'日期':<12} {'可选':>4} {'选中':<10} {'gap排名':>6} {'量排名':>6} {'封板排名':>6} {'gap第一':<10} {'缩量第一':<10}\n")
        f.write("-"*85 + "\n")
        for s in selection_analysis:
            f.write(f"{s['date']:<12} {s['total_options']:>4} {s['picked']:<10} "
                    f"{s['rank_gap']:>4}/{s['total_options']} "
                    f"{s['rank_vol']:>4}/{s['total_options']} "
                    f"{s['rank_seal']:>4}/{s['total_options']} "
                    f"{s['top_by_gap']:<10} {s['top_by_lowvol']:<10}\n")

print(f"Filter optimization complete! Output: {out_path}")
