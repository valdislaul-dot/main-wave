"""
批量下载回测K线 — 为历史涨停池中的标的补全K线数据
数据源: 腾讯fqkline (前复权, count-only形态拉~900根后本地过滤区间)
输出: data/backtest_kline/{code}.json (dict格式带metadata)
可续传: 跳过已有文件
"""
import json, os, sys, time as _time, urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

START = '2023-08-04'
END = '2026-08-04'
OUT_DIR = os.path.join(BASE, 'data', 'backtest_kline')
FETCH_COUNT = 900  # ~3.6年交易日, 含缓冲


def get_code_list():
    """获取需要下载的标的列表 (从backtest_codes.json + 已有kline_data)"""
    codes = set()

    # 1. 从历史涨停池清单
    manifest_path = os.path.join(BASE, 'data', 'backtest_codes.json')
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            codes.update(json.load(f))

    # 2. 从现有kline_data
    kline_dir = os.path.join(BASE, 'data', 'kline_data')
    if os.path.exists(kline_dir):
        for fn in os.listdir(kline_dir):
            if fn.endswith('.json'):
                parts = fn.replace('.json', '').rsplit('_', 1)
                if len(parts) == 2:
                    codes.add(parts[1])

    return sorted(codes)


def fetch_kline(code):
    """腾讯fqkline前复权, count-only形态拉最近~900根, 本地过滤START~END区间"""
    mkt = 'sz' if code.startswith(('0', '3')) else 'sh'
    url = (f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
           f'?param={mkt}{code},day,,,{FETCH_COUNT},qfq')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode('utf-8'))
        rows = (d.get('data', {}).get(f'{mkt}{code}', {}) or {}).get('qfqday') or []
    except Exception:
        return None

    out = []
    for r in rows:
        if START <= r[0] <= END:
            # 腾讯格式: [date, open, close, high, low, volume(手)]
            try:
                out.append({
                    'date': r[0],
                    'open': round(float(r[1]), 2),
                    'high': round(float(r[3]), 2),
                    'low': round(float(r[4]), 2),
                    'close': round(float(r[2]), 2),
                    'volume': round(float(r[5]) * 100, 2),
                })
            except (ValueError, IndexError):
                continue
    return out if len(out) >= 25 else None


def main():
    codes = get_code_list()
    print(f'批量下载K线: {len(codes)} 只标的')
    print(f'区间: {START} → {END}')
    print(f'输出: {OUT_DIR}/')
    print()

    os.makedirs(OUT_DIR, exist_ok=True)

    new_count = 0
    skip_count = 0
    fail_count = 0
    t0 = _time.time()

    for i, code in enumerate(codes):
        out_path = os.path.join(OUT_DIR, f'{code}.json')

        if os.path.exists(out_path):
            skip_count += 1
            continue

        klines = fetch_kline(code)

        if klines:
            mkt = 'SZ' if code.startswith(('0', '3')) else 'SH'
            out_data = {
                'metadata': {
                    'code': code,
                    'market': mkt,
                    'period': 'daily',
                    'adjustment': 'qfq',
                    'source': 'Tencent fqkline',
                    'source_endpoint': 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                    'requested_start': START,
                    'requested_end': END,
                    'record_count': len(klines),
                    'order': 'ascending',
                    'downloaded_at': datetime.now().isoformat(),
                },
                'data': klines,
            }
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(out_data, f, ensure_ascii=False)
            new_count += 1
        else:
            fail_count += 1

        # Progress every 50 stocks or every 10 seconds
        if (i + 1) % 50 == 0 or (i == len(codes) - 1):
            elapsed = _time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(codes) - i - 1) / rate if rate > 0 else 0
            print(f'  [{i+1}/{len(codes)}] 新增:{new_count} 跳过:{skip_count} '
                  f'失败:{fail_count} | {rate:.1f}只/秒 ETA:{eta:.0f}s')

    total_files = len([f for f in os.listdir(OUT_DIR) if f.endswith('.json')])
    print(f'\n完成! K线缓存: {total_files} 只')
    print(f'新增: {new_count} | 跳过: {skip_count} | 失败: {fail_count}')


if __name__ == '__main__':
    main()
