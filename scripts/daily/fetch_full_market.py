"""
全市场K线下载 — 8877只A股, 3年, 用于统计涨停活跃度
首次运行1-2小时, 断点续传
"""
import baostock as bs
import json, os, sys, time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE, 'data', 'full_market_kline')
META_PATH = os.path.join(BASE, 'data', 'full_market_meta.json')
START = '2023-08-04'
END = '2026-08-05'

os.makedirs(OUT_DIR, exist_ok=True)

def get_all_codes():
    """获取全A股代码列表"""
    rs = bs.query_stock_basic()
    codes = []
    while rs.next():
        row = rs.get_row_data()
        bs_code, name, ipo_date, out_date, stock_type, status = row
        # type=1是股票, 排除退市/指数/ETF/B股/科创板/北交所
        code = bs_code.replace('sh.', '').replace('sz.', '')
        if stock_type == '1' and status == '1' and not code.startswith(('8', '9', '4', '688', '300', '301')):
            codes.append((code, name))
    return codes

def download_one(bs, code):
    """下载单只股票K线(只取close), 返回(date,close)列表"""
    bc = f'sh.{code}' if code.startswith('6') else f'sz.{code}'
    try:
        rs = bs.query_history_k_data_plus(bc, "date,close",
            start_date=START, end_date=END, frequency="d", adjustflag="2")
        rows = []
        while rs.next():
            r = rs.get_row_data()
            if r[0] and r[1]:
                rows.append((r[0], round(float(r[1]), 2)))
        return rows if len(rows) >= 25 else None
    except:
        return None

def main():
    bs.login()
    codes = get_all_codes()
    bs.logout()
    print(f'全A股: {len(codes)} 只')

    # 加载进度
    done = set()
    if os.path.exists(META_PATH):
        with open(META_PATH, 'r') as f:
            done = set(json.load(f))

    remaining = [(c, n) for c, n in codes if c not in done]
    print(f'已完成: {len(done)}, 剩余: {len(remaining)}')

    if not remaining:
        print('全部完成!')
        return

    bs.login()
    t0 = time.time()
    new_done = 0

    for i, (code, name) in enumerate(remaining):
        out_path = os.path.join(OUT_DIR, f'{code}.json')
        if os.path.exists(out_path):
            done.add(code)
            continue

        rows = download_one(bs, code)
        if rows:
            with open(out_path, 'w') as f:
                json.dump(rows, f, ensure_ascii=False)
        done.add(code)
        new_done += 1

        # 每100只保存进度
        if (i+1) % 100 == 0:
            with open(META_PATH, 'w') as f:
                json.dump(sorted(done), f)
            elapsed = time.time() - t0
            rate = (i+1) / elapsed
            eta = (len(remaining) - i - 1) / rate
            print(f'  [{len(done)}/{len(codes)}] {rate:.1f}只/秒 ETA:{eta/60:.0f}分')

    bs.logout()

    # 最终保存
    with open(META_PATH, 'w') as f:
        json.dump(sorted(done), f)

    total = len([f for f in os.listdir(OUT_DIR) if f.endswith('.json')])
    print(f'\n完成! K线文件: {total} 只')

if __name__ == '__main__':
    main()
