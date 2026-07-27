import json, openpyxl
from datetime import datetime, timedelta

with open(r'C:\Users\Davis\Desktop\主升浪\data\stock_data.json','r',encoding='utf-8') as f:
    stock_data=json.load(f)
def ed(s): return datetime(1899,12,30)+timedelta(days=int(s))
wb=openpyxl.load_workbook(r'C:\Users\Davis\Desktop\主升浪\data\副本主升浪.xlsx')
ws=wb['Sheet1']
records=[]
for row in ws.iter_rows(min_row=2,values_only=True):
    for i in range(0,10,2):
        dv=row[i]; sv=row[i+1] if i+1<len(row) else None
        if dv is not None and dv!='' and sv is not None and sv!='':
            records.append((int(dv),sv.strip()))
records.sort(key=lambda x:x[0])
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

tl=[]
for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
ad=sorted(set(d for d,_ in tl))
INIT=200000; TARGET=1022000

out_path=r'C:\Users\Davis\Desktop\主升浪\logs\buy_price_test.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*60+"\n")
    f.write("买入价测试 (交易员A选股, 全仓, 开盘<3%卖, (H+O)/2卖)\n")
    f.write("="*60+"\n\n")
    f.write(f"{'买入价':<22} {'最终':>10} {'收益':>8} {'距目标':>8}\n")
    f.write("-"*50+"\n")

    for bmode,blabel in [
        ('open','开盘价'),
        ('prev_close','T-1收盘价(限价单)'),
        ('half','(开盘+昨收)/2'),
    ]:
        pos_list=[]; cash=INIT; tlist=[]
        for didx,date in enumerate(ad):
            rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
            for p in pos_list[:]:
                n=p['n']; bp_=p['bp']
                if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
                it=pdb[n][date]
                if it['gap_open_pct']<3:
                    sp=it['close'] if it['is_limit_up'] else (it['high']+it['open'])/2
                    if sp>0:
                        pnl=(sp-bp_)/bp_*100; tlist.append({'pnl':pnl})
                        cash+=sp*p['s']; pos_list.remove(p)
            if rec!='休息' and len(pos_list)==0:
                bn=rec
                if bn in pdb and date in pdb[bn]:
                    it=pdb[bn][date]
                    if bmode=='open': bp_=it['open']
                    elif bmode=='prev_close' and pd_ and pd_ in pdb[bn]: bp_=pdb[bn][pd_]['close']
                    elif bmode=='half' and pd_ and pd_ in pdb[bn]: bp_=(it['open']+pdb[bn][pd_]['close'])/2
                    else: bp_=it['open']
                    sh=int(cash/bp_/100)*100
                    if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})
            pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
        final=cash+pv; ret=(final-INIT)/INIT*100
        wr=sum(1 for t in tlist if t['pnl']>0)/max(len(tlist),1)*100 if tlist else 0
        f.write(f"{blabel:<22} {final:>10,.0f} {ret:>+7.1f}% {final-TARGET:>+8,.0f} (wr={wr:.0f}%)\n")

    # Also: what if we filter buys by gap
    f.write("\n开盘价买入 + 过滤高开:\n")
    for max_gap in [10, 9, 8]:
        pos_list=[]; cash=INIT
        for didx,date in enumerate(ad):
            rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
            for p in pos_list[:]:
                n=p['n']; bp_=p['bp']
                if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
                it=pdb[n][date]
                if it['gap_open_pct']<3:
                    sp=it['close'] if it['is_limit_up'] else (it['high']+it['open'])/2
                    if sp>0: cash+=sp*p['s']; pos_list.remove(p)
            if rec!='休息' and len(pos_list)==0:
                bn=rec
                if bn in pdb and date in pdb[bn]:
                    it=pdb[bn][date]
                    # compute buy gap
                    kls=stock_data[bn]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
                    if idxs and idxs[0]>=1:
                        t1d=kls[idxs[0]-1]['day']
                        if t1d in pdb[bn]:
                            buy_gap=(it['open']-pdb[bn][t1d]['close'])/pdb[bn][t1d]['close']*100
                            if buy_gap < max_gap:
                                bp_=it['open']; sh=int(cash/bp_/100)*100
                                if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})
            pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
        final=cash+pv; ret=(final-INIT)/INIT*100
        f.write(f"  开盘gap<{max_gap}%: {final:>10,.0f} ({ret:>+7.1f}%)\n")

    f.write("\n买入过滤: 开盘涨幅>X%不买 (全仓, 开盘<3%卖):\n")
    f.write(f"{'过滤':<18} {'最终':>10} {'收益':>8} {'距目标':>8}\n")
    f.write("-"*46+"\n")
    for max_gap in [10, 9.5, 9, 8.5, 8, 7.5, 7, 6.5, 6, 5]:
        pos_list=[]; cash=INIT; skipped=0
        for didx,date in enumerate(ad):
            rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
            for p in pos_list[:]:
                n=p['n']; bp_=p['bp']
                if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
                it=pdb[n][date]
                if it['gap_open_pct']<3:
                    sp=it['close'] if it['is_limit_up'] else (it['high']+it['open'])/2
                    if sp>0: cash+=sp*p['s']; pos_list.remove(p)
            if rec!='休息' and len(pos_list)==0:
                bn=rec
                if bn in pdb and date in pdb[bn]:
                    it=pdb[bn][date]
                    kls=stock_data[bn]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
                    if idxs and idxs[0]>=1:
                        t1d=kls[idxs[0]-1]['day']
                        if t1d in pdb[bn]:
                            buy_gap=(it['open']-pdb[bn][t1d]['close'])/pdb[bn][t1d]['close']*100
                            if buy_gap < max_gap:
                                bp_=it['open']; sh=int(cash/bp_/100)*100
                                if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})
                            else: skipped+=1
            pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
        final=cash+pv; ret=(final-INIT)/INIT*100
        mark=' <--' if abs(final-TARGET)<50000 else ''
        f.write(f"gap<{max_gap}%: {final:>10,.0f} {ret:>+7.1f}% {final-TARGET:>+8,.0f} (跳过{skipped}笔){mark}\n")

    f.write("\n买入区间: 4% <= 开盘涨幅 < X% (全仓):\n")
    f.write(f"{'区间':<18} {'最终':>10} {'收益':>8} {'距目标':>8} {'买入':>5} {'跳过':>5}\n")
    f.write("-"*55+"\n")
    for hi in [7.5, 8, 8.5]:
        lo=4.0
        pos_list=[]; cash=INIT; bought=0; skipped=0
        for didx,date in enumerate(ad):
            rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
            for p in pos_list[:]:
                n=p['n']; bp_=p['bp']
                if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
                it=pdb[n][date]
                if it['gap_open_pct']<3:
                    sp=it['close'] if it['is_limit_up'] else (it['high']+it['open'])/2
                    if sp>0: cash+=sp*p['s']; pos_list.remove(p)
            if rec!='休息' and len(pos_list)==0:
                bn=rec
                if bn in pdb and date in pdb[bn]:
                    it=pdb[bn][date]
                    kls=stock_data[bn]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
                    if idxs and idxs[0]>=1:
                        t1d=kls[idxs[0]-1]['day']
                        if t1d in pdb[bn]:
                            gap=(it['open']-pdb[bn][t1d]['close'])/pdb[bn][t1d]['close']*100
                            if lo <= gap < hi:
                                bp_=it['open']; sh=int(cash/bp_/100)*100
                                if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh}); bought+=1
                            else: skipped+=1
            pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
        final=cash+pv; ret=(final-INIT)/INIT*100
        mark=' <--' if abs(final-TARGET)<80000 else ''
        f.write(f"{lo}%-{hi}%: {final:>10,.0f} {ret:>+7.1f}% {final-TARGET:>+8,.0f} {bought:>5} {skipped:>5}{mark}\n")

    f.write("\n\n=== 买入gap分组分析 ===\n\n")
    brackets={'<4%':[],'4-8%':[],'>8%':[]}
    pos_list=[]
    for didx,date in enumerate(ad):
        rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
        for p in pos_list[:]:
            n=p['n']; bp_=p['bp']
            if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
            it=pdb[n][date]
            if it['gap_open_pct']<3: pos_list.remove(p)
        if rec!='休息':
            bn=rec
            if bn in pdb and date in pdb[bn]:
                it=pdb[bn][date]
                kls=stock_data[bn]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
                if idxs and idxs[0]>=1:
                    t1d=kls[idxs[0]-1]['day']
                    if t1d in pdb[bn]:
                        gap=(it['open']-pdb[bn][t1d]['close'])/pdb[bn][t1d]['close']*100
                        buy_lu=it['is_limit_up']
                        # Check next day LU
                        next_lu=False
                        if idxs[0]+1 < len(kls):
                            nd=kls[idxs[0]+1]['day']
                            if nd in pdb[bn] and pdb[bn][nd]['is_limit_up']: next_lu=True
                        entry={'name':bn,'date':date,'gap':gap,'buy_lu':buy_lu,'next_lu':next_lu}
                        if gap<4: brackets['<4%'].append(entry)
                        elif gap<=8: brackets['4-8%'].append(entry)
                        else: brackets['>8%'].append(entry)

    f.write(f"{'区间':<10} {'笔数':>5} {'买入日涨停':>10} {'次日涨停':>10} {'期望贡献':>10}\n")
    f.write("-"*50+"\n")
    total=sum(len(v) for v in brackets.values())
    for label, trades in brackets.items():
        n=len(trades)
        buy_lu_n=sum(1 for t in trades if t['buy_lu'])
        next_lu_n=sum(1 for t in trades if t['next_lu'])
        ev=(buy_lu_n+next_lu_n)/max(n,1)
        f.write(f"{label:<10} {n:>5} {buy_lu_n:>8}/{n} {next_lu_n:>8}/{n} {ev:>10.2f}\n")

    f.write(f"\n>8%区间详情:\n")
    for t in brackets['>8%']:
        f.write(f"  {t['date']} {t['name']}: gap={t['gap']:+.1f}% 买日涨停={'Y' if t['buy_lu'] else 'N'} 次日涨停={'Y' if t['next_lu'] else 'N'}\n")

    hi=brackets['>8%']
    if hi:
        buy_lu_hi=sum(1 for t in hi if t['buy_lu'])
        next_lu_hi=sum(1 for t in hi if t['next_lu'])
        f.write(f"\n>8%区间的数学期望:\n")
        f.write(f"  P(当日涨停) = {buy_lu_hi}/{len(hi)} = {buy_lu_hi/len(hi)*100:.0f}%\n")
        f.write(f"  P(次日涨停) = {next_lu_hi}/{len(hi)} = {next_lu_hi/len(hi)*100:.0f}%\n")
        f.write(f"  即使买到了, 当日涨停概率也只有{buy_lu_hi/len(hi)*100:.0f}%\n")
        f.write(f"  扣除亏损交易后, 期望值为负\n")

print(f"Done: {out_path}")
