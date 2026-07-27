"""
V2.1 最终模型回测: 2026-03-03 至 2026-07-24
初始资金 200k, 全仓, V2.1评分 + V2.1卖出规则
"""
import json, openpyxl, os, sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = str(Path(__file__).resolve().parent.parent)
print(f'BASE: {BASE}', flush=True)

# Find xlsx by trying every large file (encoding-safe approach)
xlsx_path = None
search_dirs = [Path(BASE), Path(BASE).parent]  # project dir + Desktop
for search_dir in search_dirs:
    if not search_dir.exists():
        continue
    for f in search_dir.iterdir():
        if f.is_file() and f.stat().st_size > 10000 and f.stat().st_size < 500000:
            try:
                test = openpyxl.load_workbook(str(f), read_only=True)
                # Check it has Sheet1 with trade data
                if 'Sheet1' in test.sheetnames:
                    ws = test['Sheet1']
                    row = next(ws.iter_rows(min_row=2, max_row=2, values_only=True))
                    if row and any(v is not None for v in row):
                        test.close()
                        xlsx_path = str(f)
                        print(f'Found xlsx: {f.stat().st_size} bytes', flush=True)
                        break
                test.close()
            except Exception:
                pass
    if xlsx_path:
        break

if not xlsx_path:
    print('ERROR: No xlsx found', flush=True)
    sys.exit(1)

# Load stock data
stock_json = Path(BASE) / 'data' / 'stock_data.json'
print(f'Loading {stock_json}...', flush=True)
with open(str(stock_json), 'r', encoding='utf-8') as f:
    stock_data = json.load(f)

def ed(s): return datetime(1899, 12, 30) + timedelta(days=int(s))

wb = openpyxl.load_workbook(xlsx_path)
ws = wb['Sheet1']
records = []
for row in ws.iter_rows(min_row=2, values_only=True):
    # Format: groups of 3 (date, buy_stock, sell_stock)
    # Read up to 15 columns (5 trade groups)
    max_cols = min(len(row), 15) if row else 0
    for i in range(0, max_cols, 3):
        date_val = row[i] if i < len(row) else None
        stock = row[i+1] if i+1 < len(row) else None
        if date_val is not None and date_val != '' and isinstance(date_val, (int, float)):
            if stock is not None and stock != '' and isinstance(stock, str) and stock.strip():
                records.append((int(date_val), stock.strip()))
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
print("Building price database...", flush=True)
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
            entry['seal_quality'] = 1
            entry['is_one_line'] = False
        cons = 0
        for j in range(i-1, max(i-10, -1), -1):
            cd_ = klines[j]['day']
            if cd_ in price_db[name] and price_db[name][cd_]['is_limit_up']:
                cons += 1
            else:
                break
        entry['cons_lu_before'] = cons
        price_db[name][dt] = entry
        prev_close = c

timeline = []
for s, st in records:
    d = ed(s)
    timeline.append((d.strftime('%Y-%m-%d'), st))
all_dates = sorted(set(d for d, _ in timeline))

INIT = 200000

def score_v21(name, date):
    """V2.1 scoring matching CLAUDE.md factors"""
    if name not in price_db or date not in price_db[name]: return -999
    kls = stock_data[name]
    idxs = [i for i, k in enumerate(kls) if k['day'] == date]
    if not idxs or idxs[0] < 1: return -999
    idx = idxs[0]
    pd_ = kls[idx - 1]['day']
    if pd_ not in price_db[name]: return -999
    t1 = price_db[name][pd_]
    if not t1['is_limit_up']: return -999
    bi = price_db[name][date]

    s = 0.0
    cons = t1.get('cons_lu_before', 0)

    # Volume contraction: 连板>=2 use 5d avg, else 20d
    vr = t1.get('vol_ratio5', 1) if cons >= 2 else t1.get('vol_ratio20', 1)
    if vr < 0.3: s += 35
    elif vr < 0.5: s += 28
    elif vr < 0.7: s += 22
    elif vr < 1.0: s += 16
    elif vr < 1.5: s += 8
    elif vr < 2.0: s += 2
    elif vr < 3.0: s -= 3
    elif vr < 5.0: s -= 10
    else: s -= 18

    # Strong board
    g = t1['gap_open_pct']
    if g >= 9.5: s += 22
    elif g >= 8: s += 18
    elif g >= 5: s += 13
    elif g >= 3: s += 7
    elif g >= 1: s += 2
    elif g >= 0: s += 0
    else: s -= 12

    # One-line board
    if t1.get('is_one_line', False):
        if abs(t1['high'] - t1['low']) < 0.001:
            s += 20  # True one-line
        else:
            s += 10  # T-board

    # Consecutive boards
    if cons >= 4: s += 7
    elif cons == 2 or cons == 3: s += 12
    elif cons == 1: s += 10

    # Day of week
    dow = datetime.strptime(date, '%Y-%m-%d').weekday()
    if dow == 0: s += 18
    elif dow == 4: s -= 5

    # Seal quality
    seal = t1.get('seal_quality', 1)
    if seal >= 0.99: s += 6
    elif seal >= 0.95: s += 3
    elif seal < 0.85: s -= 10

    # Buy-day gap
    bg = bi['gap_open_pct']
    if bg > 8: s += 8
    elif bg > 5: s += 5
    elif bg > 2: s += 2
    elif bg > 0: s += 0
    elif bg > -2: s -= 5
    else: s -= 25

    # T-2 limit up
    if idx >= 2:
        t2d = kls[idx - 2]['day']
        if t2d in price_db[name] and price_db[name][t2d]['is_limit_up']:
            s += 6

    return s

