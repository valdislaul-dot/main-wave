import json
import openpyxl
from datetime import datetime, timedelta
from collections import defaultdict

with open(r'C:\Users\Davis\Desktop\主升浪\stock_data.json', 'r', encoding='utf-8') as f:
    stock_data = json.load(f)

def excel_to_date(serial):
    return datetime(1899, 12, 30) + timedelta(days=int(serial))

wb = openpyxl.load_workbook(r'C:\Users\Davis\Desktop\主升浪\副本主升浪.xlsx')
ws = wb['Sheet1']
records = []
for row in ws.iter_rows(min_row=2, values_only=True):
    for i in range(0, 10, 2):
        date_val = row[i]; stock = row[i+1] if i+1 < len(row) else None
        if date_val is not None and date_val != '' and stock is not None and stock != '':
            records.append((int(date_val), stock.strip()))
records.sort(key=lambda x: x[0])

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
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10

def is_limit_up(close, prev_close, limit_pct):
    if prev_close is None or prev_close <= 0: return False
    return close >= round(prev_close * (1 + limit_pct), 2) - 0.005

# Build price DB
price_db = {}
for name, code in stocks_map.items():
    if name not in stock_data: continue
    price_db[name] = {}
    limit_pct = get_limit_pct(code)
    klines = stock_data[name]
    prev_close = None
    for i, k in enumerate(klines):
        date = k['day']
        o=float(k['open']); c=float(k['close']); h=float(k['high']); l=float(k['low']); v=float(k['volume'])
        entry={'open':o,'close':c,'high':h,'low':l,'volume':v,'is_limit_up':False,'prev_close':prev_close,'change_pct':0,'gap_open_pct':0}
        if prev_close and prev_close>0:
            entry['is_limit_up']=is_limit_up(c,prev_close,limit_pct)
            entry['change_pct']=(c-prev_close)/prev_close*100
            entry['gap_open_pct']=(o-prev_close)/prev_close*100
        if i>=5: entry['vol_ma5']=sum(float(klines[j]['volume']) for j in range(i-5,i))/5
        else: entry['vol_ma5']=v
        if i>=20: entry['vol_ma20']=sum(float(klines[j]['volume']) for j in range(i-20,i))/20
        else: entry['vol_ma20']=v
        entry['vol_ratio5']=v/entry['vol_ma5'] if entry['vol_ma5']>0 else 1
        entry['vol_ratio20']=v/entry['vol_ma20'] if entry['vol_ma20']>0 else 1
        if h>l>0:
            entry['seal_quality']=(c-l)/(h-l)
            us=(h-max(o,c))/(h-l); body=abs(c-o)/(h-l)
            entry['is_one_line']=(us<0.1 and body<0.1)
        else: entry['seal_quality']=1; entry['is_one_line']=False
        cons=0
        for j in range(i-1,max(i-10,-1),-1):
            cd_=klines[j]['day']
            if cd_ in price_db[name] and price_db[name][cd_]['is_limit_up']: cons+=1
            else: break
        entry['cons_lu_before']=cons
        price_db[name][date]=entry
        prev_close=c

timeline=[]
for serial,stock in records:
    d=excel_to_date(serial); timeline.append((d.strftime('%Y-%m-%d'),stock))
all_dates=sorted(set(d for d,_ in timeline))
INITIAL=300000; TARGET=1000000

# ================================================================
# HYBRID SELL MODEL (混合智能卖出)
# Based on calibration: combines best elements of multiple rules
# ================================================================
def decide_sell(pos, date, prev_date, price_db):
    """
    Hybrid sell decision. Returns (should_sell, sell_price).
    Combines:
    1. Always hold through limit-up days
    2. On non-limit-up days: check severity of weakness
    3. Trailing stop for strong trends
    4. Hard stop for large losses
    """
    name=pos['name']; buy_price=pos['buy_price']

    # Rule 0: No data → sell
    if name not in price_db or date not in price_db[name]:
        return (True, None)

    info_today=price_db[name][date]
    info_prev=price_db[name].get(prev_date) if prev_date else None

    # Rule 1: Previous day was limit-up → HOLD (连板持有)
    if info_prev and info_prev['is_limit_up']:
        # Reset any tracking
        pos['days_since_lu'] = 0
        pos['peak_close'] = max(pos.get('peak_close', 0), info_today['close'])
        return (False, None)

    # Track days since last limit-up
    if 'days_since_lu' not in pos: pos['days_since_lu']=0
    pos['days_since_lu']+=1

    # Track peak close
    if 'peak_close' not in pos: pos['peak_close']=info_today['close']
    else: pos['peak_close']=max(pos['peak_close'], info_today['close'])

    sell_price=None
    should_sell=False

    # Rule 2: Hard stop — if loss exceeds 8% from buy, sell immediately
    loss_from_buy=(info_today['open']-buy_price)/buy_price*100
    if loss_from_buy <= -8:
        should_sell=True
        sell_price=info_today['open']  # get out at open

    # Rule 3: Trailing stop — if close drops 5%+ from peak, sell at VWAP
    if not should_sell and pos['peak_close']>0:
        drawdown=(info_today['close']-pos['peak_close'])/pos['peak_close']*100
        if drawdown <= -5:
            should_sell=True
            sell_price=(info_today['high']+info_today['low']+info_today['close'])/3

    # Rule 4: Gap-down severity — sell if open drops significantly from prev close
    if not should_sell and info_prev:
        prev_close=info_prev['close']
        if prev_close>0:
            gap=(info_today['open']-prev_close)/prev_close*100
            if gap < -2 and pos['days_since_lu']>=1:
                should_sell=True
                sell_price=(info_today['high']+info_today['low']+info_today['close'])/3

    # Rule 5: Stale position — no limit-up for 3+ days, just exit
    if not should_sell and pos['days_since_lu']>=3:
        should_sell=True
        sell_price=(info_today['high']+info_today['low']+info_today['close'])/3

    return (should_sell, sell_price)

