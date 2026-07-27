import json, openpyxl
from datetime import datetime, timedelta

with open(r'C:\Users\Davis\Desktop\主升浪\data\stock_data.json','r',encoding='utf-8') as f:
    stock_data=json.load(f)
def ed(s): return datetime(1899,12,30)+timedelta(days=int(s))

# Load new xlsx with buy/sell columns
wb=openpyxl.load_workbook(r'C:\Users\Davis\Desktop\主升浪.xlsx')
ws=wb['Sheet1']
records=[]
for row in ws.iter_rows(min_row=2,values_only=True):
    for i in range(0,15,3):
        dv=row[i]; buy=row[i+1]; sell=row[i+2]
        if dv is not None and dv!='':
            d=ed(int(dv)).strftime('%Y-%m-%d')
            b=str(buy).strip() if buy else None
            s=str(sell).strip() if sell else None
            records.append((d,b,s))
records.sort(key=lambda x:x[0])

# Build timeline: date -> (buy, sell)
timeline={}
for d,b,s in records:
    timeline[d]={'buy':b,'sell':s}
all_dates=sorted(timeline.keys())

sm={}
for n,c in [('赤天化','600227'),('亚盛集团','600108'),('国星光电','002449'),('顺钠股份','000533'),('美利云','000815'),('宇环数控','002903'),('金浦钛业','000545'),('郑州煤电','600121'),('金正大','002470'),('京投发展','600683'),('正泰电源','002150'),('基蛋生物','603387'),('华电辽能','600396'),('新日股份','603787'),('舒华体育','605299'),('新能泰山','000720'),('美诺华','603538'),('津药药业','600488'),('安徽建工','600502'),('力诺药包','301188'),('星辉环材','300834'),('中工国际','002051'),('康盛股份','002418'),('新朋股份','002328'),('圣阳股份','002580'),('康恩贝','600572'),('昂利康','002940'),('蜀道装备','300540'),('圣龙股份','603178'),('九鼎新材','002201'),('东望时代','600052'),('水发燃气','603318'),('飞南资源','301500'),('宝光股份','600379'),('金螳螂','002081'),('波导股份','600130'),('深圳华强','000062'),('大唐发电','601991'),('蒙娜丽莎','002918'),('滨化股份','601678'),('合肥城建','002208'),('华能蒙电','600863'),('达实智能','002421'),('合百集团','000417'),('安德利','605198'),('肯特股份','301591'),('香江控股','600162'),('泓淋电力','301439'),('方大集团','000055'),('广西能源','600310'),('天洋新材','603330'),('龙源技术','300105'),('金安国纪','002636'),('天地源','600665'),('翔鹭钨业','002842'),('金钼股份','601958'),('盛龙股份','001257'),('立航科技','603261'),('黄河旋风','600172'),('世名科技','300522'),('长裕集团','603407'),('宏柏新材','605366'),('兴业科技','002674'),('安洁科技','002635'),('雷赛智能','002979'),('先锋新材','300163'),('恒尚节能','603137'),('同兴达','002845'),('立方制药','003020'),('哈药股份','600664'),('立新能源','001258'),('长缆科技','002879')]:
    sm[n]=c
def lp(c): return 0.20 if (c.startswith('30') or c.startswith('688')) else 0.10
def lu(c,pc,lp_):
    if pc is None or pc<=0: return False
    return c>=round(pc*(1+lp_),2)-0.005
pdb={}
for name,code in sm.items():
    if name not in stock_data: continue
    pdb[name]={}; lpt=lp(code); klines=stock_data[name]; pc=None
    for i,k in enumerate(klines):
        dt=k['day']; o=float(k['open']); c=float(k['close']); h=float(k['high']); l=float(k['low'])
        e={'open':o,'close':c,'high':h,'low':l,'is_limit_up':False,'prev_close':pc,'gap_open_pct':0}
        if pc and pc>0: e['is_limit_up']=lu(c,pc,lpt); e['gap_open_pct']=(o-pc)/pc*100
        pdb[name][dt]=e; pc=c

