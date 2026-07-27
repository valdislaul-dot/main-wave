import akshare as ak
import baostock as bs
import time
from datetime import datetime, timedelta
from collections import defaultdict

START_D = '2026-03-01'
END_D = '2026-07-24'

# Generate trading days
all_dates = []
d = datetime.strptime(START_D, '%Y-%m-%d')
end = datetime.strptime(END_D, '%Y-%m-%d')
while d <= end:
    if d.weekday() < 5:
        all_dates.append(d)
    d += timedelta(days=1)

print(f'Trading days: {len(all_dates)}')

# Step 1: Download all LU pools
print('Step 1: Downloading LU pools...')
lu_pools = {}
for i, dt in enumerate(all_dates):
    dt_str = dt.strftime('%Y%m%d')
    try:
        df = ak.stock_zt_pool_em(date=dt_str)
        def ok(c):
            return not (c.startswith('300') or c.startswith('301') or c.startswith('688'))
        df = df[df['代码'].apply(ok)]
        lu_pools[dt.strftime('%Y-%m-%d')] = df
    except:
        lu_pools[dt.strftime('%Y-%m-%d')] = None
    if (i+1) % 30 == 0:
        print(f'  {i+1}/{len(all_dates)}')

print(f'LU pools: {len(lu_pools)} days')

# Step 2: Collect unique codes
all_codes = set()
for dt_str, df in lu_pools.items():
    if df is not None:
        for _, row in df.iterrows():
            all_codes.add(str(row['代码']))
print(f'Unique stocks: {len(all_codes)}')

# Step 3: Download K-lines
print('Step 3: Downloading K-lines...')
bs.login()
kline_cache = {}
errors = 0
code_list = sorted(all_codes)
for i, code in enumerate(code_list):
    try:
        if code.startswith('6'): bs_code = f'sh.{code}'
        else: bs_code = f'sz.{code}'
        rs = bs.query_history_k_data_plus(bs_code,
            'date,open,high,low,close',
            start_date='2026-02-15', end_date='2026-07-24',
            frequency='d', adjustflag='2')
        if rs is None:
            errors += 1
            continue
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if len(rows) >= 25:
            kline_cache[code] = rows
        else:
            errors += 1
    except:
        errors += 1
    if (i+1) % 200 == 0:
        print(f'  {i+1}/{len(all_codes)} (cached {len(kline_cache)})')
bs.logout()
print(f'K-lines: {len(kline_cache)} cached, {errors} errors')

# Step 4: Simulate
print('Step 4: Simulating trades...')
by_board = defaultdict(list)
sim_count = 0

for i, dt in enumerate(all_dates):
    dt_str = dt.strftime('%Y-%m-%d')
    df = lu_pools.get(dt_str)
    if df is None or i + 1 >= len(all_dates):
        continue

    next_dt = all_dates[i + 1]

    for _, row in df.iterrows():
        code = str(row['代码'])
        if code not in kline_cache:
            continue

        kls = kline_cache[code]

        # Find today's index
        idx = None
        for j, r in enumerate(kls):
            if r[0] == dt_str:
                idx = j
                break
        if idx is None or idx < 1:
            continue

        today_o = float(kls[idx][1])
        today_c = float(kls[idx][2])
        prev_c = float(kls[idx-1][2])

        # Opening gap
        gap = (today_o - prev_c) / prev_c * 100

        # Only buy 4-8% range
        if not (4.0 <= gap <= 8.0):
            continue

        # Count board number (consecutive LU before today)
        cons = 0
        j = idx - 1
        while j > 0:
            cj = float(kls[j][2])
            pj = float(kls[j-1][2]) if j > 0 else 0
            if pj > 0:
                lpx = round(pj * 1.10, 2)
                if cj >= lpx - 0.005:
                    cons += 1
                    j -= 1
                else:
                    break
            else:
                break
        board_num = cons + 1

        # Find sell: walk forward until open gap < 3%
        sell_idx = idx + 1
        sold = False
        while sell_idx < len(kls):
            so = float(kls[sell_idx][1])
            sc = float(kls[sell_idx][2])
            sh = float(kls[sell_idx][3])
            spc = float(kls[sell_idx-1][2])

            sg = (so - spc) / spc * 100

            if sg < 3.0:
                # Sell: LU day -> close, else -> (H+O)/2
                ls_price = round(spc * 1.10, 2)
                is_lu = sc >= ls_price - 0.005
                sp = sc if is_lu else (sh + so) / 2
                pnl = (sp - today_o) / today_o * 100
                by_board[board_num].append(pnl)
                sim_count += 1
                sold = True
                break
            sell_idx += 1

    if (i+1) % 20 == 0:
        print(f'  Day {i+1}/{len(all_dates)}, trades so far: {sim_count}')

print(f'Total simulated trades: {sim_count}')

# Output
out_path = r'C:\Users\Davis\Desktop\主升浪\logs\full_market_perf_v2.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*70+"\n")
    f.write("全市场: 买入时连板数 vs 实际盈亏\n")
    f.write("规则: 竞价4-8%买入, 开盘<3%卖出, 涨停日卖收盘否则卖(H+O)/2\n")
    f.write(f"样本: {START_D} 至 {END_D}, 全市场(剔除300/301/688)\n")
    f.write("="*70+"\n\n")
    f.write(f"{'连板数':<8} {'笔数':>8} {'平均盈亏':>10} {'中位盈亏':>10} {'胜率':>10} {'盈亏比':>10}\n")
    f.write("-"*60+"\n")

    for b in range(1, 10):
        trades = by_board.get(b, [])
        if len(trades) >= 3:
            avg = sum(trades) / len(trades)
            med = sorted(trades)[len(trades)//2]
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            wr = len(wins) / len(trades) * 100
            aw = sum(wins) / len(wins) if wins else 0
            al = sum(losses) / len(losses) if losses else -1
            plr = aw / abs(al) if al != 0 else 0
            f.write(f"{b}连板     {len(trades):>8} {avg:>+9.1f}% {med:>+9.1f}% {wr:>9.0f}% {plr:>9.1f}\n")

    f.write(f"\n总交易: {sim_count}笔\n")

print(f"Done: {out_path}")