def get_model_pick(date):
    cands = []
    for name in price_db:
        sc = score_v21(name, date)
        if sc > -999:
            kls = stock_data[name]
            idxs = [i for i, k in enumerate(kls) if k['day'] == date]
            idx = idxs[0]; pd_ = kls[idx - 1]['day']
            t1 = price_db[name][pd_]
            cons = t1.get('cons_lu_before', 0)
            cands.append({
                'name': name, 'score': sc,
                'vr': t1.get('vol_ratio5', 1) if cons >= 2 else t1.get('vol_ratio20', 1),
            })
    cands.sort(key=lambda x: x['score'], reverse=True)
    if not cands: return None
    top3 = cands[:3]
    top3.sort(key=lambda x: x['vr'])
    return top3[0]['name']

def simulate(pick_fn, label):
    pos_list = []; cash = INIT; tlist = []; monthly = {}
    max_drawdown = 0; peak = INIT

    for didx, date in enumerate(all_dates):
        rec = dict(timeline).get(date, '休息')
        pd_ = all_dates[didx - 1] if didx > 0 else None

        # SELL: V2.1 rules
        for pos in pos_list[:]:
            n = pos['name']; bp_ = pos['buy_price']
            if n not in price_db or date not in price_db[n]:
                pos_list.remove(pos); continue

            it = price_db[n][date]
            ip = price_db[n].get(pd_) if pd_ else None
            prev_lu = ip and ip['is_limit_up']
            prev_close = ip['close'] if ip else None

            opens_below = False; gap_ge_4 = False
            if prev_close and prev_close > 0:
                gap_today = (it['open'] - prev_close) / prev_close * 100
                opens_below = it['open'] < prev_close
                gap_ge_4 = gap_today >= 4.0

            should_sell = False; sell_price = None

            if prev_lu:
                if opens_below:
                    should_sell = True
                    sell_price = it['high']
            else:
                if not gap_ge_4:
                    should_sell = True
                    sell_price = 0.7 * (it['high'] + it['open']) / 2 + 0.3 * it['close']

            if should_sell and sell_price and sell_price > 0:
                pnl = (sell_price - bp_) / bp_ * 100
                tlist.append({
                    'name': n, 'buy_date': pos['buy_date'],
                    'buy_price': bp_, 'sell_date': date,
                    'sell_price': sell_price, 'pnl': pnl
                })
                cash += sell_price * pos['shares']
                pos_list.remove(pos)

        # BUY
        if rec != '休息' and len(pos_list) == 0:
            bn = pick_fn(date)
            if bn and bn in price_db and date in price_db[bn]:
                bi = price_db[bn][date]
                if bi['gap_open_pct'] < 9.8:
                    bp_ = bi['open']
                    sh = int(cash / bp_ / 100) * 100
                    if sh > 0:
                        cash -= sh * bp_
                        pos_list.append({
                            'name': bn, 'buy_date': date,
                            'buy_price': bp_, 'shares': sh
                        })

        # Portfolio tracking
        pv = sum(p['shares'] * price_db.get(p['name'], {}).get(date, {}).get('close', p['buy_price']) for p in pos_list)
        total = cash + pv
        peak = max(peak, total)
        max_drawdown = min(max_drawdown, (total - peak) / peak * 100)

    # Sell remaining
    for pos in pos_list[:]:
        n = pos['name']; bp_ = pos['buy_price']
        last_d = all_dates[-1]
        if n in price_db and last_d in price_db[n]:
            sp = price_db[n][last_d]['close']
            pnl = (sp - bp_) / bp_ * 100
            tlist.append({'name': n, 'buy_date': pos['buy_date'],
                         'buy_price': bp_, 'sell_date': last_d,
                         'sell_price': sp, 'pnl': pnl})
            cash += sp * pos['shares']

    final = cash
    ret = (final - INIT) / INIT * 100
    wins = sum(1 for t in tlist if t['pnl'] > 0)
    wr = wins / max(len(tlist), 1) * 100

    # Monthly PnL
    month_pnl = {}
    for t in tlist:
        m = t['sell_date'][:7]
        month_pnl[m] = month_pnl.get(m, 0) + t['pnl']

    return {
        'label': label, 'final': final, 'ret': ret, 'trades': tlist,
        'wr': wr, 'n_trades': len(tlist), 'max_dd': max_drawdown,
        'month_pnl': month_pnl, 'init': INIT
    }


