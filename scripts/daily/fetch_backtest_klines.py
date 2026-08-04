"""
批量下载回测K线 — 为历史涨停池中的标的补全K线数据
数据源: baostock (前复权, 180天)
输出: data/backtest_kline/{code}.json
可续传: 跳过已有文件
"""
import json, os, sys, time as _time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

START = '2023-08-04'
END = '2026-08-04'
OUT_DIR = os.path.join(BASE, 'data', 'backtest_kline')


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


def baostock_login():
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != '0':
            print(f'  baostock login failed: {lg.error_msg}')
            return None
        return bs
    except Exception as e:
        print(f'  baostock import failed: {e}')
        return None


def fetch_kline(bs, code, days=200):
    """下载单只股票K线, 前复权"""
    # Determine exchange prefix
    if code.startswith('6'):
        bs_code = f'sh.{code}'
    else:
        bs_code = f'sz.{code}'

    end_date = END  # YYYY-MM-DD
    # 3年回测需要~750交易日, 加60天缓冲
    start_date = (datetime.strptime(START, '%Y-%m-%d') - timedelta(days=70)).strftime('%Y-%m-%d')

    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2"  # 前复权
        )

        if rs.error_code != '0':
            return None

        rows = []
        while rs.next():
            row = rs.get_row_data()
            if row[0] == '':
                continue
            try:
                rows.append({
                    'date': row[0],
                    'open': round(float(row[1]), 2),
                    'high': round(float(row[2]), 2),
                    'low': round(float(row[3]), 2),
                    'close': round(float(row[4]), 2),
                    'volume': float(row[5]) if row[5] != '' else 0.0
                })
            except:
                continue

        return rows if len(rows) >= 25 else None
    except:
        return None


def main():
    codes = get_code_list()
    print(f'批量下载K线: {len(codes)} 只标的')
    print(f'区间: {START} → {END}')
    print(f'输出: {OUT_DIR}/')
    print()

    bs = baostock_login()
    if bs is None:
        print('无法连接baostock, 退出')
        return

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

        klines = fetch_kline(bs, code)

        if klines:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(klines, f, ensure_ascii=False)
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

    bs.logout()

    total_files = len([f for f in os.listdir(OUT_DIR) if f.endswith('.json')])
    print(f'\n完成! K线缓存: {total_files} 只')
    print(f'新增: {new_count} | 跳过: {skip_count} | 失败: {fail_count}')
    print(f'回测可用标的: {total_files} (原242只 → {total_files}只)')


if __name__ == '__main__':
    main()
