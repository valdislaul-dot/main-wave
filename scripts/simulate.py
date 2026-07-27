import json
import openpyxl
from datetime import datetime, timedelta

# Load stock price data
with open(r'C:\Users\Davis\Desktop\stock_data.json', 'r', encoding='utf-8') as f:
    stock_data = json.load(f)

def excel_to_date(serial):
    return datetime(1899, 12, 30) + timedelta(days=int(serial))

# Load trading record
wb = openpyxl.load_workbook(r'C:\Users\Davis\Desktop\主升浪\副本主升浪.xlsx')
ws = wb['Sheet1']
records = []
for row in ws.iter_rows(min_row=2, values_only=True):
    for i in range(0, 10, 2):
        date_val = row[i]
        stock = row[i+1] if i+1 < len(row) else None
        if date_val is not None and date_val != '' and stock is not None and stock != '':
            records.append((int(date_val), stock.strip()))
records.sort(key=lambda x: x[0])

record_by_date = {}
for serial, stock in records:
    d = excel_to_date(serial)
    record_by_date[d.strftime('%Y-%m-%d')] = stock

# Full stock code mapping
stocks_map = {
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

def get_limit_pct(code):
    if code.startswith('30') or code.startswith('688'):
        return 0.20
    return 0.10

def calc_limit_up(prev_close, limit_pct):
    return round(prev_close * (1 + limit_pct), 2)

def is_limit_up(close, prev_close, limit_pct):
    limit_price = calc_limit_up(prev_close, limit_pct)
    return close >= limit_price - 0.005

# Build price database
price_db = {}
for name, code in stocks_map.items():
    if name not in stock_data:
        continue
    price_db[name] = {}
    limit_pct = get_limit_pct(code)
    klines = stock_data[name]
    prev_close = None
    for k in klines:
        date = k['day']
        o = float(k['open'])
        c = float(k['close'])
        h = float(k['high'])
        l = float(k['low'])
        v = float(k['volume'])
        entry = {
            'open': o, 'close': c, 'high': h, 'low': l, 'volume': v,
            'is_limit_up': False, 'prev_close': prev_close
        }
        if prev_close is not None and prev_close > 0:
            entry['is_limit_up'] = is_limit_up(c, prev_close, limit_pct)
        price_db[name][date] = entry
        prev_close = c

# === SIMULATION ===
INITIAL_CAPITAL = 300000

positions = []
cash = INITIAL_CAPITAL
daily_log = []

all_dates = sorted(set(excel_to_date(s).strftime('%Y-%m-%d') for s, _ in records))

out_path = r'C:\Users\Davis\Desktop\simulation_log.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('='*130 + '\n')
    f.write('逐日持仓状态机模拟\n')
    f.write('='*130 + '\n\n')
    f.write(f'初始资金: {INITIAL_CAPITAL:,.0f}\n\n')

    for date in all_dates:
        record = record_by_date.get(date, '休息')

        # STEP 0: Sell stocks that didn't hit limit-up yesterday
        date_idx = all_dates.index(date)
        prev_date = all_dates[date_idx - 1] if date_idx > 0 else None

        stocks_sold = []
        for pos in positions[:]:
            pos_name = pos['name']
            should_sell = True
            if prev_date and prev_date in price_db.get(pos_name, {}):
                if price_db[pos_name][prev_date]['is_limit_up']:
                    should_sell = False  # 连板持有

            if should_sell:
                if date in price_db.get(pos_name, {}):
                    sell_price = price_db[pos_name][date]['open']
                    proceeds = sell_price * pos['shares']
                    cash += proceeds
                    pnl = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                    stocks_sold.append({
                        'name': pos_name, 'buy_date': pos['buy_date'],
                        'buy_price': pos['buy_price'], 'sell_price': sell_price,
                        'shares': pos['shares'], 'pnl_pct': pnl
                    })
                    positions.remove(pos)

        # STEP 1: Buy new stock
        stock_bought = None
        if record != '休息':
            buy_name = record
            if buy_name in price_db and date in price_db[buy_name]:
                buy_price = price_db[buy_name][date]['open']
                shares = int(cash / buy_price / 100) * 100
                if shares > 0:
                    cost = shares * buy_price
                    cash -= cost
                    positions.append({
                        'name': buy_name, 'buy_date': date,
                        'buy_price': buy_price, 'shares': shares
                    })
                    stock_bought = {'name': buy_name, 'price': buy_price,
                                   'shares': shares, 'cost': cost}

        # Portfolio value
        position_value = 0
        for pos in positions:
            if date in price_db.get(pos['name'], {}):
                position_value += pos['shares'] * price_db[pos['name']][date]['close']
        total_value = cash + position_value

        # Log
        held_names = [f"{p['name']}({p['buy_date']})" for p in positions]
        f.write(f"{date} | 记录={record:6s} | ")
        if stocks_sold:
            for s in stocks_sold:
                f.write(f"卖{s['name']}@{s['sell_price']:.2f}({s['pnl_pct']:+.1f}%) ")
        if stock_bought:
            f.write(f"买{stock_bought['name']}@{stock_bought['price']:.2f}*{stock_bought['shares']} ")
        if not stocks_sold and not stock_bought:
            f.write(f"无操作 ")
        f.write(f"| 持仓={held_names} | 现金={cash:,.0f} | 总资产={total_value:,.0f}\n")

        daily_log.append({
            'date': date, 'record': record, 'held': held_names,
            'cash': cash, 'total': total_value,
            'sold': stocks_sold, 'bought': stock_bought
        })

    final_value = daily_log[-1]['total'] if daily_log else 0
    total_return = (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    f.write(f'\n{"="*130}\n')
    f.write(f'最终资产: {final_value:,.0f} | 总收益率: {total_return:+.1f}%\n')
    f.write(f'最终持仓: {[(p["name"], p["buy_date"]) for p in positions]}\n')
    f.write(f'剩余现金: {cash:,.0f}\n')

print(f'Final portfolio: {final_value:,.0f}')
print(f'Total return: {total_return:+.1f}%')
print(f'Log: {out_path}')
