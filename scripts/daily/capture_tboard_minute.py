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
    """2026-08-20起: 复用 zt_pool.fetch_zt_pool_raw (同花顺涨停揭秘, 弃用东财push2ex)"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zt_pool import fetch_zt_pool_raw
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    date_str = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}' if len(date_str) == 8 else date_str
    return fetch_zt_pool_raw(date_str)

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

def download_tboard_minute(code, date_str, reason='tboard'):
    """下载单只T字板/慢推候选的分钟K线 (2026-09-01起含慢推型失败侧样本)"""
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
        'code': code, 'date': date_str, 'capture_reason': reason,
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
            stat = t.get('zt_stat') or f"{t.get('limit_days', 1)}板"
            print(f"    {t['code']} {t['name']:<8} "
                  f"封板{t['first_seal']} 炸{t['break_times']}次 "
                  f"末封{t['last_seal']} {stat}")

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

    # Step 3.5: 慢推型样本采集 (2026-09-01起, 失败侧样本积累)
    # 低开/平开(gap<4%)的竞价池股, 不论最终是否封板 → 2-4周后回测慢推型封板率
    print(f"\n[3.5] 慢推型样本采集(低开/平开, 含失败侧)...")
    slow_collected = 0
    auction_file = BASE / 'data' / 'auction' / f'{date_str}.json'
    if auction_file.exists():
        try:
            with open(auction_file, encoding='utf-8') as f:
                auction = json.load(f)
            tboard_codes = {t['code'] for t in t_boards}
            slow_cands = [s for s in auction.get('stocks', [])
                          if s.get('gap_pct') is not None and s['gap_pct'] < 4
                          and s.get('code') and s['code'] not in tboard_codes]
            for s in slow_cands[:40]:   # 每日上限40只, 防采集量过大
                code = s['code']
                out_file = OUT_DIR / f'{code}_{date_str}.json'
                if out_file.exists():
                    continue
                try:
                    download_tboard_minute(code, date_str, reason='slow_push')
                    slow_collected += 1
                except Exception as e:
                    print(f"  [WARN] {code}: {e}")
                time.sleep(0.25)
            print(f"  低开/平开候选: {len(slow_cands)} 只, 新采集 {slow_collected} 只")
        except Exception as e:
            print(f"  竞价快照读取失败: {e}")
    else:
        print(f"  无竞价快照({auction_file.name}), 跳过")

    # Step 4: Print analysis
    print(f"\n[4/4] T字板分钟分析:")
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
