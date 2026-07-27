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
        h = float(k['high']); l = float(k['low']); v = float(k['volume'])
        entry = {
            'open': o, 'close': c, 'high': h, 'low': l, 'volume': v,
            'is_limit_up': False, 'prev_close': prev_close,
            'change_pct': 0, 'gap_open_pct': 0,
        }
        if prev_close and prev_close > 0:
            entry['is_limit_up'] = is_lu(c, prev_close, lpct)
            entry['change_pct'] = (c - prev_close) / prev_close * 100
            entry['gap_open_pct'] = (o - prev_close) / prev_close * 100
            # Is stock LOCKED at limit-up at the OPEN?
            # i.e., did it open at today's limit-up price?
            today_lu_price = round(prev_close * (1 + lpct), 2)
            entry['opens_at_lu'] = (o >= today_lu_price - 0.005)
        else:
            entry['opens_at_lu'] = False
        # MA/Vol
        if i >= 5:
            entry['vol_ma5'] = sum(float(klines[j]['volume']) for j in range(i-5, i)) / 5
        else:
            entry['vol_ma5'] = v
        if i >= 20:
            entry['vol_ma20'] = sum(float(klines[j]['volume']) for j in range(i-20, i)) / 20
        else:
            entry['vol_ma20'] = v
        entry['vol_ratio5'] = v / entry['vol_ma5'] if entry['vol_ma5'] > 0 else 1
        entry['vol_ratio20'] = v / entry['vol_ma20'] if entry['vol_ma20'] > 0 else 1
        if h > l > 0:
            entry['seal_quality'] = (c - l) / (h - l)
            us = (h - max(o, c)) / (h - l)
            body = abs(c - o) / (h - l)
            entry['is_one_line'] = (us < 0.1 and body < 0.1)
        else:
            entry['seal_quality'] = 1; entry['is_one_line'] = False
        cons = 0
        for j in range(i-1, max(i-10, -1), -1):
            cd_ = klines[j]['day']
            if cd_ in price_db[name] and price_db[name][cd_]['is_limit_up']:
                cons += 1
            else: break
        entry['cons_lu_before'] = cons
        price_db[name][dt] = entry
        prev_close = c

timeline = []
for s, st in records:
    d = ed(s); timeline.append((d.strftime('%Y-%m-%d'), st))
all_dates = sorted(set(d for d, _ in timeline))
INIT = 300000; TARGET = 1000000

# Scoring function
def score_v2(name, date):
    if name not in price_db or date not in price_db[name]: return -999
    kls = stock_data[name]
    idxs = [i for i, k in enumerate(kls) if k['day'] == date]
    if not idxs or idxs[0] < 1: return -999
    idx = idxs[0]; pd_ = kls[idx - 1]['day']
    if pd_ not in price_db[name]: return -999
    t1 = price_db[name][pd_]
    if not t1['is_limit_up']: return -999
    bi = price_db[name][date]
    s = 0.0
    v20 = t1.get('vol_ratio20', 1)
    if v20 < 0.3: s += 35
    elif v20 < 0.5: s += 28
    elif v20 < 0.7: s += 22
    elif v20 < 1.0: s += 16
    elif v20 < 1.5: s += 8
    elif v20 < 2.0: s += 2
    elif v20 < 3.0: s -= 3
    elif v20 < 5.0: s -= 10
    else: s -= 18
    g = t1['gap_open_pct']
    if g >= 9.5: s += 22
    elif g >= 8: s += 18
    elif g >= 5: s += 13
    elif g >= 3: s += 7
    elif g >= 1: s += 2
    elif g >= 0: s += 0
    else: s -= 12
    if t1.get('is_one_line', False): s += 12
    cons = t1.get('cons_lu_before', 0)
    if cons == 0: s += 3
    elif cons == 1: s += 10
    elif cons == 2: s += 12
    elif cons >= 3: s += 7
    dow = datetime.strptime(date, '%Y-%m-%d').weekday()
    if dow == 0: s += 18
    elif dow == 4: s -= 5
    seal = t1.get('seal_quality', 1)
    if seal >= 0.99: s += 6
    elif seal >= 0.95: s += 3
    elif seal < 0.85: s -= 10
    bg = bi['gap_open_pct']
    if bg > 8: s += 8
    elif bg > 5: s += 5
    elif bg > 2: s += 2
    elif bg > 0: s += 0
    elif bg > -2: s -= 5
    else: s -= 25
    t2_lu = False
    if idx >= 2:
        t2d = kls[idx - 2]['day']
        if t2d in price_db[name]: t2_lu = price_db[name][t2d]['is_limit_up']
    if t2_lu: s += 6
    return s

