"""
K线存量修复 — 回填追加行缺失字段 (2026-08-19)
问题: 腾讯qfq追加行缺 pct_change/turnover_pct/amount_10k_cny
   → 3年连板统计等下游对追加行判涨停失效
方案: 腾讯qfq重拉100天, 序列内计算pct_change回填;
      turnover/amount 从 data/zt_pool/ 近期涨停池快照回填(池内股票才有)
用法: python scripts/daily/backfill_kline_fields.py
"""
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIRS = [os.path.join(BASE, 'data', 'kline_data'),
              os.path.join(BASE, 'data', 'backtest_kline')]
POOL_DIR = os.path.join(BASE, 'data', 'zt_pool')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def read_json(p):
    for enc in ('utf-8', 'gbk'):
        try:
            with open(p, encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def load_pool_map():
    """{code: {date: {turnover, amount}}} 从近期涨停池快照"""
    pm = defaultdict(dict)
    if not os.path.exists(POOL_DIR):
        return pm
    for fn in os.listdir(POOL_DIR):
        if not fn.endswith('.json'):
            continue
        date = fn.replace('.json', '')
        date = f'{date[:4]}-{date[4:6]}-{date[6:]}'   # YYYYMMDD → YYYY-MM-DD
        pool = read_json(os.path.join(POOL_DIR, fn))
        stocks = pool if isinstance(pool, list) else (pool or {}).get('stocks', [])
        for s in stocks or []:
            code = str(s.get('code', ''))
            if not code:
                continue
            pm[code][date] = {
                'turnover': round(float(s.get('turnover', 0) or 0), 2),
                'amount': round(float(s.get('amount', 0) or 0) / 10000, 2),  # 元→万元
            }
    return pm


def qfq_bars(code):
    """腾讯qfq日K 100天 → {date: (open, close)}"""
    mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
    url = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{code},day,,,100,qfq'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode('utf-8'))
    node = (d.get('data', {}).get(f'{mkt}{code}', {}) or {})
    rows = node.get('qfqday') or []
    if not rows:
        # 无除权史的股票腾讯不返回qfqday, 数据在day键 (无除权时qfq≡day, 口径自洽)
        rows = node.get('day') or []
    return {r[0]: (float(r[1]), float(r[2])) for r in rows}


def backfill_file(path, pool_map):
    raw = read_json(path)
    if raw is None:
        return 'bad_file'
    is_dict_fmt = isinstance(raw, dict) and 'data' in raw
    rows = raw.get('data', raw) if is_dict_fmt else raw
    if not rows:
        return 'empty'

    none_idx = [i for i, r in enumerate(rows)
                if isinstance(r, dict) and r.get('pct_change') is None]
    if not none_idx:
        return 'ok'

    code = (raw.get('metadata') or {}).get('code') if is_dict_fmt else os.path.basename(path).replace('.json', '')
    if not code:
        return 'no_code'

    # 腾讯qfq重拉, 序列内计算pct_change
    try:
        bars = qfq_bars(code)
    except Exception:
        return 'fetch_fail'
    if not bars:
        return 'fetch_empty'

    filled = 0
    sorted_dates = sorted(bars.keys())
    for i in none_idx:
        row = rows[i]
        date = row.get('date', '')
        if date not in bars:
            continue
        idx = sorted_dates.index(date)
        if idx > 0:
            prev_close = bars[sorted_dates[idx - 1]][1]
            if prev_close:
                pct = round((float(row['close']) - prev_close) / prev_close * 100, 2)
                row['pct_change'] = pct
                filled += 1
        # turnover/amount 从池快照补
        if date in pool_map.get(code, {}):
            pm = pool_map[code][date]
            if row.get('turnover_pct') is None and pm.get('turnover'):
                row['turnover_pct'] = pm['turnover']
            if row.get('amount_10k_cny') is None and pm.get('amount'):
                row['amount_10k_cny'] = pm['amount']

    if filled:
        if is_dict_fmt:
            raw['data'] = rows
            md = raw.get('metadata') or {}
            md['fields_backfilled'] = 'pct_change+turnover+amount (2026-08-19)'
            raw['metadata'] = md
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(raw, f, ensure_ascii=False)
        return f'filled {filled}'
    return 'no_change'


def main():
    pool_map = load_pool_map()
    print(f'池快照映射: {sum(len(v) for v in pool_map.values())} 条')
    total_filled = 0
    stats = defaultdict(int)
    for d in KLINE_DIRS:
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.json') or fn.startswith('._'):
                continue
            path = os.path.join(d, fn)
            result = backfill_file(path, pool_map)
            stats[result if not result.startswith('filled') else 'filled'] += 1
            if result.startswith('filled'):
                total_filled += int(result.split()[1])
            time.sleep(0.15)   # 腾讯限速
    print(f'统计: {dict(stats)}')
    print(f'共回填 pct_change {total_filled} 行')


if __name__ == '__main__':
    main()
