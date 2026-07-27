"""
每日K线数据更新
盘后运行：下载今日全市场涨停股的K线数据，更新本地数据库
"""
import baostock as bs
import os
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import akshare as ak
import json, os, time
from datetime import datetime, timedelta

# BASE auto-detected below
DAILY_DIR = os.path.join(BASE, '每日收盘数据')
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
INDEX_FILE = os.path.join(DAILY_DIR, 'stock_index.json')
WATCH_FILE = os.path.join(BASE, 'logs', 'watchlist.json')

os.makedirs(DAILY_DIR, exist_ok=True)
os.makedirs(KLINE_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE, 'logs'), exist_ok=True)

def get_today():
    """Get the most recent trading day (skip weekends)"""
    today = datetime.now()
    if today.hour < 15:  # Before market close, use previous day
        today = today - timedelta(days=1)
    # Skip to Friday if weekend
    while today.weekday() >= 5:
        today = today - timedelta(days=1)
    return today.strftime('%Y-%m-%d')

def code_to_bs(code):
    return f'sh.{code}' if code.startswith('6') else f'sz.{code}'

def load_watchlist():
    """Load/watchlist of stocks to track (from index + manual additions)"""
    stocks = {}
    # Load base index
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            stocks = json.load(f)
    # Merge with watchlist
    if os.path.exists(WATCH_FILE):
        with open(WATCH_FILE, 'r', encoding='utf-8') as f:
            wl = json.load(f)
            stocks.update(wl)
    return stocks

def save_watchlist(stocks):
    with open(WATCH_FILE, 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)

def update_stock_kline(name, code, bs_code, start_date, end_date):
    """Download K-line for a single stock"""
    rs = bs.query_history_k_data_plus(bs_code,
        'date,open,high,low,close,volume',
        start_date=start_date, end_date=end_date,
        frequency='d', adjustflag='2')
    if rs.error_code != '0':
        return None, rs.error_msg

    rows = []
    while rs.next():
        row = rs.get_row_data()
        rows.append(row)
    return rows, None

def main():
    today = get_today()
    print(f'[Update] Target date: {today}')

    # Check if today's data already exists
    today_dir = os.path.join(DAILY_DIR, today)
    if os.path.exists(today_dir):
        print(f'[Update] {today} data already exists, updating...')

    # Login
    bs.login()

    # Load stock list
    stocks = load_watchlist()
    print(f'[Update] Tracking {len(stocks)} stocks')

    # Also find today's LU stocks via akshare (new stocks to track)
    try:
        today_yyyymmdd = today.replace('-', '')
        df = ak.stock_zt_pool_em(date=today_yyyymmdd)
        # Filter out 创业板/科创板
        def allowed(code):
            return not (code.startswith('300') or code.startswith('301') or code.startswith('688'))
        df = df[df['代码'].apply(allowed)]

        new_count = 0
        for _, row in df.iterrows():
            code = str(row['代码'])
            name = str(row['名称'])
            if name not in stocks:
                stocks[name] = code
                new_count += 1

        if new_count > 0:
            print(f'[Update] Added {new_count} new stocks from today\'s LU pool')
            save_watchlist(stocks)
    except Exception as e:
        print(f'[Update] Warning: Could not fetch LU pool: {e}')

    # Download/update K-line for all tracked stocks
    # Get data from 90 days ago to ensure 20+ trading days
    start_date = (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')
    end_date = today

    success = 0
    errors = 0
    daily_data = {}

    for name, code in stocks.items():
        try:
            bs_code = code_to_bs(code)
            rows, err = update_stock_kline(name, code, bs_code, start_date, end_date)

            if err:
                errors += 1
                if errors <= 3:
                    print(f'  Error {name}({code}): {err}')
                continue

            if not rows or len(rows) < 5:
                continue

            # Save per-stock file
            key = f'{name}_{code}'
            kline_data = []
            for r in rows:
                def sf(s): return float(s) if s and s != '' else 0.0
                d = {
                    'date': r[0], 'open': sf(r[1]), 'high': sf(r[2]),
                    'low': sf(r[3]), 'close': sf(r[4]), 'volume': sf(r[5])
                }
                kline_data.append(d)
                # Also collect daily snapshot
                if r[0] not in daily_data:
                    daily_data[r[0]] = {}
                daily_data[r[0]][code] = {
                    'name': name, 'open': d['open'], 'high': d['high'],
                    'low': d['low'], 'close': d['close'], 'volume': d['volume']
                }

            fpath = os.path.join(KLINE_DIR, f'{key}.json')
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(kline_data, f, ensure_ascii=False)
            success += 1

        except Exception as e:
            errors += 1

    bs.logout()

    # Save daily snapshots
    for dt, data in daily_data.items():
        date_dir = os.path.join(DAILY_DIR, dt)
        os.makedirs(date_dir, exist_ok=True)
        fpath = os.path.join(date_dir, 'daily_data.json')
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)

    # Save updated index
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)

    print(f'[Update] Success: {success} stocks, Errors: {errors}')
    print(f'[Update] Daily snapshots: {len(daily_data)} dates (including today: {today})')
    print(f'[Update] Done!')

if __name__ == '__main__':
    main()
