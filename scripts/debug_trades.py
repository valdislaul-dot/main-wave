import json, openpyxl
from datetime import datetime, timedelta

with open(r'C:\Users\Davis\Desktop\主升浪\stock_data.json','r',encoding='utf-8') as f:
    stock_data = json.load(f)

def ed(s): return datetime(1899,12,30) + timedelta(days=int(s))

wb = openpyxl.load_workbook(r'C:\Users\Davis\Desktop\主升浪\副本主升浪.xlsx')
ws = wb['Sheet1']
records = []
for row in ws.iter_rows(min_row=2, values_only=True):
    for i in range(0, 10, 2):
        dv = row[i]; sv = row[i+1] if i+1 < len(row) else None
        if dv is not None and dv != '' and sv is not None and sv != '':
            records.append((int(dv), sv.strip()))
records.sort(key=lambda x: x[0])

stocks_map = {}
for n, c in [
    ('赤天化','600227'),('亚盛集团','600108'),('国星光电','002449'),('顺钠股份','000533'),
    ('美利云','000815'),('宇环数控','002903'),('金浦钛业','000545'),('郑州煤电','600121'),
    ('金正大','002470'),('京投发展','600683'),('正泰电源','002150'),('基蛋生物':'603387'),
    ('华电辽能','600396'),('新日股份','603787'),('舒华体育','605299'),('新能泰山','000720'),
    ('美诺华','603538'),('津药药业','600488'),('安徽建工','600502'),('力诺药包','301188'),
    ('星辉环材','300834'),('中工国际','002051'),('康盛股份','002418'),('新朋股份','002328'),
    ('圣阳股份','002580'),('康恩贝','600572'),('昂利康','002940'),('蜀道装备','300540'),
    ('圣龙股份','603178'),('九鼎新材','002201'),('东望时代','600052'),('水发燃气','603318'),
    ('飞南资源','301500'),('宝光股份','600379'),('金螳螂','002081'),('波导股份','600130'),
    ('深圳华强','000062'),('大唐发电','601991'),('蒙娜丽莎','002918'),('滨化股份','601678'),
    ('合肥城建','002208'),('华能蒙电','600863'),('达实智能','002421'),('合百集团','000417'),
    ('安德利','605198'),('肯特股份','301591'),('香江控股','600162'),('泓淋电力':'301439'),
    ('方大集团','000055'),('广西能源','600310'),('天洋新材','603330'),('龙源技术','300105'),
    ('金安国纪','002636'),('天地源','600665'),('翔鹭钨业','002842'),('金钼股份','601958'),
    ('盛龙股份','001257'),('立航科技','603261'),('黄河旋风','600172'),('世名科技','300522'),
    ('长裕集团','603407'),('宏柏新材','605366'),('兴业科技','002674'),('安洁科技','002635'),
    ('雷赛智能','002979'),('先锋新材','300163'),('恒尚节能','603137'),('同兴达':'002845'),
    ('立方制药','003020'),('哈药股份','600664'),('立新能源','001258'),('长缆科技','002879'),
]:
    stocks_map[n] = c

def get_lp(code):
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10

