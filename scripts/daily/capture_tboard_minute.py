"""
盘后自动捕获T字板分钟K线
运行时机: 每天15:00后
数据源: 东财涨停池→筛选T字板 → 腾讯API下载1分/5分K线
"""
import json, os, sys, time, urllib.request
from pathlib import Path
from datetime import datetime, timedelta

BASE = Path(__file__).resolve().parent.parent.parent
OUT_DIR = BASE / 'data' / 'minute_kline'
OUT_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ============================================================
# Step 1: Get today's limit-up pool from 东财
# ============================================================
def get_today_zt_pool(date_str=None):
    """拉取东财涨停池，返回涨停股列表"""
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')

    import requests
    url = "https://push2ex.eastmoney.com/getTopicZTPool"
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 5000,
        "sort": "fbt:asc", "date": date_str,
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        pool = (r.json().get("data") or {}).get("pool") or []
    except Exception as e:
        print(f"[ERROR] 涨停池请求失败: {e}")
        return []

    results = []
    for p in pool:
        code = p["c"]
        # 排除300/301/688
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        fbt = p.get("fbt", 0)
        lbt = p.get("lbt", 0)
        results.append({
            'code': code,
            'name': p.get('n', ''),
            'price': p.get('p', 0) / 1000,
            'pct': round(p.get('zdp', 0), 2),
            'limit_days': p.get('lbc', 0),
            'first_seal': f"{str(fbt).zfill(6)[:2]}:{str(fbt).zfill(6)[2:4]}:{str(fbt).zfill(6)[4:6]}" if fbt else '',
            'last_seal': f"{str(lbt).zfill(6)[:2]}:{str(lbt).zfill(6)[2:4]}:{str(lbt).zfill(6)[4:6]}" if lbt else '',
            'break_times': p.get('zbc', 0),
            'seal_fund': p.get('fund', 0),
            'turnover': round(p.get('hs', 0), 2),
            'industry': p.get('hybk', ''),
            'zt_stat': f"{(p.get('zttj') or {}).get('days','?')}天{(p.get('zttj') or {}).get('ct','?')}板",
        })
    return results

# ============================================================
# Step 2: Identify T-board from limit-up pool
# ============================================================
def is_t_board(stock):
    """
    T字板判断: 从涨停池数据推断
    T字板特征: 开盘封涨停 → 盘中炸板 → 回封
    东财字段: break_times > 0 且 first_seal != last_seal → 有炸板回封
    """
    # 有炸板次数且最终回封了 = T字板
    if stock['break_times'] > 0 and stock['last_seal']:
        return True
    # 也可能是一字板开板但没回封（炸板池）
    return False

# ============================================================
# Step 3: Download minute K-line via Tencent
# ============================================================
def get_prefix(code):
    return 'sh' if code.startswith(('5', '6', '9')) else 'sz'

def fetch_minute(code, freq, count=320):
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
            return d.get('data', {}).get(f'{pre}{code}', {}).get(freq, [])
    except Exception as e:
        print(f"  [WARN] {code} {freq}: {e}")
    return []

