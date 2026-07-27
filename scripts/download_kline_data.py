import baostock as bs
import json, os, time
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# Stock list: trader's 72 stocks + extra from market scan
# ============================================================
trader_stocks = {
    '赤天化':'600227','亚盛集团':'600108','国星光电':'002449','顺钠股份':'000533',
    '美利云':'000815','宇环数控':'002903','金浦钛业':'000545','郑州煤电':'600121',
    '金正大':'002470','京投发展':'600683','正泰电源':'002150','基蛋生物':'603387',
    '华电辽能':'600396','新日股份':'603787','舒华体育':'605299','新能泰山':'000720',
    '美诺华':'603538','津药药业':'600488','安徽建工':'600502','力诺药包':'301188',
    '星辉环材':'300834','中工国际':'002051','康盛股份':'002418','新朋股份':'002328',
    '圣阳股份':'002580','康恩贝':'600572','昂利康':'002940','蜀道装备':'300540',
    '圣龙股份':'603178','九鼎新材':'002201','东望时代':'600052','水发燃气':'603318',
    '飞南资源':'301500','宝光股份':'600379','金螳螂':'002081','波导股份':'600130',
    '深圳华强':'000062','大唐发电':'601991','蒙娜丽莎':'002918','滨化股份':'601678',
    '合肥城建':'002208','华能蒙电':'600863','达实智能':'002421','合百集团':'000417',
    '安德利':'605198','肯特股份':'301591','香江控股':'600162','泓淋电力':'301439',
    '方大集团':'000055','广西能源':'600310','天洋新材':'603330','龙源技术':'300105',
    '金安国纪':'002636','天地源':'600665','翔鹭钨业':'002842','金钼股份':'601958',
    '盛龙股份':'001257','立航科技':'603261','黄河旋风':'600172','世名科技':'300522',
    '长裕集团':'603407','宏柏新材':'605366','兴业科技':'002674','安洁科技':'002635',
    '雷赛智能':'002979','先锋新材':'300163','恒尚节能':'603137','同兴达':'002845',
    '立方制药':'003020','哈药股份':'600664','立新能源':'001258','长缆科技':'002879',
}

# Additional stocks from market scan (Friday 07/24 LU stocks not in trader list)
extra_stocks = {
    '爱丽家居':'603221','汉缆股份':'002498','长城军工':'601606',
    '宝塔实业':'000595','孚日股份':'002083','中电鑫龙':'002298',
    '威派格':'603956','深物业A':'000011','建设机械':'600984',
    '中岩大地':'003001','湖南天雁':'600698','太阳电缆':'002300',
    '盈方微':'000670','合百集团':'000417','狮头股份':'600539',
    '华银电力':'600744',
}

all_stocks = {**trader_stocks, **extra_stocks}
print(f'Total stocks to download: {len(all_stocks)}')

# ============================================================
# Setup folders
# ============================================================
base = r'C:\Users\Davis\Desktop\主升浪'
daily_base = os.path.join(base, '每日收盘数据')
os.makedirs(daily_base, exist_ok=True)

START = '2026-03-01'
END = '2026-07-24'

# ============================================================
# Download all K-line data
# ============================================================
bs.login()
all_data = defaultdict(dict)  # date -> {code/name -> row}
stock_data_map = {}  # code/name -> [rows]
errors = []
success = 0

for name, code in all_stocks.items():
    try:
        if code.startswith('6'): bs_code = f'sh.{code}'
        else: bs_code = f'sz.{code}'

        rs = bs.query_history_k_data_plus(bs_code,
            'date,open,high,low,close,volume',
            start_date=START, end_date=END,
            frequency='d', adjustflag='2')

        if rs.error_code != '0':
            errors.append((name, code, rs.error_msg))
            continue

        rows = []
        while rs.next():
            row = rs.get_row_data()
            rows.append(row)
            dt = row[0]
            def sf(s): return float(s) if s and s != '' else 0.0
            all_data[dt][code] = {
                'name': name, 'open': sf(row[1]), 'high': sf(row[2]),
                'low': sf(row[3]), 'close': sf(row[4]), 'volume': sf(row[5])
            }

        if len(rows) < 20:
            errors.append((name, code, f'Only {len(rows)} bars'))
            continue

        stock_data_map[f'{name}_{code}'] = rows
        success += 1

        if success % 20 == 0:
            print(f'  Downloaded {success}/{len(all_stocks)}...')

    except Exception as e:
        errors.append((name, code, str(e)))

bs.logout()
print(f'Download complete: {success} success, {len(errors)} errors')

# ============================================================
# Save per-stock files
# ============================================================
stock_dir = os.path.join(base, 'kline_data')
os.makedirs(stock_dir, exist_ok=True)

for key, rows in stock_data_map.items():
    fpath = os.path.join(stock_dir, f'{key}.json')
    data = []
    for r in rows:
        def safe_float(s): return float(s) if s and s != '' else 0.0
        data.append({
            'date': r[0], 'open': safe_float(r[1]), 'high': safe_float(r[2]),
            'low': safe_float(r[3]), 'close': safe_float(r[4]), 'volume': safe_float(r[5])
        })
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
print(f'Saved {len(stock_data_map)} per-stock files to {stock_dir}')

# ============================================================
# Save per-date files in 每日收盘数据/YYYY-MM-DD/
# ============================================================
dates_saved = 0
for dt, stocks in sorted(all_data.items()):
    date_dir = os.path.join(daily_base, dt)
    os.makedirs(date_dir, exist_ok=True)
    fpath = os.path.join(date_dir, 'daily_data.json')
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False)
    dates_saved += 1
print(f'Saved {dates_saved} daily snapshots to {daily_base}')

# ============================================================
# Save stock list index
# ============================================================
index_path = os.path.join(daily_base, 'stock_index.json')
with open(index_path, 'w', encoding='utf-8') as f:
    json.dump(all_stocks, f, ensure_ascii=False)
print(f'Stock index: {index_path}')

if errors:
    print(f'\nErrors ({len(errors)}):')
    for name, code, msg in errors[:10]:
        print(f'  {name}({code}): {msg}')

print('\nDone!')
