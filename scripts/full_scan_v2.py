import akshare as ak
import baostock as bs
import time
from datetime import datetime

# Step 1: Get LU stocks from akshare
print('Step 1: Getting LU stock list...')
df = ak.stock_zt_pool_em(date='20260724')

def allowed(code):
    return not (code.startswith('300') or code.startswith('301') or code.startswith('688'))

filtered = df[df['代码'].apply(allowed)]
codes = filtered['代码'].tolist()
names = dict(zip(filtered['代码'], filtered['名称']))
seal_times = dict(zip(filtered['代码'], filtered['首次封板时间']))
industries = dict(zip(filtered['代码'], filtered['所属行业']))
print(f'Filtered: {len(codes)} stocks')

# Step 2: Login baostock
bs.login()

def get_lp(code):
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10

def baostock_code(c):
    if c.startswith('6'): return f'sh.{c}'
    else: return f'sz.{c}'

def is_limit_up(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0: return False
    return close >= round(prev_close * (1 + lpct), 2) - 0.005

results = []
errors = []
success = 0

for code in codes:
    try:
        bs_code = baostock_code(code)
        rs = bs.query_history_k_data_plus(bs_code,
            'date,open,high,low,close,volume',
            start_date='2026-03-01', end_date='2026-07-24',
            frequency='d', adjustflag='2')

        if rs.error_code != '0':
            errors.append((code, rs.error_msg))
            continue

        klines = []
        while rs.next():
            klines.append(rs.get_row_data())

        if len(klines) < 30:
            errors.append((code, f'Only {len(klines)} bars'))
            continue

        # Build price DB
        pdb = {}
        prev_close = None
        lpct = get_lp(code)

        for i, row in enumerate(klines):
            dt = row[0]
            o = float(row[1]); c = float(row[2])
            h = float(row[3]); l = float(row[4]); v = float(row[5])

            entry = {'open': o, 'close': c, 'high': h, 'low': l, 'volume': v,
                     'is_limit_up': False, 'prev_close': prev_close,
                     'gap_open_pct': 0}
            if prev_close and prev_close > 0:
                entry['is_limit_up'] = is_limit_up(c, prev_close, lpct)
                entry['gap_open_pct'] = (o - prev_close) / prev_close * 100

            if i >= 5:
                entry['vol_ma5'] = sum(float(klines[j][5]) for j in range(i-5, i)) / 5
            else:
                entry['vol_ma5'] = v
            if i >= 20:
                entry['vol_ma20'] = sum(float(klines[j][5]) for j in range(i-20, i)) / 20
            else:
                entry['vol_ma20'] = v
            entry['vol_ratio5'] = v / entry['vol_ma5'] if entry['vol_ma5'] > 0 else 1
            entry['vol_ratio20'] = v / entry['vol_ma20'] if entry['vol_ma20'] > 0 else 1

            if h > l > 0:
                us = (h - max(o, c)) / (h - l) if (h - l) > 0 else 0
                body = abs(c - o) / (h - l) if (h - l) > 0 else 0
                entry['is_one_line'] = (us < 0.1 and body < 0.1)
            else:
                entry['is_one_line'] = False

            cons = 0
            for j in range(i-1, max(i-10, -1), -1):
                cd_ = klines[j][0]
                if cd_ in pdb and pdb[cd_]['is_limit_up']:
                    cons += 1
                else:
                    break
            entry['cons_lu_before'] = cons
            pdb[dt] = entry
            prev_close = c

        # Score Friday 07/24
        fri = '2026-07-24'
        if fri not in pdb or not pdb[fri]['is_limit_up']:
            continue

        t1 = pdb[fri]
        score = 0.0

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

        g = t1['gap_open_pct']
        if g >= 9.5: score += 22
        elif g >= 8: score += 18
        elif g >= 5: score += 13
        elif g >= 3: score += 7
        elif g >= 1: score += 2
        elif g >= 0: score += 0
        else: score -= 12

        if t1.get('is_one_line', False): score += 12

        cons = t1['cons_lu_before']
        if cons == 0: score += 3
        elif cons == 1: score += 10
        elif cons == 2: score += 12
        elif cons >= 3: score += 7

        dow = datetime.strptime('2026-07-27', '%Y-%m-%d').weekday()
        if dow == 0: score += 18

        # T-2 LU check
        t2_lu = False
        dates_list = [k[0] for k in klines]
        fri_idx = dates_list.index(fri) if fri in dates_list else -1
        if fri_idx >= 2:
            t2_date = dates_list[fri_idx - 2]
            if t2_date in pdb:
                t2_lu = pdb[t2_date]['is_limit_up']
        if t2_lu: score += 6

        results.append({
            'code': code, 'name': names.get(code, '?'),
            'score': score, 'vr20': v20, 'gap': g,
            'cons': cons, 'one_line': t1.get('is_one_line', False),
            'open': t1['open'], 'close': t1['close'],
            'seal_time': seal_times.get(code, '?'),
            'industry': industries.get(code, '?'),
        })
        success += 1

    except Exception as e:
        errors.append((code, str(e)))

bs.logout()

# Sort and display
results.sort(key=lambda x: x['score'], reverse=True)

out_path = r'C:\Users\Davis\Desktop\主升浪\market_scan_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("=" * 90 + "\n")
    f.write("全市场涨停股筛选 (07/24周五涨停 -> 07/27周一候选)\n")
    f.write("剔除创业板(300/301)和科创板(688) | 含周一效应+18分\n")
    f.write("=" * 90 + "\n\n")
    f.write(f"{'#':<3} {'代码':<8} {'名称':<10} {'评分':>6} {'量比20d':>8} {'T-1gap':>8} {'连板':>4} {'一字':>4} {'开盘':>8} {'封板':>8} {'行业':<12}\n")
    f.write("-" * 90 + "\n")

    for i, r in enumerate(results):
        f.write(f"{i+1:<3} {r['code']:<8} {r['name']:<10} {r['score']:>6.0f} {r['vr20']:>7.1f}x {r['gap']:>+7.1f}% {r['cons']:>4} {'Y' if r['one_line'] else 'N':>4} {r['open']:>8.2f} {r['seal_time']:>8} {r['industry']:<12}\n")

    if len(results) >= 3:
        top3 = sorted(results[:3], key=lambda x: x['vr20'])
        f.write(f"\n>> 首选: {top3[0]['name']}({top3[0]['code']}) Top3中量比最小({top3[0]['vr20']:.1f}x)\n")
        f.write(f">> 备选: {top3[1]['name']}({top3[1]['code']}) | {top3[2]['name']}({top3[2]['code']})\n")

    f.write(f"\n成功{success}只 | 错误{len(errors)}只\n")
    if errors:
        for code, msg in errors[:5]:
            f.write(f"  {code}: {msg}\n")

print(f"Done: {out_path}")
print(f"Success: {success}, Errors: {len(errors)}")