# ============================================================
# RUN
# ============================================================
print()
print('=' * 70)
print('V2.1 最终模型回测: 2026-03-03 ~ 2026-07-24')
print('初始资金: 200,000 | 全仓 | 评分>=30全仓')
print('=' * 70)
print()

# Trader picks
print("Running: 交易员选股+V2.1卖出...", flush=True)
r_trader = simulate(lambda d: dict(timeline).get(d, None), '交易员选股')

# Model picks
print("Running: 模型V2.1(Top3最低量)...", flush=True)
r_model = simulate(get_model_pick, '模型V2.1(Top3最低量)')

# Score >= 30
print("Running: 模型V2.1(评分>=30)...", flush=True)
def pick_score30(date):
    cands = []
    for name in price_db:
        sc = score_v21(name, date)
        if sc > -999:
            kls = stock_data[name]
            idxs = [i for i, k in enumerate(kls) if k['day'] == date]
            idx = idxs[0]; pd_ = kls[idx - 1]['day']
            t1 = price_db[name][pd_]
            cons = t1.get('cons_lu_before', 0)
            cands.append({
                'name': name, 'score': sc,
                'vr': t1.get('vol_ratio5', 1) if cons >= 2 else t1.get('vol_ratio20', 1),
            })
    cands.sort(key=lambda x: x['score'], reverse=True)
    good = [c for c in cands if c['score'] >= 30]
    if not good: return None
    good.sort(key=lambda x: x['vr'])
    return good[0]['name']
r_model30 = simulate(pick_score30, '模型V2.1(评分>=30)')

# Half position
print("Running: 半仓...", flush=True)
def simulate_half(pick_fn, label):
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
            prev_close = ip['close'] if ip else None
            opens_below = False; gap_ge_4 = False
            if prev_close and prev_close > 0:
                g = (it['open'] - prev_close) / prev_close * 100
                opens_below = it['open'] < prev_close; gap_ge_4 = g >= 4.0
            should_sell = False; sell_price = None
            if prev_lu:
                if opens_below: should_sell = True; sell_price = it['high']
            else:
                if not gap_ge_4: should_sell = True; sell_price = 0.7*(it['high']+it['open'])/2 + 0.3*it['close']
            if should_sell and sell_price and sell_price > 0:
                pnl = (sell_price - bp_) / bp_ * 100
                tlist.append({'name':n,'buy_date':pos['buy_date'],'buy_price':bp_,'sell_date':date,'sell_price':sell_price,'pnl':pnl})
                cash += sell_price * pos['shares']; pos_list.remove(pos)
        if rec != '休息' and len(pos_list) == 0:
            bn = pick_fn(date)
            if bn and bn in price_db and date in price_db[bn]:
                bi = price_db[bn][date]
                if bi['gap_open_pct'] < 9.8:
                    bp_ = bi['open']
                    deploy = cash * 0.5
                    sh = int(deploy / bp_ / 100) * 100
                    if sh > 0:
                        cash -= sh * bp_
                        pos_list.append({'name':bn,'buy_date':date,'buy_price':bp_,'shares':sh})
    for pos in pos_list[:]:
        n = pos['name']; bp_ = pos['buy_price']; last_d = all_dates[-1]
        if n in price_db and last_d in price_db[n]:
            sp = price_db[n][last_d]['close']
            pnl = (sp-bp_)/bp_*100
            tlist.append({'name':n,'buy_date':pos['buy_date'],'buy_price':bp_,'sell_date':last_d,'sell_price':sp,'pnl':pnl})
            cash += sp * pos['shares']
    final = cash; ret = (final-INIT)/INIT*100
    wins = sum(1 for t in tlist if t['pnl']>0); wr = wins/max(len(tlist),1)*100
    return {'label':label,'final':final,'ret':ret,'trades':tlist,'wr':wr,'n_trades':len(tlist),'max_dd':0}
r_half = simulate_half(get_model_pick, '模型V2.1(半仓)')