out_path=r'C:\Users\Davis\Desktop\主升浪\logs\final_backtest.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*70+"\n")
    f.write("A最终回测: 次日必卖, 全仓, 全量买入\n")
    f.write("="*70+"\n\n")

    # Test: rolling half-position (A's actual mechanism)
    # pos_old: bought 2 days ago, sold TODAY at HIGH (intraday execution)
    # pos_new: bought yesterday, held, moves to pos_old tomorrow
    # Each day: sell pos_old at HIGH, rotate pos_new->pos_old, buy new at open with 50%
    f.write("半仓轮动模型 (2日持仓, 卖旧买新):\n")
    f.write(f"{'卖出价':<25} {'仓位':>6} {'最终':>10} {'收益':>8} {'距目标':>8}\n")
    f.write("-"*60+"\n")

    for pos_pct in [0.45, 0.50, 0.55]:
        for sp_mode,sp_label in [
            ('high','旧仓卖在最高价'),
            ('ho','旧仓卖在(H+O)/2'),
            ('close','旧仓卖在收盘价'),
        ]:
            INIT=200000; TARGET=1022000
            pos_old=None; pos_new=None; cash=INIT; tlist=[]
            for didx,date in enumerate(all_dates):
                t=timeline[date]
                it_old=None; it_new=None
                if pos_old: it_old=pdb.get(pos_old['n'],{}).get(date)
                if pos_new: it_new=pdb.get(pos_new['n'],{}).get(date)

                # SELL pos_old at HIGH (intraday good price)
                if pos_old and it_old:
                    if sp_mode=='high': sp=it_old['high']
                    elif sp_mode=='ho': sp=(it_old['high']+it_old['open'])/2
                    else: sp=it_old['close']
                    if sp>0:
                        pnl=(sp-pos_old['bp'])/pos_old['bp']*100; tlist.append({'pnl':pnl})
                        cash+=sp*pos_old['s']; pos_old=None

                # pos_new becomes pos_old (will be sold tomorrow)
                pos_old=pos_new; pos_new=None

                # BUY with 50% cash at open
                if t['buy']:
                    bn=t['buy']
                    if bn in pdb and date in pdb[bn]:
                        bp_=pdb[bn][date]['open']
                        deploy=cash*pos_pct; sh=int(deploy/bp_/100)*100
                        if sh>0: cash-=sh*bp_; pos_new={'n':bn,'b':date,'bp':bp_,'s':sh}

                pv=0
                if pos_old and pdb.get(pos_old['n'],{}).get(date):
                    pv+=pos_old['s']*pdb[pos_old['n']][date]['close']
                if pos_new and pdb.get(pos_new['n'],{}).get(date):
                    pv+=pos_new['s']*pdb[pos_new['n']][date]['close']

            # Sell remaining positions
            if pos_old:
                last_d=all_dates[-1]
                it=pdb.get(pos_old['n'],{}).get(last_d)
                if it:
                    sp=it['high'] if sp_mode=='high' else ((it['high']+it['open'])/2 if sp_mode=='ho' else it['close'])
                    if sp>0:
                        pnl=(sp-pos_old['bp'])/pos_old['bp']*100; tlist.append({'pnl':pnl})
                        cash+=sp*pos_old['s']
            if pos_new:
                last_d=all_dates[-1]
                it=pdb.get(pos_new['n'],{}).get(last_d)
                if it:
                    sp=it['high'] if sp_mode=='high' else ((it['high']+it['open'])/2 if sp_mode=='ho' else it['close'])
                    if sp>0:
                        pnl=(sp-pos_new['bp'])/pos_new['bp']*100; tlist.append({'pnl':pnl})
                        cash+=sp*pos_new['s']

            final=cash; ret=(final-INIT)/INIT*100; diff=final-TARGET
            wr=sum(1 for t in tlist if t['pnl']>0)/max(len(tlist),1)*100
            mark=' <-- CLOSE' if abs(diff)<120000 else ''
            f.write(f"{sp_label:<25} {pos_pct*100:>4.0f}% {final:>10,.0f} {ret:>+7.1f}% {diff:>+8,.0f} wr={wr:.0f}%{mark}\n")
        f.write("\n")

    # Score-based position sizing
    def quick_score(name, date):
        if name not in pdb or date not in pdb[name]: return 0
        kls=stock_data[name]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
        if not idxs or idxs[0]<1: return 0
        idx=idxs[0]; pd_=kls[idx-1]['day']
        if pd_ not in pdb[name]: return 0
        t1=pdb[name][pd_]
        if not t1['is_limit_up']: return 0
        sc=0
        v20=sum(float(kls[j]['volume']) for j in range(max(0,idx-20),idx))/20 if idx>=20 else float(kls[idx]['volume'])
        vr20=float(kls[idx]['volume'])/v20 if v20>0 else 1
        if vr20<0.3: sc+=35
        elif vr20<0.5: sc+=28
        elif vr20<0.7: sc+=22
        elif vr20<1.0: sc+=16
        elif vr20<1.5: sc+=8
        elif vr20<2.0: sc+=2
        elif vr20<3.0: sc-=3
        elif vr20<5.0: sc-=10
        else: sc-=18
        g=t1['gap_open_pct']
        if g>=9.5: sc+=22
        elif g>=8: sc+=18
        elif g>=5: sc+=13
        elif g>=3: sc+=7
        elif g>=1: sc+=2
        else: sc-=12
        cons=0; j=idx-1
        while j>=0:
            cd_=kls[j]['day']
            if cd_ in pdb[name] and pdb[name][cd_]['is_limit_up']: cons+=1; j-=1
            else: break
        if cons==1: sc+=10
        elif cons==2: sc+=12
        elif cons>=3: sc+=7
        else: sc+=3
        return sc

    f.write("\n评分分档仓位 (次日必卖, 卖在HIGH):\n")
    f.write(f"{'高分全仓阈值':>12} {'最终':>10} {'收益':>8} {'距目标':>8}\n")
    f.write("-"*42+"\n")

    for score_cut in [30, 40, 50]:
        for INIT, init_label in [(300000,'30万'),(200000,'20万')]:
            TARGET=1022000
            pos_list=[]; cash=INIT; tlist=[]
        for didx,date in enumerate(all_dates):
            t=timeline[date]
            for p in pos_list[:]:
                n=p['n']; bp_=p['bp']
                if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
                it=pdb[n][date]; sp=it['high']
                if sp>0: pnl=(sp-bp_)/bp_*100; tlist.append({'pnl':pnl}); cash+=sp*p['s']; pos_list.remove(p)
            if t['buy']:
                bn=t['buy']
                if bn in pdb and date in pdb[bn]:
                    sc=quick_score(bn,date)
                    pos_pct=1.0 if sc>=score_cut else 0.5
                    bp_=pdb[bn][date]['open']; deploy=cash*pos_pct; sh=int(deploy/bp_/100)*100
                    if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})
            pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
        final=cash+pv; ret=(final-INIT)/INIT*100; diff=final-TARGET
        wr=sum(1 for t in tlist if t['pnl']>0)/max(len(tlist),1)*100
        mark=' <--' if abs(diff)<150000 else ''
        f.write(f"评分>={score_cut}全仓: {final:>10,.0f} {ret:>+7.1f}% {diff:>+8,.0f} wr={wr:.0f}%{mark}\n")

    f.write("\n30万初始+评分>=30全仓:\n")
    for INIT in [300000]:
        for sc in [30]:
            pos_list=[]; cash=INIT
            for didx,date in enumerate(all_dates):
                t=timeline[date]
                for p in pos_list[:]:
                    n=p['n']; bp_=p['bp']
                    if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
                    it=pdb[n][date]; sp=it['high']
                    if sp>0: cash+=sp*p['s']; pos_list.remove(p)
                if t['buy']:
                    bn=t['buy']
                    if bn in pdb and date in pdb[bn]:
                        sscore=quick_score(bn,date)
                        pp=1.0 if sscore>=sc else 0.5
                        bp_=pdb[bn][date]['open']; deploy=cash*pp; sh=int(deploy/bp_/100)*100
                        if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})
                pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
            final=cash+pv; ret=(final-INIT)/INIT*100
            f.write(f"30万 -> {final:,.0f} ({ret:+.1f}%)\n")

print(f"Done: {out_path}")