def download_tboard_minute(code, date_str):
    """下载单只T字板的分钟K线"""
    out_file = OUT_DIR / f"{code}_{date_str}.json"

    # Skip if already downloaded and has data
    if out_file.exists():
        try:
            with open(out_file) as f:
                existing = json.load(f)
            if len(existing.get('min1', [])) > 0:
                return existing  # already good
        except:
            pass

    m1_bars = fetch_minute(code, 'm1', 240)
    time.sleep(0.15)
    m5_bars = fetch_minute(code, 'm5', 80)

    # Filter to target date
    date_compact = date_str.replace('-', '')
    m1_filtered = [b for b in m1_bars if b[0].startswith(date_compact)]
    m5_filtered = [b for b in m5_bars if b[0].startswith(date_compact)]

    data = {
        'code': code, 'date': date_str,
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

    if m1_filtered or m5_filtered:
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return data

# ============================================================
# Step 4: Analysis
# ============================================================
def analyze_tboard(data):
    """分析T字板分钟数据，提取关键指标"""
    m1 = data.get('min1', [])
    if len(m1) < 10:
        return None

    first = m1[0]
    last = m1[-1]
    lowest = min(m1, key=lambda x: x['l'])
    highest = max(m1, key=lambda x: x['h'])

    # Find the dip (first time price goes significantly below open)
    open_p = first['o']
    dip_bar = None
    for b in m1:
        if b['l'] < open_p * 0.97:  # drop > 3% from open
            dip_bar = b
            break
    if dip_bar is None:
        for b in m1:
            if b['l'] < open_p * 0.99:
                dip_bar = b
                break

    # Find re-seal (first bar after dip where price returns to limit-up)
    re_seal = None
    if dip_bar:
        dip_idx = m1.index(dip_bar)
        limit_price = open_p  # limit-up price = open for T-board
        for b in m1[dip_idx+1:]:
            if b['c'] >= limit_price * 0.998:
                re_seal = b
                break

    return {
        'code': data['code'],
        'date': data['date'],
        'open': open_p,
        'close': last['c'],
        'dip_low': lowest['l'],
        'dip_time': lowest['t'] if lowest else '',
        'dip_pct': round((open_p - lowest['l']) / open_p * 100, 2),
        'dip_duration_min': 0,  # will compute below
        're_seal_time': re_seal['t'] if re_seal else '',
        'is_fully_sealed': last['c'] >= open_p * 0.998,
        'total_volume_1min': sum(b['v'] for b in m1),
    }


# ============================================================
# MAIN
# ============================================================
def main(date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    print(f"\n{'='*60}")
    print(f"T字板分钟K线捕获 — {date_str}")
    print(f"{'='*60}")

    # Step 1-2: Get limit-up pool and filter T-boards
    print("\n[1/3] 拉取涨停池...")
    zt_pool = get_today_zt_pool(date_str.replace('-', ''))

    t_boards = [s for s in zt_pool if is_t_board(s)]
    regular_zt = [s for s in zt_pool if not is_t_board(s)]

    print(f"  涨停: {len(zt_pool)} 只")
    print(f"  T字板(炸板回封): {len(t_boards)} 只")
    print(f"  普通涨停: {len(regular_zt)} 只")

    if t_boards:
        print(f"\n  T字板列表:")
        for t in t_boards:
            print(f"    {t['code']} {t['name']:<8} "
                  f"封板{t['first_seal']} 炸{t['break_times']}次 "
                  f"末封{t['last_seal']} {t['zt_stat']}")

    # Step 3: Download minute data
    print(f"\n[2/3] 下载分钟K线...")
    analyses = []
    for t in t_boards:
        code = t['code']
        name = t['name']
        print(f"  {code} {name}...", end=' ')
        try:
            data = download_tboard_minute(code, date_str)
            m1_n = len(data.get('min1', []))
            m5_n = len(data.get('min5', []))
            print(f"m1={m1_n} m5={m5_n}")

            if m1_n > 0:
                analysis = analyze_tboard(data)
                if analysis:
                    analysis['name'] = name
                    analysis['zt_info'] = t
                    analyses.append(analysis)
        except Exception as e:
            print(f"FAIL: {e}")
        time.sleep(0.3)

    # Step 4: Print analysis
    print(f"\n[3/3] T字板分钟分析:")
    if analyses:
        print(f"  {'代码':<8} {'名称':<8} {'开盘':>7} {'最低':>7} {'跌幅%':>7} "
              f"{'跳水时间':<10} {'回封时间':<10} {'封死':>4}")
        print(f"  {'-'*70}")
        for a in analyses:
            print(f"  {a['code']:<8} {a.get('name',''):<8} {a['open']:>7.2f} "
                  f"{a['dip_low']:>7.2f} {a['dip_pct']:>6.1f}% "
                  f"{a['dip_time'][-6:]:<10} {a['re_seal_time'][-6:]:<10} "
                  f"{'Y' if a['is_fully_sealed'] else 'N':>4}")
    else:
        print("  (无T字板或分钟数据未就绪)")

    # Save summary
    summary = {
        'date': date_str,
        'zt_total': len(zt_pool),
        't_board_count': len(t_boards),
        't_boards': t_boards,
        'analyses': analyses,
    }
    summary_path = OUT_DIR / f'_summary_{date_str}.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    total_files = len(list(OUT_DIR.glob('[0-9]*.json')))
    print(f"\n总分钟数据文件: {total_files}")
    print(f"输出目录: {OUT_DIR}")

    return summary


if __name__ == '__main__':
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(date_arg)