# ================================================================
# SCORING MODEL (from previous work)
# ================================================================
def score_v2(name, date, price_db, stock_data):
    if name not in price_db or date not in price_db[name]: return -999
    klines=stock_data[name]
    idxs=[i for i,k in enumerate(klines) if k['day']==date]
    if not idxs or idxs[0]<1: return -999
    idx=idxs[0]
    pd_=klines[idx-1]['day']
    if pd_ not in price_db[name]: return -999
    t1=price_db[name][pd_]
    if not t1['is_limit_up']: return -999
    bi=price_db[name][date]
    t2_lu=False
    if idx>=2:
        t2d=klines[idx-2]['day']
        if t2d in price_db[name]: t2_lu=price_db[name][t2d]['is_limit_up']
    s=0.0
    v20=t1.get('vol_ratio20',1)
    if v20<0.3: s+=35
    elif v20<0.5: s+=28
    elif v20<0.7: s+=22
    elif v20<1.0: s+=16
    elif v20<1.5: s+=8
    elif v20<2.0: s+=2
    elif v20<3.0: s-=3
    elif v20<5.0: s-=10
    else: s-=18
    g=t1['gap_open_pct']
    if g>=9.5: s+=22
    elif g>=8: s+=18
    elif g>=5: s+=13
    elif g>=3: s+=7
    elif g>=1: s+=2
    elif g>=0: s+=0
    else: s-=12
    if t1.get('is_one_line',False): s+=12
    cons=t1.get('cons_lu_before',0)
    if cons==0: s+=3
    elif cons==1: s+=10
    elif cons==2: s+=12
    elif cons>=3: s+=7
    dow=datetime.strptime(date,'%Y-%m-%d').weekday()
    if dow==0: s+=18
    elif dow==4: s-=5
    seal=t1.get('seal_quality',1)
    if seal>=0.99: s+=6
    elif seal>=0.95: s+=3
    elif seal<0.85: s-=10
    bg=bi['gap_open_pct']
    if bg>8: s+=8
    elif bg>5: s+=5
    elif bg>2: s+=2
    elif bg>0: s+=0
    elif bg>-2: s-=5
    else: s-=25
    if t2_lu: s+=6
    return s

def get_model_pick(date):
    cands=[]
    for name in price_db:
        sc=score_v2(name,date,price_db,stock_data)
        if sc>-999:
            klines=stock_data[name]
            idxs=[i for i,k in enumerate(klines) if k['day']==date]
            idx=idxs[0]; pd_=klines[idx-1]['day']
            t1=price_db[name][pd_]
            cands.append({'name':name,'score':sc,'t1_vol20':t1.get('vol_ratio20',1)})
    cands.sort(key=lambda x:x['score'],reverse=True)
    if not cands: return None
    top3=cands[:3]; top3.sort(key=lambda x:x['t1_vol20'])
    return top3[0]['name']

# ================================================================
# SIMULATION ENGINE
# ================================================================
def run_sim(pick_fn, label):
    positions=[]; cash=INITIAL; trades_log=[]
    for didx,date in enumerate(all_dates):
        record=dict(timeline).get(date,'休息')
        prev_date=all_dates[didx-1] if didx>0 else None

        # SELL
        for pos in positions[:]:
            should_sell, sp = decide_sell(pos, date, prev_date, price_db)
            if should_sell:
                if sp and sp>0:
                    pnl=(sp-pos['buy_price'])/pos['buy_price']*100
                    trades_log.append({
                        'name':pos['name'],'buy_date':pos['buy_date'],
                        'buy_price':pos['buy_price'],'sell_date':date,
                        'sell_price':sp,'pnl':pnl,
                        'hold_days':(datetime.strptime(date,'%Y-%m-%d')-
                                    datetime.strptime(pos['buy_date'],'%Y-%m-%d')).days
                    })
                    cash+=sp*pos['shares']
                    positions.remove(pos)

        # BUY
        stock_bought=None
        if record!='休息' and len(positions)==0:
            pick=pick_fn(date)
            if pick and pick in price_db and date in price_db[pick]:
                bp=price_db[pick][date]['open']
                shares=int(cash/bp/100)*100
                if shares>0:
                    cash-=shares*bp
                    positions.append({'name':pick,'buy_date':date,'buy_price':bp,'shares':shares})
                    stock_bought={'name':pick,'price':bp,'shares':shares}

        pv=sum(p['shares']*price_db.get(p['name'],{}).get(date,{}).get('close',p['buy_price']) for p in positions)

    final=cash+pv; ret=(final-INITIAL)/INITIAL*100
    wins=sum(1 for t in trades_log if t['pnl']>0)
    wr=wins/max(len(trades_log),1)*100
    return {'label':label,'final':final,'ret':ret,'trades':trades_log,
            'wr':wr,'held':[(p['name'],p['buy_date']) for p in positions],
            'cash':cash,'n_trades':len(trades_log)}

