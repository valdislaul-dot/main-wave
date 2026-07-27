"""
T字板识别 + 分钟K线下载 (腾讯API版)
1. 扫描日K线找出T字板
2. 用腾讯ifzq.gtimg.cn下载1分/5分K线
"""
import json, os, time, urllib.request
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

BASE = r'C:\Users\Davis\Desktop\gogo'
KLINE_DIR = Path(BASE) / 'data' / 'kline_data'
OUT_DIR = Path(BASE) / 'data' / 'minute_kline'
OUT_DIR.mkdir(parents=True, exist_ok=True)

def get_lp(code):
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10

def is_limit_up(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0: return False
    return close >= round(prev_close * (1 + lpct), 2) - 0.005

def get_prefix(code):
    return 'sh' if code.startswith(('5','6','9')) else 'sz'

# ================================================================
# STEP 1: Scan kline_data for T-board patterns
# ================================================================
print("=" * 60)
print("STEP 1: Scanning for T-board patterns")
print("=" * 60)

t_boards = []

for f in sorted(KLINE_DIR.glob('*.json')):
    code = f.stem.split('_')[1] if '_' in f.stem else f.stem
    if code.startswith(('300', '301', '688')):
        continue
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            klines = json.load(fh)
    except:
        continue
    if len(klines) < 2:
        continue

    lpct = get_lp(code)
    for i in range(1, len(klines)):
        k = klines[i]; prev = klines[i-1]
        date = k.get('date', '')
        o = float(k['open']); c = float(k['close'])
        h = float(k['high']); l = float(k['low'])
        prev_c = float(prev['close'])
        if prev_c <= 0: continue

        gap = (o - prev_c) / prev_c * 100
        lu_today = is_limit_up(c, prev_c, lpct)
        min_gap = 19.5 if lpct > 0.15 else 9.5

        # T-board: opened limit-up, dipped, re-sealed at limit-up
        if gap >= min_gap and lu_today and (h - l) > 0.01:
            upper_shadow = h - max(c, o)
            lower_shadow = min(c, o) - l
            if lower_shadow > 0.03 and upper_shadow < 0.03:
                t_boards.append({
                    'code': code, 'date': date,
                    'open': round(o, 2), 'high': round(h, 2),
                    'low': round(l, 2), 'close': round(c, 2),
                    'prev_close': round(prev_c, 2),
                    'gap_pct': round(gap, 2),
                    'lower_shadow_pct': round(lower_shadow / prev_c * 100, 2),
                })

t_boards.sort(key=lambda x: (x['date'], x['code']))
print(f"Found {len(t_boards)} T-board events")

# Deduplicate by (code, date)
unique = {}
for t in t_boards:
    key = (t['code'], t['date'])
    if key not in unique: unique[key] = t
print(f"Unique events: {len(unique)}")

# ================================================================
# STEP 2: Download minute K-line via Tencent API
# ================================================================
print("\n" + "=" * 60)
print("STEP 2: Downloading 1-min & 5-min K-line (Tencent API)")
print("=" * 60)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def fetch_minute(code, freq, count=320):
    """Fetch minute K-line from Tencent. freq='m1' or 'm5'."""
    pre = get_prefix(code)
    url = (f'https://ifzq.gtimg.cn/appstock/app/kline/mkline'
           f'?param={pre}{code},{freq},,{count}&_var=result')
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Referer': 'https://gu.qq.com/'
    })
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode('gbk')
        if '=' in data:
            d = json.loads(data.split('=', 1)[1].strip())
            bars = d.get('data', {}).get(f'{pre}{code}', {}).get(freq, [])
            return bars
    except Exception as e:
        print(f"  Error fetching {code} {freq}: {e}")
    return []

downloaded = 0; failed = 0
events = list(unique.values())

for i, t in enumerate(events):
    code, date = t['code'], t['date']
    out_file = OUT_DIR / f"{code}_{date}.json"

    if out_file.exists():
        downloaded += 1
        continue

    try:
        m1_bars = fetch_minute(code, 'm1', 240)
        time.sleep(0.2)
        m5_bars = fetch_minute(code, 'm5', 320)

        # Filter to target date
        date_compact = date.replace('-', '')
        m1_filtered = [b for b in m1_bars if b[0].startswith(date_compact)]
        m5_filtered = [b for b in m5_bars if b[0].startswith(date_compact)]

        data = {
            'code': code, 'date': date,
            't_board': t,
            'min1': [{
                't': b[0], 'o': round(float(b[1]), 2),
                'c': round(float(b[2]), 2), 'h': round(float(b[3]), 2),
                'l': round(float(b[4]), 2), 'v': int(float(b[5])),
                'turnover_bp': float(b[7]) if len(b) > 7 else 0,
            } for b in m1_filtered],
            'min5': [{
                't': b[0], 'o': round(float(b[1]), 2),
                'c': round(float(b[2]), 2), 'h': round(float(b[3]), 2),
                'l': round(float(b[4]), 2), 'v': int(float(b[5])),
                'turnover_bp': float(b[7]) if len(b) > 7 else 0,
            } for b in m5_filtered],
        }

        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        downloaded += 1
        if downloaded % 10 == 0:
            print(f"  [{downloaded}/{len(events)}] {code} {date}: "
                  f"m1={len(m1_filtered)} m5={len(m5_filtered)}")
    except Exception as e:
        failed += 1
        if failed <= 3:
            print(f"  FAIL {code} {date}: {e}")
        time.sleep(0.5)

# ================================================================
# STEP 3: Summary
# ================================================================
print(f"\nDone: {downloaded} downloaded, {failed} failed")

files = list(OUT_DIR.glob('*.json'))
total_m1 = 0; total_m5 = 0
sample = None
for f in files:
    with open(f) as fh:
        d = json.load(fh)
    total_m1 += len(d.get('min1', []))
    total_m5 += len(d.get('min5', []))
    if sample is None and len(d.get('min5', [])) > 5:
        sample = d

print(f"Files: {len(files)} | Total bars: m1={total_m1} m5={total_m5}")

if sample:
    print(f"\nSample: {sample['code']} {sample['date']}")
    print(f"  T-board: gap={sample['t_board']['gap_pct']}% "
          f"low_shadow={sample['t_board']['lower_shadow_pct']}%")
    print(f"  1-min bars: {len(sample['min1'])}")
    if sample['min1']:
        first = sample['min1'][0]; last = sample['min1'][-1]
        open_p = float(sample['t_board']['open'])
        low_p = float(sample['t_board']['low'])
        print(f"    09:31 open={first['o']} → 15:00 close={last['c']}")
        # Find the dip (lowest price)
        lowest = min(sample['min1'], key=lambda x: x['l'])
        print(f"    lowest bar: {lowest['t']} l={lowest['l']}")
        recovery = [(b['t'], b['c']) for b in sample['min1'] if float(b['c']) >= float(sample['t_board']['close'])*0.995]
        if recovery:
            print(f"    re-sealed at: {recovery[0][0]}")
    print(f"  5-min bars: {len(sample['min5'])}")

print(f"\nOutput: {OUT_DIR}")