def get_model_pick(date, require_buyable=False):
    """Get best model pick. If require_buyable=True, skip stocks that open at limit-up (can't buy)."""
    cands = []
    for name in price_db:
        sc = score_v2(name, date)
        if sc > -999:
            kls = stock_data[name]
            idxs = [i for i, k in enumerate(kls) if k['day'] == date]
            idx = idxs[0]; pd_ = kls[idx - 1]['day']
            t1 = price_db[name][pd_]
            buyable = True
            if require_buyable and name in price_db and date in price_db[name]:
                if price_db[name][date].get('opens_at_lu', False):
                    buyable = False  # Locked at limit-up, can't buy
            cands.append({
                'name': name, 'score': sc,
                'v20': t1.get('vol_ratio20', 1),
                'buyable': buyable,
            })
    cands.sort(key=lambda x: x['score'], reverse=True)

    if require_buyable:
        # Filter to only buyable, then pick from top 3 by lowest volume
        buyable = [c for c in cands if c['buyable']]
        if not buyable:
            return None  # Nothing buyable today
        top3 = buyable[:3]
        top3.sort(key=lambda x: x['v20'])
        return top3[0]['name']
    else:
        if not cands: return None
        top3 = cands[:3]
        top3.sort(key=lambda x: x['v20'])
        return top3[0]['name']

