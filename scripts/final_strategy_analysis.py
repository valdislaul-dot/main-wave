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

        # MAs
        if i >= 5:
            ma5 = sum(float(klines[j]['close']) for j in range(i-5, i)) / 5
        else:
            ma5 = c
        if i >= 10:
            ma10 = sum(float(klines[j]['close']) for j in range(i-10, i)) / 10
        else:
            ma10 = c
        if i >= 20:
            ma20 = sum(float(klines[j]['close']) for j in range(i-20, i)) / 20
        else:
            ma20 = c
        if i >= 60:
            ma60 = sum(float(klines[j]['close']) for j in range(i-60, i)) / 60
        else:
            ma60 = c

        entry['ma5'] = ma5
        entry['ma10'] = ma10
        entry['ma20'] = ma20
        entry['ma60'] = ma60
        entry['pct_from_ma5'] = (c - ma5) / ma5 * 100
        entry['pct_from_ma20'] = (c - ma20) / ma20 * 100
        entry['pct_from_ma60'] = (c - ma60) / ma60 * 100

        # Pre-trend: 5-day and 10-day change before this day
        if i >= 5:
            entry['chg_5d'] = (c - float(klines[i-5]['close'])) / float(klines[i-5]['close']) * 100
        else:
            entry['chg_5d'] = 0
        if i >= 10:
            entry['chg_10d'] = (c - float(klines[i-10]['close'])) / float(klines[i-10]['close']) * 100
        else:
            entry['chg_10d'] = 0

        # Consecutive limit-up count backward from this day
        cons_lu = 0
        for j in range(i, max(i-10, -1), -1):
            check_date = klines[j]['day']
            if check_date in price_db[name] and price_db[name][check_date]['is_limit_up']:
                cons_lu += 1
            else:
                break
        entry['cons_lu_here'] = cons_lu

        # Days since last limit-up (excluding current)
        days_since_lu = 999
        for j in range(i-1, max(i-30, -1), -1):
            check_date = klines[j]['day']
            if check_date in price_db[name] and price_db[name][check_date]['is_limit_up']:
                days_since_lu = i - j
                break
        entry['days_since_lu'] = days_since_lu

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

        # Board seal quality
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

all_trade_dates = sorted(set(d for d, _ in timeline))

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
    for lookback in [1, 2, 3, 4, 5, 10]:
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
        'buy_close': buy_info['close'],
        'buy_is_lu': buy_info['is_limit_up'],
        'buy_gap': buy_info['gap_open_pct'],
        'buy_vol_ratio5': buy_info['vol_ratio5'],
        't1_change': t1.get('change_pct', 0),
        't1_is_lu': t1.get('is_limit_up', False),
        't1_gap_open': t1.get('gap_open_pct', 0),
        't1_vol_ratio5': t1.get('vol_ratio5', 1),
        't1_vol_ratio20': t1.get('vol_ratio20', 1),
        't1_seal': t1.get('seal_quality', 0),
        't1_pct_from_ma20': t1.get('pct_from_ma20', 0),
        't1_pct_from_ma60': t1.get('pct_from_ma60', 0),
        't1_chg_5d': t1.get('chg_5d', 0),
        't1_chg_10d': t1.get('chg_10d', 0),
        't1_days_since_lu': t1.get('days_since_lu', 999),
        't1_cons_lu': t1.get('cons_lu_here', 1),
        't1_is_20d_high': t1.get('is_20d_high', False),
        't2_is_lu': pre_days.get(2, {}).get('is_limit_up', False),
        'cons_lu': cons_lu,
        'pre_days': pre_days,
    })

total = len(trades)