# ================================================================
# RUN ALL MODELS
# ================================================================
out_path=r'C:\Users\Davis\Desktop\主升浪\hybrid_model_results.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*100+"\n")
    f.write("混合智能卖出模型 — 最终对比\n")
    f.write("="*100+"\n\n")
    f.write("卖出规则: 连板持有 + 硬止损-8% + 移动止盈-5% + 低开-2%退出 + 3日不板退出\n")
    f.write("卖出价: 紧急用开盘价, 其他用VWAP\n\n")

    # Model A: Trader's picks
    def pick_trader(date):
        return dict(timeline).get(date,None)
    rA=run_sim(pick_trader,"A-交易员选股")

    # Model B: Our model picks
    rB=run_sim(get_model_pick,"B-模型选股(Top3最低量)")

    f.write(f"{'模型':<30} {'最终资产':>12} {'收益率':>10} {'交易':>6} {'胜率':>8}\n")
    f.write("-"*70+"\n")
    for r in [rA,rB]:
        f.write(f"{r['label']:<30} {r['final']:>12,.0f} {r['ret']:>+9.1f}% {r['n_trades']:>6} {r['wr']:>7.0f}%\n")

    # Detailed trades for trader
    f.write(f"\n\n{'='*100}\n")
    f.write(f"A. 交易员选股 — 逐笔明细\n")
    f.write(f"{'='*100}\n")
    f.write(f"{'买入日':<12} {'标的':<10} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'盈亏':>8} {'持天':>4}\n")
    f.write("-"*65+"\n")
    for t in rA['trades']:
        f.write(f"{t['buy_date']:<12} {t['name']:<10} {t['buy_price']:>8.2f} "
                f"{t['sell_date']:<12} {t['sell_price']:>8.2f} {t['pnl']:>+7.1f}% {t['hold_days']:>4}\n")
    f.write(f"\n总交易: {rA['n_trades']}笔 | 胜率: {rA['wr']:.0f}%\n")
    f.write(f"持仓: {rA['held']}\n")
    f.write(f"距目标1M: {rA['final']-TARGET:+,.0f}\n")

    # Detailed for model
    f.write(f"\n\n{'='*100}\n")
    f.write(f"B. 模型选股 — 逐笔明细\n")
    f.write(f"{'='*100}\n")
    f.write(f"{'买入日':<12} {'标的':<10} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'盈亏':>8} {'持天':>4}\n")
    f.write("-"*65+"\n")
    for t in rB['trades']:
        f.write(f"{t['buy_date']:<12} {t['name']:<10} {t['buy_price']:>8.2f} "
                f"{t['sell_date']:<12} {t['sell_price']:>8.2f} {t['pnl']:>+7.1f}% {t['hold_days']:>4}\n")
    f.write(f"\n总交易: {rB['n_trades']}笔 | 胜率: {rB['wr']:.0f}%\n")
    f.write(f"持仓: {rB['held']}\n")

    # ================================================================
    # COMPARISON TABLE
    # ================================================================
    f.write(f"\n\n{'='*100}\n")
    f.write("最终对比总结\n")
    f.write(f"{'='*100}\n\n")

    f.write(f"{'策略':<40} {'最终资产':>12} {'收益率':>10}\n")
    f.write("-"*65+"\n")
    f.write(f"{'交易员选股 + 旧规则(不涨停就卖)':<40} {108912:>12,.0f} {'-63.7%':>10}\n")
    f.write(f"{'交易员选股 + 混合智能卖出':<40} {rA['final']:>12,.0f} {rA['ret']:>+9.1f}%\n")
    f.write(f"{'模型选股 + 混合智能卖出':<40} {rB['final']:>12,.0f} {rB['ret']:>+9.1f}%\n")
    f.write(f"\n实际交易员结果: ~1,000,000 (+233%)\n")

    vs_target=rA['final']-TARGET
    f.write(f"混合模型距实际: {vs_target:+,.0f} ({vs_target/TARGET*100:+.1f}%)\n")

print(f"Complete: {out_path}")