def is_lu(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0: return False
    return close >= round(prev_close * (1 + lpct), 2) - 0.005

price_db = {}
for name, code in stocks_map.items():
    if name not in stock_data: continue
    price_db[name] = {}
    lpct = get_lp(code)
    klines = stock_data[name]
    prev_close = None
    for i, k in enumerate(klines):
        dt = k['day']
        o = float(k['open']); c = float(k['close'])
        entry = {
            'open': o, 'close': c, 'high': float(k['high']), 'low': float(k['low']),
            'is_limit_up': False, 'prev_close': prev_close,
        }
        if prev_close and prev_close > 0:
            entry['is_limit_up'] = is_lu(c, prev_close, lpct)
        price_db[name][dt] = entry
        prev_close = c

timeline = []
for s, st in records:
    d = ed(s)
    timeline.append((d.strftime('%Y-%m-%d'), st))
all_dates = sorted(set(d for d, _ in timeline))

out_path = r'C:\Users\Davis\Desktop\主升浪\debug_output.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("逐笔交易验证 (前10笔)\n")
    f.write("=" * 80 + "\n\n")

    INIT = 300000
    pos_list = []; cash = INIT
    gap_threshold = 0  # strict: any negative gap = low open

    for didx, date in enumerate(all_dates[:50]):  # first 50 days only
        rec = dict(timeline).get(date, '休息')
        pd_ = all_dates[didx - 1] if didx > 0 else None

        # SELL
        for pos in pos_list[:]:
            n = pos['name']; bp_ = pos['buy_price']
            if n not in price_db or date not in price_db[n]:
                f.write(f"  WARNING: {n} not in price_db on {date}\n")
                pos_list.remove(pos); continue

            it = price_db[n][date]
            ip = price_db[n].get(pd_) if pd_ else None

            prev_lu = ip['is_limit_up'] if ip else False
            opens_low = False
            gap_pct = 0
            if ip:
                pcv = ip['close']
                if pcv > 0:
                    gap_pct = (it['open'] - pcv) / pcv * 100
                    if gap_pct <= gap_threshold:
                        opens_low = True

            sell_reason = ""
            if not prev_lu and opens_low:
                sell_reason = f"不涨停+低开(gap={gap_pct:+.1f}%)"
            elif not prev_lu:
                sell_reason = f"不涨停"
            elif opens_low:
                sell_reason = f"低开(gap={gap_pct:+.1f}%)"

            if not prev_lu or opens_low:
                sp = it['open']
                if sp > 0:
                    pnl = (sp - bp_) / bp_ * 100
                    hold_days = (datetime.strptime(date, '%Y-%m-%d') -
                                datetime.strptime(pos['buy_date'], '%Y-%m-%d')).days
                    f.write(f"  SELL {n} @{sp:.2f} (buy @{bp_:.2f}) PnL={pnl:+.1f}% "
                            f"hold={hold_days}d reason={sell_reason}\n")
                    cash += sp * pos['shares']
                    pos_list.remove(pos)
                else:
                    f.write(f"  WARNING: {n} bad sell price on {date}\n")

        # BUY
        if rec != '休息' and len(pos_list) == 0:
            bn = rec
            if bn in price_db and date in price_db[bn]:
                bp_ = price_db[bn][date]['open']
                # Check if T-1 was limit-up
                kls = stock_data[bn]
                idxs = [i for i, k in enumerate(kls) if k['day'] == date]
                t1_lu = False
                if idxs and idxs[0] >= 1:
                    t1_date = kls[idxs[0] - 1]['day']
                    if t1_date in price_db[bn]:
                        t1_lu = price_db[bn][t1_date]['is_limit_up']
                sh = int(cash / bp_ / 100) * 100
                if sh > 0:
                    cash -= sh * bp_
                    pos_list.append({'name': bn, 'buy_date': date, 'buy_price': bp_, 'shares': sh})
                    f.write(f"BUY  {bn} @{bp_:.2f} x{shares} (cash={cash:,.0f}) "
                            f"T-1_LU={t1_lu} date={date}\n")
            else:
                f.write(f"  SKIP {bn} on {date}: not in price_db\n")

        pv = sum(p['shares'] * price_db.get(p['name'], {}).get(date, {}).get('close', p['buy_price']) for p in pos_list)
        if rec != '休息' or pos_list:
            f.write(f"  DAY {date} rec={rec} cash={cash:,.0f} pv={pv:,.0f} total={cash+pv:,.0f} held={[(p['name'],p['buy_date']) for p in pos_list]}\n")

    f.write(f"\nFinal after 50 days: cash={cash:,.0f} pv={pv:,.0f} total={cash+pv:,.0f}\n")

print(f"Debug output: {out_path}")
