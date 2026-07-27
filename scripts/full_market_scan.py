import akshare as ak
import time
from datetime import datetime, timedelta

# Get Friday LU stocks
df = ak.stock_zt_pool_em(date='20260724')

# Filter: exclude 300/301/688
def allowed(code):
    return not (code.startswith('300') or code.startswith('301') or code.startswith('688'))

filtered = df[df['代码'].apply(allowed)]
codes = filtered['代码'].tolist()
names = dict(zip(filtered['代码'], filtered['名称']))
print(f'Scanning {len(codes)} stocks...')

def get_lp(code):
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10

def is_limit_up(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0: return False
    return close >= round(prev_close * (1 + lpct), 2) - 0.005

results = []
errors = 0

for code in codes:
    try:
        # Get 60 days of K-line data
        klines = ak.stock_zh_a_hist(symbol=code, period='daily',
                                     start_date='20260401', end_date='20260724',
                                     adjust='')
        if len(klines) < 25:
            continue

        time.sleep(0.3)  # rate limit

        # Build price DB
        pdb = {}
        prev_close = None
        for i, (_, row) in enumerate(klines.iterrows()):
            dt = row['日期'].strftime('%Y-%m-%d') if hasattr(row['日期'], 'strftime') else str(row['日期'])[:10]
            o = float(row['开盘']); c = float(row['收盘'])
            h = float(row['最高']); l = float(row['最低']); v = float(row['成交量'])

            entry = {'open': o, 'close': c, 'high': h, 'low': l, 'volume': v,
                     'is_limit_up': False, 'prev_close': prev_close,
                     'gap_open_pct': 0}
            if prev_close and prev_close > 0:
                lpct = get_lp(code)
                entry['is_limit_up'] = is_limit_up(c, prev_close, lpct)
                entry['gap_open_pct'] = (o - prev_close) / prev_close * 100
            if i >= 5:
                entry['vol_ma5'] = sum(float(klines.iloc[j]['成交量']) for j in range(i-5, i)) / 5
            else:
                entry['vol_ma5'] = v
            if i >= 20:
                entry['vol_ma20'] = sum(float(klines.iloc[j]['成交量']) for j in range(i-20, i)) / 20
            else:
                entry['vol_ma20'] = v
            entry['vol_ratio5'] = v / entry['vol_ma5'] if entry['vol_ma5'] > 0 else 1
            entry['vol_ratio20'] = v / entry['vol_ma20'] if entry['vol_ma20'] > 0 else 1

            if h > l > 0:
                us = (h - max(o, c)) / (h - l)
                body = abs(c - o) / (h - l)
                entry['is_one_line'] = (us < 0.1 and body < 0.1)
            else:
                entry['is_one_line'] = False

            cons = 0
            for j in range(i-1, max(i-10, -1), -1):
                cd_ = klines.iloc[j]['日期'].strftime('%Y-%m-%d') if hasattr(klines.iloc[j]['日期'], 'strftime') else str(klines.iloc[j]['日期'])[:10]
                if cd_ in pdb and pdb[cd_]['is_limit_up']:
                    cons += 1
                else:
                    break
            entry['cons_lu_before'] = cons
            pdb[dt] = entry
            prev_close = c

        # Score T-1 (Friday 07/24)
        fri = '2026-07-24'
        if fri not in pdb or not pdb[fri]['is_limit_up']:
            continue

        t1 = pdb[fri]
        score = 0.0

        # Volume factor
        v20 = t1['vol_ratio20']
        if v20 < 0.3: score += 35
        elif v20 < 0.5: score += 28
        elif v20 < 0.7: score += 22
        elif v20 < 1.0: score += 16
        elif v20 < 1.5: score += 8
        elif v20 < 2.0: score += 2
        elif v20 < 3.0: score -= 3
        elif v20 < 5.0: score -= 10
        else: score -= 18

        # Gap/open strength
        g = t1['gap_open_pct']
        if g >= 9.5: score += 22
        elif g >= 8: score += 18
        elif g >= 5: score += 13
        elif g >= 3: score += 7
        elif g >= 1: score += 2
        elif g >= 0: score += 0
        else: score -= 12

        # One-line board
        if t1.get('is_one_line', False): score += 12

        # Consecutive boards
        cons = t1['cons_lu_before']
        if cons == 0: score += 3
        elif cons == 1: score += 10
        elif cons == 2: score += 12
        elif cons >= 3: score += 7

        # Monday effect (周一加分)
        dow = datetime.strptime('2026-07-27', '%Y-%m-%d').weekday()
        if dow == 0: score += 18  # Monday!

        # T-2 consecutive check
        t2_lu = False
        dates_list = list(pdb.keys())
        fri_idx = dates_list.index(fri) if fri in dates_list else -1
        if fri_idx >= 2:
            t2_date = dates_list[fri_idx - 2]
            if t2_date in pdb:
                t2_lu = pdb[t2_date]['is_limit_up']
        if t2_lu: score += 6

        results.append({
            'code': code, 'name': names[code],
            'score': score, 'vr20': v20, 'gap': g,
            'cons': cons, 'one_line': t1.get('is_one_line', False),
            't2_lu': t2_lu, 'open': t1['open'],
            'seal_time': filtered[filtered['代码']==code]['首次封板时间'].values[0],
            'industry': filtered[filtered['代码']==code]['所属行业'].values[0],
        })

    except Exception as e:
        errors += 1
        if errors <= 3:
            print(f'  Error {code}: {e}')

# Sort and display
results.sort(key=lambda x: x['score'], reverse=True)

out_path = r'C:\Users\Davis\Desktop\主升浪\market_scan_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("=" * 85 + "\n")
    f.write("全市场涨停股筛选 (2026-07-24 周五 -> 周一07/27候选)\n")
    f.write("剔除创业板(300/301)和科创板(688) | 含周一效应加分\n")
    f.write("=" * 85 + "\n\n")
    f.write(f"{'#':<3} {'代码':<8} {'名称':<10} {'评分':>6} {'量比20d':>8} {'T-1gap':>8} {'连板':>4} {'一字':>4} {'封板时间':>8} {'行业':<12}\n")
    f.write("-" * 85 + "\n")
    for i, r in enumerate(results):
        f.write(f"{i+1:<3} {r['code']:<8} {r['name']:<10} {r['score']:>6.0f} {r['vr20']:>7.1f}x {r['gap']:>+7.1f}% {r['cons']:>4} {'Y' if r['one_line'] else 'N':>4} {r['seal_time']:>8} {r['industry']:<12}\n")

    # Top 3 by score, pick lowest volume
    if len(results) >= 3:
        top3 = sorted(results[:3], key=lambda x: x['vr20'])
        f.write(f"\n>> 推荐: {top3[0]['name']}({top3[0]['code']}) Top3中量最小\n")
        f.write(f">> 备选: {top3[1]['name']}({top3[1]['code']}) | {top3[2]['name']}({top3[2]['code']})\n")
    f.write(f"\n评分{len(results)}只 | 错误{errors}只\n")

print(f"Done: {out_path}")