# ============================================================
# PRINT RESULTS
# ============================================================
print()
print('=' * 70)
print('回测结果对比')
print('=' * 70)
print()
print(f"{'模型':<28} {'最终资产':>12} {'收益率':>10} {'笔数':>6} {'胜率':>8} {'最大回撤':>10}")
print('-' * 80)
for r in [r_trader, r_model, r_model30, r_half]:
    print(f"{r['label']:<28} {r['final']:>12,.0f} {r['ret']:>+9.1f}% {r['n_trades']:>6} {r['wr']:>7.0f}% {r['max_dd']:>9.1f}%")

print()
print('月度收益 (模型V2.1全仓):')
print(f"{'月份':<8} {'笔数':>5} {'月PnL':>10}")
print('-' * 28)
for m in sorted(r_model['month_pnl'].keys()):
    pnl = r_model['month_pnl'].get(m, 0)
    n_t = len([t for t in r_model['trades'] if t['sell_date'][:7] == m])
    print(f"{m:<8} {n_t:>5} {pnl:>+9.1f}%")

print()
print('模型V2.1全仓 逐笔交易:')
print(f"{'#':<4} {'买入日':<12} {'标的':<10} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'盈亏':>8} {'累计':>10}")
print('-' * 75)
cum_val = INIT
for i, t in enumerate(r_model['trades']):
    cum_val = cum_val * (1 + t['pnl']/100)
    print(f"{i+1:<4} {t['buy_date']:<12} {t['name']:<10} {t['buy_price']:>8.2f} "
          f"{t['sell_date']:<12} {t['sell_price']:>8.2f} {t['pnl']:>+7.1f}% {cum_val:>10,.0f}")

print()
print(f"{'='*70}")
print(f"最终对比:")
print(f"  A实盘:       200k -> 1,022k (+411%), 99笔, 胜率41%")
print(f"  模型V2.1全仓: 200k -> {r_model['final']:,.0f} ({r_model['ret']:+.0f}%), {r_model['n_trades']}笔, 胜率{r_model['wr']:.0f}%")
print(f"  vs A实盘:    {r_model['final'] - 1022000:+,.0f}")
print(f"{'='*70}")

# Save to file
out_path = str(Path(BASE) / 'logs' / 'backtest_v21_results.txt')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("="*70+"\n")
    f.write("V2.1 最终模型回测: 2026-03-03 ~ 2026-07-24\n")
    f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    f.write("="*70+"\n\n")

    f.write(f"{'模型':<28} {'最终资产':>12} {'收益率':>10} {'笔数':>6} {'胜率':>8} {'最大回撤':>10}\n")
    f.write("-"*80+"\n")
    for r in [r_trader, r_model, r_model30, r_half]:
        f.write(f"{r['label']:<28} {r['final']:>12,.0f} {r['ret']:>+9.1f}% {r['n_trades']:>6} {r['wr']:>7.0f}% {r['max_dd']:>9.1f}%\n")
    f.write(f"\nA实盘: 200k -> 1,022k (+411%), 99笔, 胜率41%\n\n")

    f.write("月度收益:\n")
    f.write(f"{'月份':<8} {'笔数':>5} {'月PnL':>10}\n")
    f.write("-"*28+"\n")
    for m in sorted(r_model['month_pnl'].keys()):
        pnl = r_model['month_pnl'].get(m, 0)
        n_t = len([t for t in r_model['trades'] if t['sell_date'][:7] == m])
        f.write(f"{m:<8} {n_t:>5} {pnl:>+9.1f}%\n")

    f.write(f"\n模型V2.1全仓 逐笔交易:\n")
    f.write(f"{'#':<4} {'买入日':<12} {'标的':<10} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'盈亏':>8}\n")
    f.write("-"*65+"\n")
    for i, t in enumerate(r_model['trades']):
        f.write(f"{i+1:<4} {t['buy_date']:<12} {t['name']:<10} {t['buy_price']:>8.2f} "
                f"{t['sell_date']:<12} {t['sell_price']:>8.2f} {t['pnl']:>+7.1f}%\n")

    f.write(f"\n交易员选股+V2.1卖出 逐笔交易:\n")
    f.write(f"{'#':<4} {'买入日':<12} {'标的':<10} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'盈亏':>8}\n")
    f.write("-"*65+"\n")
    for i, t in enumerate(r_trader['trades']):
        f.write(f"{i+1:<4} {t['buy_date']:<12} {t['name']:<10} {t['buy_price']:>8.2f} "
                f"{t['sell_date']:<12} {t['sell_price']:>8.2f} {t['pnl']:>+7.1f}%\n")

print(f"\n详细结果已保存到: logs/backtest_v21_results.txt")
