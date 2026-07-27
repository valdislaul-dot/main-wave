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
    ('金正大','002470'),('京投发展','600683'),('正泰电源','002150'),('基蛋生物','603387'),
    ('华电辽能','600396'),('新日股份','603787'),('舒华体育','605299'),('新能泰山','000720'),
    ('美诺华','603538'),('津药药业','600488'),('安徽建工','600502'),('力诺药包','301188'),
    ('星辉环材','300834'),('中工国际','002051'),('康盛股份','002418'),('新朋股份','002328'),
    ('圣阳股份','002580'),('康恩贝','600572'),('昂利康','002940'),('蜀道装备','300540'),
    ('圣龙股份','603178'),('九鼎新材','002201'),('东望时代','600052'),('水发燃气','603318'),
    ('飞南资源','301500'),('宝光股份','600379'),('金螳螂','002081'),('波导股份','600130'),
    ('深圳华强','000062'),('大唐发电','601991'),('蒙娜丽莎','002918'),('滨化股份','601678'),
    ('合肥城建','002208'),('华能蒙电','600863'),('达实智能','002421'),('合百集团','000417'),
    ('安德利','605198'),('肯特股份','301591'),('香江控股','600162'),('泓淋电力','301439'),
    ('方大集团','000055'),('广西能源','600310'),('天洋新材','603330'),('龙源技术','300105'),
    ('金安国纪','002636'),('天地源','600665'),('翔鹭钨业','002842'),('金钼股份','601958'),
    ('盛龙股份','001257'),('立航科技','603261'),('黄河旋风','600172'),('世名科技','300522'),
    ('长裕集团','603407'),('宏柏新材','605366'),('兴业科技','002674'),('安洁科技','002635'),
    ('雷赛智能','002979'),('先锋新材','300163'),('恒尚节能','603137'),('同兴达','002845'),
    ('立方制药','003020'),('哈药股份','600664'),('立新能源','001258'),('长缆科技','002879'),
]:
    stocks_map[n] = c

def get_lp(code):
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10

def is_lu(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0: return False
    return close >= round(prev_close * (1 + lpct), 2) - 0.005

# Build price DB
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
            'open': o, 'close': c,
            'is_limit_up': False, 'prev_close': prev_close,
            'opens_at_lu': False, 'gap_open_pct': 0,
        }
        if prev_close and prev_close > 0:
            entry['is_limit_up'] = is_lu(c, prev_close, lpct)
            entry['gap_open_pct'] = (o - prev_close) / prev_close * 100
            today_lu_price = round(prev_close * (1 + lpct), 2)
            entry['opens_at_lu'] = (o >= today_lu_price - 0.005)
        price_db[name][dt] = entry
        prev_close = c

timeline = []
for s, st in records:
    d = ed(s); timeline.append((d.strftime('%Y-%m-%d'), st))
all_dates = sorted(set(d for d, _ in timeline))
INIT = 300000
TARGET = 1000000

out_path = r'C:\Users\Davis\Desktop\主升浪\auction_decision_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("=" * 80 + "\n")
    f.write("竞价决策模型: 卖出决定在竞价阶段(9:15-9:25)做出\n")
    f.write("=" * 80 + "\n")
    f.write("「不涨停」= 今日开盘未涨停(未封一字板)\n")
    f.write("「低开」= 今日开盘价 < 昨日收盘价\n")
    f.write("卖出条件: 未涨停开盘 OR 低开 → 开盘价卖出\n")
    f.write("持有条件: 涨停开盘(一字板) AND 不低开 → 继续持有\n\n")

    # Simulate with this interpretation
    pos_list = []; cash = INIT; tlist = []

    for didx, date in enumerate(all_dates):
        rec = dict(timeline).get(date, '休息')
        pd_ = all_dates[didx - 1] if didx > 0 else None

        # SELL: decision made during auction based on TODAY'S indicative open
        for pos in pos_list[:]:
            n = pos['name']; bp_ = pos['buy_price']
            if n not in price_db or date not in price_db[n]:
                pos_list.remove(pos); continue

            it = price_db[n][date]
            ip = price_db[n].get(pd_) if pd_ else None

            # NEW interpretation:
            # 「不涨停」= today NOT opening at limit-up price
            not_at_lu_open = not it['opens_at_lu']
            # 「低开」= today opening below prev close
            opens_low = (ip and ip['close'] > 0 and it['open'] < ip['close']) if ip else False

            # Sell if: not at LU open OR opens low
            if not_at_lu_open or opens_low:
                sp = it['open']  # Execute at opening price
                if sp > 0:
                    pnl = (sp - bp_) / bp_ * 100
                    reason_parts = []
                    if not_at_lu_open: reason_parts.append("未涨停开盘")
                    if opens_low: reason_parts.append("低开")
                    tlist.append({
                        'name': n, 'buy_date': pos['buy_date'],
                        'buy_price': bp_, 'sell_date': date,
                        'sell_price': sp, 'pnl': pnl,
                        'reason': '+'.join(reason_parts),
                        'hold_days': (datetime.strptime(date, '%Y-%m-%d') -
                                     datetime.strptime(pos['buy_date'], '%Y-%m-%d')).days,
                    })
                    cash += sp * pos['shares']
                    pos_list.remove(pos)

        # BUY
        if rec != '休息' and len(pos_list) == 0:
            bn = rec
            if bn in price_db and date in price_db[bn]:
                bp_ = price_db[bn][date]['open']
                sh = int(cash / bp_ / 100) * 100
                if sh > 0:
                    cash -= sh * bp_
                    pos_list.append({'name': bn, 'buy_date': date, 'buy_price': bp_, 'shares': sh})

        pv = sum(p['shares'] * price_db.get(p['name'], {}).get(date, {}).get('close', p['buy_price']) for p in pos_list)

    final = cash + pv
    ret = (final - INIT) / INIT * 100
    wins = sum(1 for t in tlist if t['pnl'] > 0)
    wr = wins / max(len(tlist), 1) * 100

    f.write(f"交易员选股 + 竞价决策规则:\n")
    f.write(f"  最终资产: {final:,.0f} | 收益率: {ret:+.1f}%\n")
    f.write(f"  交易笔数: {len(tlist)} | 胜率: {wr:.0f}%\n")
    f.write(f"  持仓: {[(p['name'], p['buy_date']) for p in pos_list]}\n")
    f.write(f"  距目标1M: {final - TARGET:+,.0f}\n\n")

    # Detailed trades
    f.write("逐笔明细:\n")
    f.write(f"{'买入日':<12} {'标的':<10} {'买入':>8} {'卖出日':<12} {'卖出':>8} {'盈亏':>8} {'天':>4} {'卖出原因':<20}\n")
    f.write("-" * 85 + "\n")
    for t in tlist:
        f.write(f"{t['buy_date']:<12} {t['name']:<10} {t['buy_price']:>8.2f} "
                f"{t['sell_date']:<12} {t['sell_price']:>8.2f} {t['pnl']:>+7.1f}% "
                f"{t['hold_days']:>4} {t['reason']:<20}\n")

    f.write(f"\n总交易: {len(tlist)} | 盈利: {wins} | 胜率: {wr:.0f}%\n")

print(f"Done: {out_path}")
