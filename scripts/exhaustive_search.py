import json, openpyxl
from datetime import datetime, timedelta

with open(r'C:\Users\Davis\Desktop\主升浪\stock_data.json','r',encoding='utf-8') as f:
    stock_data=json.load(f)
def ed(s): return datetime(1899,12,30)+timedelta(days=int(s))
wb=openpyxl.load_workbook(r'C:\Users\Davis\Desktop\主升浪\副本主升浪.xlsx')
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
        if pc and pc>0:
            e['is_limit_up']=lu(c,pc,lpt); e['gap_open_pct']=(o-pc)/pc*100
        pdb[name][dt]=e; pc=c

tl=[]
for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
ad=sorted(set(d for d,_ in tl))
INIT=200000; TARGET=1000000

out_path=r'C:\Users\Davis\Desktop\主升浪\exhaustive_results.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("穷举搜索: 找到使20万->100万的卖出规则\n")
    f.write("="*80+"\n\n")

    # Test ALL combinations of:
    # 1. Check what? yesterday_lu / today_open_lu / today_close_lu / today_open_strength
    # 2. Low open threshold
    # 3. Logic: OR / AND
    # 4. Sell price: open / close / vwap

    results=[]

    # Check modes
    # mode 0: yesterday not LU (original)
    # mode 1: today not opening at LU price
    # mode 2: today not CLOSING at LU price (sell next open)
    # mode 3: today open below strength threshold
    # mode 4: yesterday not LU AND today opens below prev close (combo)

    for mode in range(5):
        for strength in [9.5,9,8,7,6,5,4,3,2,1,0]:
            for low_thresh in [0,-0.5,-1,-2,-3,-5]:
                for logic in ['OR','AND']:
                    for sp_mode in ['open','close','vwap']:
                        pos=[]; cash=INIT
                        for didx,date in enumerate(ad):
                            rec=dict(tl).get(date,'休息')
                            pd_=ad[didx-1] if didx>0 else None

                            for p in pos[:]:
                                n=p['n']; bp_=p['bp']
                                if n not in pdb or date not in pdb[n]:
                                    pos.remove(p); continue
                                it=pdb[n][date]; ip=pdb[n].get(pd_) if pd_ else None

                                cond1=False; cond2=False

                                if mode==0:
                                    # yesterday not LU
                                    cond1=not (ip and ip['is_limit_up'])
                                    # low open vs prev close
                                    cond2=ip and ip['close']>0 and (it['open']-ip['close'])/ip['close']*100<=low_thresh if ip else False
                                elif mode==1:
                                    # today not opening at LU
                                    prev_c=ip['close'] if ip else 0
                                    if prev_c>0:
                                        today_lu_p=round(prev_c*(1+lp(sm.get(n,'600000'))),2)
                                        cond1=it['open']<today_lu_p-0.005
                                    else: cond1=True
                                    cond2=ip and it['open']<ip['close'] if ip else False
                                elif mode==2:
                                    # yesterday not LU (using close data from 2 days ago)
                                    cond1=not (ip and ip['is_limit_up'])
                                    cond2=ip and it['open']<ip['close'] if ip else False
                                elif mode==3:
                                    # open strength below threshold
                                    cond1=it['gap_open_pct']<strength
                                    cond2=ip and it['open']<ip['close'] if ip else False
                                elif mode==4:
                                    # combo: yesterday not LU + strength below
                                    cond1=not (ip and ip['is_limit_up'])
                                    cond2=it['gap_open_pct']<strength

                                if logic=='OR':
                                    should_sell=cond1 or cond2
                                else:
                                    should_sell=cond1 and cond2

                                if should_sell:
                                    if sp_mode=='open': sp=it['open']
                                    elif sp_mode=='close': sp=it['close']
                                    else: sp=(it['high']+it['low']+it['close'])/3
                                    if sp>0: cash+=sp*p['s']; pos.remove(p)

                            if rec!='休息' and len(pos)==0:
                                bn=rec
                                if bn in pdb and date in pdb[bn]:
                                    bp_=pdb[bn][date]['open']; sh=int(cash/bp_/100)*100
                                    if sh>0: cash-=sh*bp_; pos.append({'n':bn,'b':date,'bp':bp_,'s':sh})

                            pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos)

                        final=cash+pv; diff=abs(final-TARGET)
                        results.append({'m':mode,'s':strength,'lt':low_thresh,
                                       'logic':logic,'sp':sp_mode,'final':final,'diff':diff})

    results.sort(key=lambda x:x['diff'])
    f.write(f"{'Mode':<5} {'强度':<6} {'低开阈':<7} {'逻辑':<5} {'卖价':<6} {'最终':>10} {'距目标':>10}\n")
    f.write("-"*55+"\n")
    for r in results[:30]:
        mode_names={0:'昨不LU',1:'今不开LU',2:'今不收LU',3:'开<强度',4:'昨不LU+开<强'}
        f.write(f"{mode_names[r['m']]:<5} {r['s']:>5.1f}% {r['lt']:>+6.1f}% {r['logic']:<5} {r['sp']:<6} {r['final']:>10,.0f} {r['final']-TARGET:>+10,.0f}\n")

    best=results[0]
    f.write(f"\n最佳: mode={best['m']} strength={best['s']} low={best['lt']} logic={best['logic']} sp={best['sp']} -> {best['final']:,.0f}\n")

print(f"Done: {out_path}")
