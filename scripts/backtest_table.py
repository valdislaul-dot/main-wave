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
        dt=k['day']; o=float(k['open']); c=float(k['close']); h=float(k['high']); l=float(k['low']); v=float(k['volume'])
        e={'open':o,'close':c,'high':h,'low':l,'volume':v,'is_limit_up':False,'prev_close':pc,'gap_open_pct':0}
        if pc and pc>0:
            e['is_limit_up']=lu(c,pc,lpt); e['gap_open_pct']=(o-pc)/pc*100
        if i>=5: e['vol_ma5']=sum(float(klines[j]['volume']) for j in range(i-5,i))/5
        else: e['vol_ma5']=v
        if i>=20: e['vol_ma20']=sum(float(klines[j]['volume']) for j in range(i-20,i))/20
        else: e['vol_ma20']=v
        e['vol_ratio5']=v/e['vol_ma5'] if e['vol_ma5']>0 else 1
        e['vol_ratio20']=v/e['vol_ma20'] if e['vol_ma20']>0 else 1
        pdb[name][dt]=e; pc=c

tl=[]
for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
ad=sorted(set(d for d,_ in tl))
INIT=200000

def score_v2(name,date):
    if name not in pdb or date not in pdb[name]: return -999
    kls=stock_data[name]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
    if not idxs or idxs[0]<1: return -999
    idx=idxs[0]; pd_=kls[idx-1]['day']
    if pd_ not in pdb[name]: return -999
    t1=pdb[name][pd_]
    if not t1['is_limit_up']: return -999
    bi=pdb[name][date]; s=0.0
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
    bg=bi['gap_open_pct']
    if bg>8: s+=8
    elif bg>5: s+=5
    elif bg>2: s+=2
    elif bg>0: s+=0
    elif bg>-2: s-=5
    else: s-=25
    return s

def get_mp(date):
    cs=[]
    for name in pdb:
        sc=score_v2(name,date)
        if sc>=30:
            kls=stock_data[name]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
            if not idxs or idxs[0]<1: continue
            idx=idxs[0]; pd_=kls[idx-1]['day']; t1=pdb[name][pd_]
            cs.append({'name':name,'score':sc,'v20':t1.get('vol_ratio20',1)})
    cs.sort(key=lambda x:x['score'],reverse=True)
    if not cs: return None
    top3=cs[:3]; top3.sort(key=lambda x:x['v20'])
    return top3[0]['name']

# ============ RUN BACKTEST ============
out_path=r'C:\Users\Davis\Desktop\主升浪\backtest_table.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*110+"\n")
    f.write("完整回测表格 | 初始资金:200,000 | 模型选股(评分>=30) | 55%仓位 | 高价卖出\n")
    f.write("="*110+"\n\n")
    hdr=f"{'日期':<12} {'操作':<8} {'标的':<10} {'价格':>8} {'股数':>6} {'金额':>10} {'持仓市值':>10} {'现金':>10} {'总资产':>10} {'日收益':>10} {'累计收益%':>8}"
    f.write(hdr+"\n")
    f.write("-"*110+"\n")

    pos_list=[]; cash=INIT; prev_total=INIT; daily_log=[]

    for didx,date in enumerate(ad):
        rec=dict(tl).get(date,'休息')
        pd_=ad[didx-1] if didx>0 else None
        action=""; symbol=""; price=0; shares=0; amount=0; note=""

        # SELL
        for p in pos_list[:]:
            n=p['n']; bp_=p['bp']
            if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
            it=pdb[n][date]; ip=pdb[n].get(pd_) if pd_ else None
            not_strong=it['gap_open_pct']<6
            opens_low=ip and ip['close']>0 and it['open']<ip['close'] if ip else False
            if not_strong or opens_low:
                sp=it['high']
                if sp>0:
                    pnl=(sp-bp_)/bp_*100
                    proceeds=sp*p['s']
                    action="卖出"; symbol=n; price=sp; shares=p['s']; amount=proceeds
                    cash+=proceeds; pos_list.remove(p)
                    f.write(f"{date:<12} {action:<8} {symbol:<10} {price:>8.2f} {shares:>6} {amount:>10,.0f} ")
                    pv=sum(pp['s']*pdb.get(pp['n'],{}).get(date,{}).get('close',pp['bp']) for pp in pos_list)
                    total=cash+pv
                    daily_ret=total-prev_total
                    cum_ret=(total-INIT)/INIT*100
                    f.write(f"{pv:>10,.0f} {cash:>10,.0f} {total:>10,.0f} {daily_ret:>+10,.0f} {cum_ret:>+7.1f}%\n")
                    prev_total=total

        # BUY
        if rec!='休息' and len(pos_list)==0:
            bn=get_mp(date)
            if bn and bn in pdb and date in pdb[bn]:
                bp_=pdb[bn][date]['open']
                deploy=cash*0.55; sh=int(deploy/bp_/100)*100
                if sh>0:
                    cost=sh*bp_
                    cash-=cost
                    pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})
                    action="买入"; symbol=bn; price=bp_; shares=sh; amount=cost

        # End of day summary
        pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
        total=cash+pv
        daily_ret=total-prev_total
        cum_ret=(total-INIT)/INIT*100

        if action:
            pass  # already printed
        else:
            held_names=[f"{p['n']}({p['b']})" for p in pos_list]
            action="持仓" if pos_list else ("休息" if rec=='休息' else "无候选")
            f.write(f"{date:<12} {action:<8} {','.join(held_names) if held_names else '-':<10} {'':>8} {'':>6} {'':>10} ")
            f.write(f"{pv:>10,.0f} {cash:>10,.0f} {total:>10,.0f} {daily_ret:>+10,.0f} {cum_ret:>+7.1f}%\n")

        prev_total=total
        daily_log.append({'date':date,'action':action,'symbol':symbol,'total':total,'cash':cash,'pv':pv,'daily_ret':daily_ret,'cum_ret':cum_ret})

    # Final summary
    f.write("-"*110+"\n")
    final=prev_total
    f.write(f"\n最终资产: {final:,.0f} | 总收益: {final-INIT:+,.0f} | 总收益率: {(final-INIT)/INIT*100:+.1f}%\n")

    # Also write CSV for easy import
    csv_path=r'C:\Users\Davis\Desktop\主升浪\backtest_table.csv'
    with open(csv_path,'w',encoding='utf-8-sig') as fc:
        fc.write("日期,操作,标的,价格,股数,金额,持仓市值,现金,总资产,日收益,累计收益率\n")
        for log in daily_log:
            fc.write(f"{log['date']},{log['action']},{log.get('symbol','')},,,,,{log['total']:.0f},{log['daily_ret']:.0f},{log['cum_ret']:.1f}%\n")

    print(f"Table: {out_path}")
    print(f"CSV: {csv_path}")

print(f"Done")