out_path = r'C:\Users\Davis\Desktop\主升浪\auction_results.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("=" * 80 + "\n")
    f.write("集合竞价约束分析\n")
    f.write("=" * 80 + "\n")
    f.write("假设: 开盘即涨停(一字板)的股票无法在竞价中买入\n")
    f.write("规则: 买入->开盘价 | 卖出->不涨停或低开->开盘价卖\n\n")

    # First, analyze how many top picks are unbuyable
    f.write("1. 每日#1候选的可买性分析:\n")
    f.write(f"{'日期':<12} {'#1候选':<10} {'开盘涨停?':<10} {'可买到?':<8} {'实际买':<10}\n")
    f.write("-" * 55 + "\n")

    locked_out_days = 0
    total_buy_days = 0
    for date in all_dates:
        rec = dict(timeline).get(date, '休息')
        if rec == '休息': continue
        total_buy_days += 1

        cands = []
        for name in price_db:
            sc = score_v2(name, date)
            if sc > -999:
                opens_lu = price_db[name][date].get('opens_at_lu', False)
                cands.append({'name': name, 'score': sc, 'opens_lu': opens_lu})
        cands.sort(key=lambda x: x['score'], reverse=True)

        if cands:
            top = cands[0]
            locked = "是(一字板)" if top['opens_lu'] else "否"
            buyable = "否" if top['opens_lu'] else "是"
            if top['opens_lu']: locked_out_days += 1
            f.write(f"{date:<12} {top['name']:<10} {locked:<10} {buyable:<8} {rec:<10}\n")

    f.write(f"\n#1候选无法买入(一字板)的天数: {locked_out_days}/{total_buy_days} ({locked_out_days/total_buy_days*100:.0f}%)\n\n")

    # Now simulate with and without auction constraint
    f.write("\n2. 模拟对比: 无约束 vs 竞价约束(只买可买到的)\n")
    f.write("-" * 70 + "\n")

    for label, constrained in [("无约束(理想)", False), ("竞价约束(只能买未封板的)", True)]:
        pos_list = []; cash = INIT; tlist = []
        for didx, date in enumerate(all_dates):
            rec = dict(timeline).get(date, '休息')
            pd_ = all_dates[didx - 1] if didx > 0 else None
            for pos in pos_list[:]:
                n = pos['name']; bp_ = pos['buy_price']
                if n not in price_db or date not in price_db[n]:
                    pos_list.remove(pos); continue
                it = price_db[n][date]; ip = price_db[n].get(pd_) if pd_ else None
                prev_lu = ip and ip['is_limit_up']
                opens_low = False
                if ip:
                    pcv = ip['close']
                    if pcv > 0 and (it['open'] - pcv) / pcv * 100 <= -1:
                        opens_low = True
                if not prev_lu or opens_low:
                    sp = it['open']
                    if sp > 0:
                        pnl = (sp - bp_) / bp_ * 100; tlist.append({'pnl': pnl})
                        cash += sp * pos['shares']; pos_list.remove(pos)

            if rec != '休息' and len(pos_list) == 0:
                # Use trader picks for this test (not model picks)
                bn = rec
                if bn in price_db and date in price_db[bn]:
                    # Check if buyable
                    if constrained and price_db[bn][date].get('opens_at_lu', False):
                        pass  # Can't buy, skip this day
                    else:
                        bp_ = price_db[bn][date]['open']
                        sh = int(cash / bp_ / 100) * 100
                        if sh > 0: cash -= sh * bp_; pos_list.append({'name': bn, 'buy_date': date, 'buy_price': bp_, 'shares': sh})

            pv = sum(p['shares'] * price_db.get(p['name'], {}).get(date, {}).get('close', p['buy_price']) for p in pos_list)
        final = cash + pv; ret = (final - INIT) / INIT * 100
        wr = sum(1 for t in tlist if t['pnl'] > 0) / max(len(tlist), 1) * 100
        f.write(f"{label:<30} final={final:>12,.0f} ret={ret:>+8.1f}% trades={len(tlist):>3} wr={wr:.0f}%\n")

    # Now test: what if trader's picks WERE constrained by auction?
    # i.e., the trader could only pick from buyable candidates
    f.write("\n\n3. 关键测试: 交易员是否受竞价约束?\n")
    f.write("如果交易员只能从可买到的(未一字板)候选中选股:\n")
    f.write("-" * 70 + "\n")

    # Check: on days when the trader picked a stock, was the #1 model pick buyable?
    f.write(f"{'日期':<12} {'模型#1':<10} {'#1可买?':<8} {'#1评分':<6} {'交易员选':<10} {'可买?':<8} {'评在可买中排名':<12}\n")
    f.write("-" * 75 + "\n")

    trader_picked_unbuyable = 0
    for date in all_dates:
        rec = dict(timeline).get(date, '休息')
        if rec == '休息': continue

        cands = []
        for name in price_db:
            sc = score_v2(name, date)
            if sc > -999:
                opens_lu = price_db[name][date].get('opens_at_lu', False)
                cands.append({'name': name, 'score': sc, 'buyable': not opens_lu})
        cands.sort(key=lambda x: x['score'], reverse=True)

        top1 = cands[0] if cands else None
        buyable_cands = [c for c in cands if c['buyable']]

        # Find trader's pick rank among buyable
        trader_rank_buyable = next((i+1 for i, c in enumerate(buyable_cands) if c['name'] == rec), -1)

        if top1:
            f.write(f"{date:<12} {top1['name']:<10} {'是' if top1['buyable'] else '否':<8} {top1['score']:>6.0f} "
                    f"{rec:<10} {'是' if any(c['name']==rec and c['buyable'] for c in cands) else '否':<8} "
                    f"{trader_rank_buyable:>3}/{len(buyable_cands)}\n")

    # Final summary
    f.write(f"\n\n4. 结论\n")
    f.write("-" * 70 + "\n")

print(f"Done: {out_path}")
