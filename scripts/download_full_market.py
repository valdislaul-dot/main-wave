"""
全市场K线下载 → 新浪API (6+年历史)
覆盖所有主板个股(过滤300/301/688/ST), 已有6年数据的跳过
"""
import json, os, glob, time, urllib.request
import akshare as ak

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
SINA_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={}&scale=240&ma=no&datalen=5000"

os.makedirs(KLINE_DIR, exist_ok=True)


def sina_symbol(code):
    return f'sz{code}' if code.startswith(('0', '3')) else f'sh{code}'


def main():
    # 1. 获取全市场股票列表
    print('[1/3] 获取股票列表...')
    df = ak.stock_info_a_code_name()
    stocks = []
    for _, r in df.iterrows():
        code = str(r['code']).zfill(6)
        name = str(r['name'])
        if code.startswith(('300', '301', '688')):
            continue
        if 'ST' in name.upper():
            continue
        if not code.isdigit():
            continue
        stocks.append((code, name))
    print(f'主板个股: {len(stocks)}只')

    # 2. 检查已有6年数据的
    print('[2/3] 检查已有数据...')
    existing = {}
    for fp in glob.glob(os.path.join(KLINE_DIR, '*.json')):
        fn = os.path.basename(fp).replace('.json', '')
        parts = fn.rsplit('_', 1)
        if len(parts) == 2 and parts[0] and parts[0] != parts[1]:
            fname, fcode = parts[0], parts[1]
        else:
            fcode = fn.lstrip('_')
            fname = ''
        if not fcode.isdigit():
            continue
        try:
            with open(fp) as f:
                k = json.load(f)
            # 6年 = ~1500条
            if len(k) >= 1400:
                existing[fcode] = fp  # 已够, 跳过
            else:
                existing[fcode] = None  # 不够, 需要重新下载
        except:
            existing[fcode] = None

    has_enough = sum(1 for v in existing.values() if v)
    need_update = sum(1 for v in existing.values() if v is None)
    new_stocks = [s for s in stocks if s[0] not in existing]
    print(f'已有6年: {has_enough}只 | 需更新: {need_update}只 | 新标的: {len(new_stocks)}只')
    print(f'待下载: {need_update + len(new_stocks)}只')

    # 3. 下载
    print('[3/3] 开始下载...')
    to_download = [(c, n) for c, n in stocks if c not in existing or existing[c] is None]

    success = 0
    errors = 0
    empty = 0

    for i, (code, name) in enumerate(to_download):
        try:
            sym = sina_symbol(code)
            url = SINA_URL.format(sym)
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            req.add_header('Referer', 'https://finance.sina.com.cn/')
            resp = urllib.request.urlopen(req, timeout=15)
            raw = resp.read().decode('gbk')
            data = json.loads(raw)

            if not data or len(data) < 100:
                empty += 1
                continue

            rows = []
            for d in data:
                rows.append({
                    'date': d['day'],
                    'open': round(float(d['open']), 2),
                    'high': round(float(d['high']), 2),
                    'low': round(float(d['low']), 2),
                    'close': round(float(d['close']), 2),
                    'volume': float(d['volume']),
                })

            fpath = os.path.join(KLINE_DIR, f'{name}_{code}.json')
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(rows, f, ensure_ascii=False)
            success += 1

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f'  Error {name}({code}): {e}')

        if (i + 1) % 200 == 0:
            pct = (i + 1) / len(to_download) * 100
            print(f'  进度: {i+1}/{len(to_download)} ({pct:.0f}%) 成功{success} 空{empty} 错{errors}')

        time.sleep(0.06)

    total = len(glob.glob(os.path.join(KLINE_DIR, '*.json')))
    print(f'\n完成: 成功{success} 空{empty} 错{errors}')
    print(f'K线库总量: {total}只')


if __name__ == '__main__':
    main()
