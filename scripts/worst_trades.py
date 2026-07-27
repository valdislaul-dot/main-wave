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
        dt=k['day']; o=float(k['open']); c=float(k['close']); h=float(k['high']); l=float(k['low']);v=float(k['volume'])
        e={'open':o,'close':c,'high':h,'low':l,'volume':v,'is_limit_up':False,'prev_close':pc,'gap_open_pct':0}
        if pc and pc>0: e['is_limit_up']=lu(c,pc,lpt); e['gap_open_pct']=(o-pc)/pc*100
        if i>=20:
            e['v20']=sum(float(klines[j]['volume']) for j in range(i-20,i))/20
        else: e['v20']=v
        e['vr20']=v/e['v20'] if e['v20']>0 else 1
        pdb[name][dt]=e; pc=c

tl=[]
for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
ad=sorted(set(d for d,_ in tl))

# Simulate trader picks with executable rules
pos_list=[]; cash=200000; trades=[]
for didx,date in enumerate(ad):
    rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
    for p in pos_list[:]:
        n=p['n']; bp_=p['bp']
        if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
        it=pdb[n][date]; ip=pdb[n].get(pd_) if pd_ else None
        if not (ip and ip['is_limit_up']):
            sp=it['high']  # trader sells near high
            if sp>0:
                pnl=(sp-bp_)/bp_*100; pnl_amt=(sp-bp_)*p['s']
                hd=(datetime.strptime(date,'%Y-%m-%d')-datetime.strptime(p['b'],'%Y-%m-%d')).days
                # Get T-1 data of buy day
                t1_vr20=0; t1_gap=0; t1_cons=0; t1_lu=False
                if p['b'] in pdb[n]:
                    bi=pdb[n][p['b']]
                    t1_vr20=bi.get('vr20',0); t1_gap=bi.get('gap_open_pct',0)
                # Also get buy day gap
                buy_gap=0; buy_lu=False
                if date in pdb[n]:
                    bi2=pdb[n][date]
                    buy_gap=bi2.get('gap_open_pct',0); buy_lu=bi2['is_limit_up']
                trades.append({
                    'name':n,'buy_date':p['b'],'sell_date':date,
                    'buy_price':bp_,'sell_price':sp,'pnl':pnl,'hd':hd,
                    't1_vr20':t1_vr20,'t1_gap':t1_gap,
                    'buy_gap':buy_gap,'buy_lu':buy_lu,
                })
                cash+=sp*p['s']; pos_list.remove(p)
    if rec!='休息' and len(pos_list)==0:
        bn=rec
        if bn in pdb and date in pdb[bn]:
            bp_=pdb[bn][date]['open']; sh=int(cash/bp_/100)*100
            if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})

trades.sort(key=lambda x:x['pnl'])

out_path=r'C:\Users\Davis\Desktop\主升浪\logs\worst_trades.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*100+"\n")
    f.write("交易员A 亏损交易分析\n")
    f.write("="*100+"\n\n")

    losers=[t for t in trades if t['pnl']<0]
    winners=[t for t in trades if t['pnl']>=0]

    f.write(f"总交易: {len(trades)} | 盈利: {len(winners)} | 亏损: {len(losers)} | 胜率: {len(winners)/len(trades)*100:.0f}%\n")
    f.write(f"平均盈利: {sum(t['pnl'] for t in winners)/len(winners):+.1f}% | 平均亏损: {sum(t['pnl'] for t in losers)/len(losers):+.1f}%\n")
    f.write(f"盈亏比: {abs(sum(t['pnl'] for t in winners)/len(winners)/(sum(t['pnl'] for t in losers)/len(losers))):.1f}\n\n")

    f.write("="*100+"\n")
    f.write("亏损排序 (从最差开始)\n")
    f.write("="*100+"\n")
    f.write(f"{'#':<3} {'买入日':<12} {'标的':<10} {'盈亏':>8} {'持天':>4} {'T-1量比':>8} {'T-1开盘gap':>10} {'买入日gap':>10} {'买入日涨停':>8} {'可能原因':<20}\n")
    f.write("-"*100+"\n")

    for i,t in enumerate(losers[:20]):
        reason=""
        if t['t1_vr20']>5: reason="T-1巨量"
        elif t['t1_vr20']>3: reason+="T-1放量 "
        if t['t1_gap']<3 and t['t1_gap']>=0: reason+="T-1弱板 "
        if t['t1_gap']<0: reason+="T-1低开涨停 "
        if t['buy_gap']<0: reason+="买入日低开 "
        if t['hd']==1 and t['buy_lu']==False: reason+="次日断板 "
        if not reason: reason="综合因素"
        f.write(f"{i+1:<3} {t['buy_date']:<12} {t['name']:<10} {t['pnl']:>+7.1f}% {t['hd']:>4} {t['t1_vr20']:>7.1f}x {t['t1_gap']:>+9.1f}% {t['buy_gap']:>+9.1f}% {'Y' if t['buy_lu'] else 'N':>8} {reason:<20}\n")

    # Pattern summary
    f.write("\n"+"="*100+"\n")
    f.write("亏损模式归类\n")
    f.write("="*100+"\n\n")

    pat1=sum(1 for t in losers if t['t1_vr20']>3)
    pat2=sum(1 for t in losers if t['t1_gap']>=0 and t['t1_gap']<3)
    pat3=sum(1 for t in losers if t['buy_gap']<0)
    pat4=sum(1 for t in losers if t['t1_vr20']<1.0)

    f.write(f"T-1放量(>3x): {pat1}/{len(losers)}笔 — 追了放量板,次日承接不足\n")
    f.write(f"T-1弱板(gap 0-3%): {pat2}/{len(losers)}笔 — 板不够强,次日走弱\n")
    f.write(f"买入日低开: {pat3}/{len(losers)}笔 — 竞价就弱,全天没救回来\n")
    f.write(f"T-1缩量但仍亏: {pat4}/{len(losers)}笔 — 缩量也不是万能的\n\n")

    f.write("亏损区间分布:\n")
    ranges={'0~-5%':0,'-5%~-10%':0,'-10%~-15%':0,'-15%~-20%':0,'<-20%':0}
    for t in losers:
        if t['pnl']>-5: ranges['0~-5%']+=1
        elif t['pnl']>-10: ranges['-5%~-10%']+=1
        elif t['pnl']>-15: ranges['-10%~-15%']+=1
        elif t['pnl']>-20: ranges['-15%~-20%']+=1
        else: ranges['<-20%']+=1
    for r,c in ranges.items():
        f.write(f"  {r}: {c}笔\n")

print(f"Done: {out_path}")