out_path = r'C:\Users\Davis\Desktop\主升浪\final_strategy_analysis.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*120 + "\n")
    f.write("最终选股策略综合分析 V4\n")
    f.write("="*120 + "\n\n")

    # ====== SECTION 1: Long-term trend before limit-up ======
    f.write("="*120 + "\n")
    f.write("一、涨停前的趋势位置 — 股票在涨停前处于什么状态?\n")
    f.write("="*120 + "\n\n")

    f.write("T-1日价格相对均线位置:\n")
    f.write(f"{'指标':<30} {'< -20%':>8} {'-20~-10%':>8} {'-10~0%':>8} {'0~10%':>8} {'10~20%':>8} {'>20%':>8}\n")
    f.write("-"*80 + "\n")

    for label, key in [('vs MA20', 't1_pct_from_ma20'), ('vs MA60', 't1_pct_from_ma60')]:
        dist = Counter()
        for t in trades:
            v = t[key]
            if v < -20: dist['<-20%'] += 1
            elif v < -10: dist['-20~-10%'] += 1
            elif v < 0: dist['-10~0%'] += 1
            elif v < 10: dist['0~10%'] += 1
            elif v < 20: dist['10~20%'] += 1
            else: dist['>20%'] += 1
        f.write(f"{label:<30} {dist.get('<-20%',0):>8} {dist.get('-20~-10%',0):>8} {dist.get('-10~0%',0):>8} "
                f"{dist.get('0~10%',0):>8} {dist.get('10~20%',0):>8} {dist.get('>20%',0):>8}\n")

    # ====== SECTION 2: Pre-limit-up trend ======
    f.write("\n" + "="*120 + "\n")
    f.write("二、涨停前的涨幅趋势 — 是底部首板还是高位加速?\n")
    f.write("="*120 + "\n\n")

    f.write("T-1之前5日/10日涨幅分布与该股T-1是第几个涨停:\n")
    for label, key in [('5日涨幅', 't1_chg_5d'), ('10日涨幅', 't1_chg_10d')]:
        buckets = {'<0%':[], '0-10%':[], '10-20%':[], '20-30%':[], '30-50%':[], '>50%':[]}
        for t in trades:
            v = t[key]
            if v < 0: buckets['<0%'].append(t)
            elif v < 10: buckets['0-10%'].append(t)
            elif v < 20: buckets['10-20%'].append(t)
            elif v < 30: buckets['20-30%'].append(t)
            elif v < 50: buckets['30-50%'].append(t)
            else: buckets['>50%'].append(t)

        f.write(f"\n{label}:\n")
        f.write(f"  {'区间':<12} {'笔数':>5} {'平均连板':>6} {'涨停率':>8}\n")
        for bname, group in buckets.items():
            if group:
                wins = sum(1 for t in group if t['buy_is_lu'])
                avg_cons = sum(t['t1_cons_lu'] for t in group) / len(group)
                rate = wins / len(group) * 100
                f.write(f"  {bname:<12} {len(group):>5} {avg_cons:>6.1f} {rate:>7.0f}%\n")

    # ====== SECTION 3: First board vs Nth board ======
    f.write("\n" + "="*120 + "\n")
    f.write("三、涨停'新鲜度' — 是近期首次涨停还是连续涨停?\n")
    f.write("="*120 + "\n\n")

    f.write("距上次涨停天数 (days_since_lu on T-1):\n")
    ds_groups = {'=1天(连板中)':[], '=2天':[], '=3-5天':[], '=6-10天':[], '>10天':[], '首次(>30天)':[]}
    for t in trades:
        d = t['t1_days_since_lu']
        if d == 1: ds_groups['=1天(连板中)'].append(t)
        elif d == 2: ds_groups['=2天'].append(t)
        elif d <= 5: ds_groups['=3-5天'].append(t)
        elif d <= 10: ds_groups['=6-10天'].append(t)
        elif d <= 30: ds_groups['>10天'].append(t)
        else: ds_groups['首次(>30天)'].append(t)

    f.write(f"  {'距上次涨停':<20} {'笔数':>5} {'涨停率':>8}\n")
    for gname, group in ds_groups.items():
        if group:
            wins = sum(1 for t in group if t['buy_is_lu'])
            rate = wins / len(group) * 100
            f.write(f"  {gname:<20} {len(group):>5} {rate:>7.0f}%\n")

    # ====== SECTION 4: Repeated stocks analysis ======
    f.write("\n" + "="*120 + "\n")
    f.write("四、重复交易标的分析 — 为什么反复做这几只?\n")
    f.write("="*120 + "\n\n")

    stock_trade_count = Counter(t['name'] for t in trades)
    repeats = {name: count for name, count in stock_trade_count.items() if count >= 2}

    for name, count in sorted(repeats.items(), key=lambda x: x[1], reverse=True):
        stock_trades = [t for t in trades if t['name'] == name]
        f.write(f"\n{name} ({count}次交易):\n")
        for t in stock_trades:
            f.write(f"  {t['date']}: T-1涨停={t['t1_is_lu']}, T-1涨幅={t['t1_change']:.1f}%, "
                    f"T-1量比20d={t['t1_vol_ratio20']:.1f}x, 连板={t['cons_lu']}, "
                    f"结果={'✓涨停' if t['buy_is_lu'] else '✗未涨停'}\n")

    # ====== SECTION 5: T-1 intraday pattern (candlestick) ======
    f.write("\n" + "="*120 + "\n")
    f.write("五、T-1涨停日K线形态 — 一字板 vs 实体板 vs 烂板\n")
    f.write("="*120 + "\n\n")

    f.write("以T-1开盘价与收盘价的关系判断:\n")
    f.write("  一字板(open≈close≈high≈low): 封板最强势\n")
    f.write("  实体板(open<close, 但非一字): 有换手但封住\n")
    f.write("  高开低走(open≈high, close<high): 烂板/炸板\n\n")

    t1_lu_trades = [t for t in trades if t['t1_is_lu']]
    one_line = []  # 一字板 open == high == low == close basically
    solid = []     # 实体板
    weak = []      # 弱板

    for t in t1_lu_trades:
        info = t['pre_days'].get(1, {})
        o = info.get('open', 0)
        c = info.get('close', 0)
        h = info.get('high', 0)
        l = info.get('low', 0)
        if h > 0 and l > 0:
            upper_shadow = (h - max(o, c)) / (h - l) if h != l else 0
            body = abs(c - o) / (h - l) if h != l else 0
            if upper_shadow < 0.1 and body < 0.1:
                one_line.append(t)
            elif upper_shadow < 0.2:
                solid.append(t)
            else:
                weak.append(t)

    for label, group in [('一字板(极强势)', one_line), ('强实体板', solid), ('弱板/烂板', weak)]:
        wins = sum(1 for t in group if t['buy_is_lu'])
        rate = wins / len(group) * 100 if group else 0
        f.write(f"  {label}: {len(group)}笔, 次日涨停率: {rate:.0f}%\n")

    # ====== SECTION 6: The "rest day preceding stock" analysis ======
    f.write("\n" + "="*120 + "\n")
    f.write("六、交易员休息日深层规律 — 什么时候选择不出手?\n")
    f.write("="*120 + "\n\n")

    # Build a day-by-day journal
    holdings = []
    cash_available = True  # start with cash
    rest_reasons = []

    for i, (date, name) in enumerate(timeline):
        # Check if we'd be holding something
        prev_lu = False
        if holdings:
            held = holdings[-1]
            prev_date = all_trade_dates[all_trade_dates.index(date) - 1] if all_trade_dates.index(date) > 0 else None
            if prev_date and prev_date in price_db.get(held['name'], {}):
                if price_db[held['name']][prev_date]['is_limit_up']:
                    prev_lu = True

        if name == '休息':
            reason = "未知"
            if holdings and prev_lu:
                reason = f"持有{holdings[-1]['name']}涨停中→不出手(连板持有)"
            elif holdings and not prev_lu:
                reason = f"清仓后观望(前持仓{holdings[-1]['name']}未涨停)"
                holdings = []
            else:
                # Check how many T-1 limit-up stocks were available
                prev_d = all_trade_dates[all_trade_dates.index(date) - 1] if all_trade_dates.index(date) > 0 else date
                t1_lu_count = 0
                for sname in price_db:
                    if prev_d in price_db[sname] and price_db[sname][prev_d]['is_limit_up']:
                        t1_lu_count += 1
                reason = f"无持仓+T-1有{t1_lu_count}只涨停但选择休息"

            rest_reasons.append({'date': date, 'reason': reason, 'holdings': list(holdings)})
        else:
            # Buying
            if holdings and not prev_lu:
                holdings = []  # sold
            holdings.append({'name': name, 'buy_date': date})

    f.write("休息日原因分类:\n")
    for r in rest_reasons:
        f.write(f"  {r['date']}: {r['reason']}\n")

    # ====== SECTION 7: Gap analysis - T open vs T-1 close ======
    f.write("\n" + "="*120 + "\n")
    f.write("七、买入日开盘价 vs T-1收盘价的Gap分析\n")
    f.write("="*120 + "\n\n")

    gap_from_close = []
    for t in trades:
        if 1 in t['pre_days']:
            t1_close = t['pre_days'][1]['close']
            if t1_close > 0:
                gap = (t['buy_open'] - t1_close) / t1_close * 100
                gap_from_close.append({'date': t['date'], 'name': t['name'], 'gap': gap, 'buy_is_lu': t['buy_is_lu']})

    f.write("买入开盘价相对T-1收盘价的跳空:\n")
    pos_gap = [g for g in gap_from_close if g['gap'] > 0]
    neg_gap = [g for g in gap_from_close if g['gap'] <= 0]
    f.write(f"  跳空高开: {len(pos_gap)}笔, 涨停率: {sum(1 for g in pos_gap if g['buy_is_lu'])}/{len(pos_gap)} ({sum(1 for g in pos_gap if g['buy_is_lu'])/len(pos_gap)*100:.0f}%)\n")
    f.write(f"  平开/低开: {len(neg_gap)}笔, 涨停率: {sum(1 for g in neg_gap if g['buy_is_lu'])}/{len(neg_gap)} ({sum(1 for g in neg_gap if g['buy_is_lu'])/max(len(neg_gap),1)*100:.0f}%)\n")

    # ====== SECTION 8: Final strategy summary ======
    f.write("\n" + "="*120 + "\n")
    f.write("八、最终策略推断\n")
    f.write("="*120 + "\n\n")

    f.write("""
【策略名称】涨停板次日接力策略 (Post-Limit-Up Momentum Strategy)

【核心选股条件】(按置信度排序)

  ★★★ 基本确定:
  1. T-1日必须涨停 (91%覆盖率)
     - 70/77笔交易满足此条件
     - 仅7笔例外，其中4笔是"T-2涨停+T-1断板"模式

  2. T-1涨停板质量偏好——强板优先
     - 涨停且T-1开盘涨幅>=5%: 成功率55% (vs 基准43%)
     - T-1一字板/强实体板: 成功率更高

  3. 量能偏好——缩量涨停优先
     - T-1缩量(<1x 20日均量): 成功率55%
     - T-1极度缩量(<0.5x): 成功率73% ← 最有效的单一指标
     - 理论依据: 缩量=筹码锁定好/主力控盘强

  ★★ 较有可能:
  4. 连板接力偏好
     - 连板股买入(cons>=1): 占比91%, 成功率49%
     - 三板以上: 成功率50-62% (小样本)

  5. 周一效应
     - 周一交易成功率69%, 远高于其他日(31-43%)
     - 可能原因: 周末发酵的利好周一集中释放

  ★ 待验证:
  6. 第二模式: 涨停断板反包
     - T-2涨停+T-1断板(回调)→买入博反弹
     - 占例外交易的4/7

  7. 其他可能的筛选条件(数据中无法观测):
     - 市场情绪/热点题材
     - 盘口强度(封单量)
     - 流通市值(小盘偏好)
     - 龙虎榜/游资动向

【卖出规则】
  - 持股期间若持续涨停→继续持有(连板持有)
  - 一旦不涨停→次日开盘清仓
  - 6月特殊规则: 可同时持有2只(多票模式)

【资金管理】
  - 单票全仓进出(非6月)
  - 6月可分仓多票

【策略表现评估】
  - 原始策略(全样本): 成功率43%, 模拟收益-63%
  - 最优筛选子集(强板+连板+缩量): 成功率70%, 但仅10笔交易
  - 本质问题: 高胜率条件出现频率太低, 大部分交易质量不高
""")

print(f"Final analysis complete! Output: {out_path}")
