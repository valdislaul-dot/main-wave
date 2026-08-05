"""
K线数据扩容: → 近10年
遍历 data/kline_data/ 所有文件, 重新下载完整10年历史
只处理需要扩容的(首条日期 > 2019年的)
"""
import baostock as bs
import json, os, glob, time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
CUTOFF_DATE = '2020-01-01'  # 首条晚于这个的才需要扩容


def code_to_bs(code):
    return f'sh.{code}' if code.startswith('6') else f'sz.{code}'


def main():
    files = sorted(glob.glob(os.path.join(KLINE_DIR, '*.json')))
    print(f'K线文件总数: {len(files)}')

    # 找出需要扩容的
    to_expand = []
    for fp in files:
        try:
            with open(fp, encoding='utf-8') as f:
                klines = json.load(f)
        except:
            continue
        if not klines:
            continue
        if klines[0]['date'] > CUTOFF_DATE:
            to_expand.append(fp)

    print(f'需要扩容(首条>{CUTOFF_DATE}): {len(to_expand)}只')
    if not to_expand:
        print('无需扩容')
        return

    # 解析 code
    bs.login()
    success = 0
    errors = 0
    skipped = 0

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365*10)).strftime('%Y-%m-%d')

    for i, fp in enumerate(to_expand):
        fname = os.path.basename(fp).replace('.json', '')
        parts = fname.rsplit('_', 1)
        if len(parts) == 2 and parts[0]:
            name, code = parts[0], parts[1]
        else:
            code = fname.lstrip('_')
            name = ''

        if not code or not code[0].isdigit():
            skipped += 1
            continue

        # 过滤: 创业板/科创板/ST
        if code.startswith(('300', '301', '688')):
            skipped += 1
            continue
        if 'ST' in name.upper() or 'ST' in code.upper():
            skipped += 1
            continue

        bs_code = code_to_bs(code)

        try:
            rs = bs.query_history_k_data_plus(bs_code,
                'date,open,high,low,close,volume',
                start_date=start_date, end_date=end_date,
                frequency='d', adjustflag='2')
            if rs.error_code != '0':
                errors += 1
                continue

            rows = []
            while rs.next():
                r = rs.get_row_data()
                if r[0]:
                    rows.append({
                        'date': r[0],
                        'open': round(float(r[1]), 2),
                        'high': round(float(r[2]), 2),
                        'low': round(float(r[3]), 2),
                        'close': round(float(r[4]), 2),
                        'volume': float(r[5]) if r[5] else 0,
                    })

            if rows:
                with open(fp, 'w', encoding='utf-8') as f:
                    json.dump(rows, f, ensure_ascii=False)
                success += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f'  Error {code}: {e}')

        # 进度
        if (i + 1) % 100 == 0:
            print(f'  进度: {i+1}/{len(to_expand)} 成功{success} 失败{errors}')
        time.sleep(0.05)

    bs.logout()
    print(f'\n完成: 成功{success} 失败{errors} 跳过{skipped}')


if __name__ == '__main__':
    main()
