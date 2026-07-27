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

# Simulate with CORRECTED T-1 data
pos_list=[]; cash=200000; trades=[]
for didx,date in enumerate(ad):
    rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
    for p in pos_list[:]:
        n=p['n']; bp_=p['bp']
        if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
        it=pdb[n][date]; ip=pdb[n].get(pd_) if pd_ else None
        if not (ip and ip['is_limit_up']):
            sp=it['high']
            if sp>0:
                pnl=(sp-bp_)/bp_*100
                hd=(datetime.strptime(date,'%Y-%m-%d')-datetime.strptime(p['b'],'%Y-%m-%d')).days
                # CORRECTED: use T-1 data (the day BEFORE buy)
                t1_vr20=p.get('t1_vr20',0); t1_gap=p.get('t1_gap',0); t1_lu=p.get('t1_lu',False)
                buy_gap=it['gap_open_pct']; buy_lu=it['is_limit_up']
                # Also get buy-day volume info
                buy_vr20=it.get('vr20',0)
                trades.append({
                    'name':n,'buy_date':p['b'],'sell_date':date,
                    'buy_price':bp_,'sell_price':sp,'pnl':pnl,'hd':hd,
                    't1_vr20':t1_vr20,'t1_gap':t1_gap,'t1_lu':t1_lu,
                    'buy_gap':buy_gap,'buy_lu':buy_lu,'buy_vr20':buy_vr20,
                })
                cash+=sp*p['s']; pos_list.remove(p)
    if rec!='休息' and len(pos_list)==0:
        bn=rec
        if bn in pdb and date in pdb[bn]:
            bp_=pdb[bn][date]['open']; sh=int(cash/bp_/100)*100
            if sh>0:
                # CORRECTED: get T-1 data at buy time
                kls=stock_data[bn]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
                t1_vr20=0; t1_gap=0; t1_lu=False
                if idxs and idxs[0]>=1:
                    t1d=kls[idxs[0]-1]['day']
                    if t1d in pdb[bn]:
                        t1=pdb[bn][t1d]
                        t1_vr20=t1.get('vr20',0); t1_gap=t1.get('gap_open_pct',0); t1_lu=t1['is_limit_up']
                cash-=sh*bp_
                pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh,'t1_vr20':t1_vr20,'t1_gap':t1_gap,'t1_lu':t1_lu})

trades.sort(key=lambda x:x['pnl'])
losers=[t for t in trades if t['pnl']<0]

out_path=r'C:\Users\Davis\Desktop\主升浪\logs\worst_trades_v2.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*110+"\n")
    f.write("交易员A 亏损交易分析 (修正版: T-1数据正确取自买入前一日)\n")
    f.write("="*110+"\n\n")
    f.write(f"总交易: {len(trades)} | 亏损: {len(losers)} | 胜率: {(len(trades)-len(losers))/len(trades)*100:.0f}%\n\n")

    f.write(f"{'#':<3} {'买入日':<12} {'标的':<10} {'盈亏':>8} {'T-1量比':>8} {'T-1gap':>8} {'买入日量比':>10} {'买入日gap':>10} {'持天':>4}\n")
    f.write("-"*80+"\n")
    for i,t in enumerate(losers):
        f.write(f"{i+1:<3} {t['buy_date']:<12} {t['name']:<10} {t['pnl']:>+7.1f}% {t['t1_vr20']:>7.1f}x {t['t1_gap']:>+7.1f}% {t['buy_vr20']:>9.1f}x {t['buy_gap']:>+9.1f}% {t['hd']:>4}\n")

    # Compare: how many losers had T-1 >3x vs buy-day >3x?
    t1_bad=sum(1 for t in losers if t['t1_vr20']>3)
    buy_bad=sum(1 for t in losers if t['buy_vr20']>3)
    f.write(f"\nT-1放量(>3x): {t1_bad}/{len(losers)}笔\n")
    f.write(f"买入日放量(>3x): {buy_bad}/{len(losers)}笔\n")
    f.write(f"\n之前错误地把买入日量比当T-1, 导致高估了T-1放量的影响\n")

print(f"Done: {out_path}")
