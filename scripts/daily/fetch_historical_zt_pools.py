"""
历史涨停池批量拉取
区间: 2026-03-04 → 2026-08-04
数据源: 东财 push2ex (支持历史日期)
输出: data/zt_pool_history/{YYYYMMDD}.json
可续传: 跳过已有文件
"""
import json, os, sys, time as _time, random as _random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

START = '2026-03-04'
END = '2026-08-04'
OUT_DIR = os.path.join(BASE, 'data', 'zt_pool_history')

# ── 东财API ──
import requests
ZT_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
ZT_SESSION = None
ZT_LAST = [0.0]

def _zt_get(url, params=None, headers=None, timeout=15):
    global ZT_SESSION
    if ZT_SESSION is None:
        ZT_SESSION = requests.Session()
        ZT_SESSION.headers.update({"User-Agent": ZT_UA})
    wait = 1.0 - (_time.time() - ZT_LAST[0])
    if wait > 0: _time.sleep(wait + _random.uniform(0.1, 0.5))
    try:
        return ZT_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        ZT_LAST[0] = _time.time()


def fetch_day(date_yyyymmdd):
    """拉取一天涨停池，返回原始列表(含300/688)"""
    url = "https://push2ex.eastmoney.com/getTopicZTPool"
    params = {"ut": "7eea3edcaed734bea9cbfc24409ed989",
              "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": "fbt:asc",
              "date": date_yyyymmdd}
    headers = {"User-Agent": ZT_UA, "Referer": "https://quote.eastmoney.com/"}

    try:
        r = _zt_get(url, params=params, headers=headers, timeout=15)
        data = r.json()
        pool = (data.get("data") or {}).get("pool") or []

        result = []
        for p in pool:
            code = p.get("c", "")
            ft = p.get("fbt", 0)
            lt = p.get("lbt", 0)
            result.append({
                'code': code,
                'name': p.get("n", ""),
                'price': p.get("p", 0) / 1000 if p.get("p", 0) > 100 else p.get("p", 0),
                'pct': round(p.get("zdp", 0), 2),
                'turnover': round(p.get("hs", 0), 2),
                'limit_days': p.get("days", 1),
                'first_seal': f"{str(ft).zfill(6)[:2]}:{str(ft).zfill(6)[2:4]}:{str(ft).zfill(6)[4:6]}",
                'last_seal': f"{str(lt).zfill(6)[:2]}:{str(lt).zfill(6)[2:4]}:{str(lt).zfill(6)[4:6]}",
                'seal_fund': p.get("fund", 0),
                'break_times': p.get("zbc", 0),
                'industry': p.get("hybk", ""),
                'amount': p.get("amount", 0),
                'float_cap': p.get("f20", 0),
                'excluded': code.startswith(('300', '301', '688', '8', '9')),
            })
        return result
    except Exception as e:
        print(f'  [ERROR] {date_yyyymmdd}: {e}')
        return None


def get_trading_days():
    days = []
    d = datetime.strptime(START, '%Y-%m-%d')
    ed = datetime.strptime(END, '%Y-%m-%d')
    while d <= ed:
        if d.weekday() < 5:
            days.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    return days


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    trading_days = get_trading_days()
    print(f'历史涨停池拉取: {START} → {END}')
    print(f'交易日: {len(trading_days)} 天')
    print(f'输出: {OUT_DIR}/')
    print()

    success = 0
    skipped = 0
    failed = 0
    total_stocks = 0
    unique_codes = set()

    for i, day in enumerate(trading_days):
        yyyymmdd = day.replace('-', '')
        out_path = os.path.join(OUT_DIR, f'{yyyymmdd}.json')

        if os.path.exists(out_path):
            # Already fetched — still count codes
            try:
                with open(out_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                for s in existing:
                    unique_codes.add(s['code'])
                skipped += 1
                continue
            except:
                pass  # Corrupted, re-fetch

        pool = fetch_day(yyyymmdd)
        if pool is None:
            failed += 1
            print(f'  [{i+1}/{len(trading_days)}] {day} ← FAILED')
            continue

        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(pool, f, ensure_ascii=False, indent=1)

        for s in pool:
            unique_codes.add(s['code'])

        eligible = sum(1 for s in pool if not s['excluded'])
        success += 1
        total_stocks += len(pool)

        if (i + 1) % 10 == 0 or i == 0:
            print(f'  [{i+1}/{len(trading_days)}] {day}: {len(pool)}只'
                  f'(可用{eligible}) | 累计唯一: {len(unique_codes)}')

    print()
    print(f'完成! 成功:{success} 跳过:{skipped} 失败:{failed}')
    print(f'历史池唯一标的: {len(unique_codes)} 只')
    print(f'当前缓存标的: 242 只 → 覆盖提升 {len(unique_codes)/242:.1f}x')

    # Save code manifest for K-line fetch
    manifest = sorted(unique_codes)
    manifest_path = os.path.join(BASE, 'data', 'backtest_codes.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
    print(f'标的清单已保存: {manifest_path}')


if __name__ == '__main__':
    main()
