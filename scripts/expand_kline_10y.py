"""
K线扩容 → 新浪API (快, 0.6s/只, 覆盖2013-2026)
过滤: 300/301/688/ST
"""
import json, os, glob, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
SINA_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={}&scale=240&ma=no&datalen=5000"


def sina_code(code):
    return f'sz{code}' if code.startswith(('0', '3')) else f'sh{code}'


def main():
    files = sorted(glob.glob(os.path.join(KLINE_DIR, '*.json')))
    print(f'待处理: {len(files)}只')

    success = 0
    errors = 0
    no_data = 0
    total_rows = 0

    for i, fp in enumerate(files):
        fname = os.path.basename(fp).replace('.json', '')
        parts = fname.rsplit('_', 1)
        if len(parts) == 2 and parts[0] and parts[0] != parts[1]:
            name, code = parts[0], parts[1]
        else:
            code = fname.lstrip('_')
            name = ''

        if not code.isdigit():
            continue
        if code.startswith(('300', '301', '688')):
            continue
        if 'ST' in name.upper():
            continue

        try:
            scode = sina_code(code)
            url = SINA_URL.format(scode)
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            resp = urllib.request.urlopen(req, timeout=15)
            raw = resp.read().decode('gbk')
            data = json.loads(raw)

            if not data:
                no_data += 1
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

            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(rows, f, ensure_ascii=False)
            success += 1
            total_rows += len(rows)

        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f'  Error {name}({code}): {e}')

        if (i + 1) % 100 == 0:
            print(f'  进度: {i+1}/{len(files)} 成功{success} 空{no_data} 错{errors}')

        time.sleep(0.08)

    print(f'\n完成: 成功{success} 空{no_data} 错{errors}')
    print(f'平均: {total_rows/success:.0f}行/只' if success else '')
    # 验证一只
    test_fp = os.path.join(KLINE_DIR, '中京电子_002579.json')
    if os.path.exists(test_fp):
        with open(test_fp) as f:
            k = json.load(f)
        print(f'验证 中京电子: {len(k)}条 {k[0]["date"]}~{k[-1]["date"]}')


if __name__ == '__main__':
    main()
