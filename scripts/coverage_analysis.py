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
        if h>l>0:
            e['seal_quality']=(c-l)/(h-l); us=(h-max(o,c))/(h-l); body=abs(c-o)/(h-l)
            e['is_one_line']=(us<0.1 and body<0.1)
        else: e['seal_quality']=1; e['is_one_line']=False
        cons=0
        for j in range(i-1,max(i-10,-1),-1):
            cd_=klines[j]['day']
            if cd_ in pdb[name] and pdb[name][cd_]['is_limit_up']: cons+=1
            else: break
        e['cons_lu_before']=cons
        pdb[name][dt]=e; pc=c

tl=[]
for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
ad=sorted(set(d for d,_ in tl))

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
    t2_lu=False
    if idx>=2:
        t2d=kls[idx-2]['day']
        if t2d in pdb[name]: t2_lu=pdb[name][t2d]['is_limit_up']
    if t2_lu: s+=6
    return s

out_path=r'C:\Users\Davis\Desktop\主升浪\coverage_results.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*90+"\n")
    f.write("选股策略覆盖率分析: 交易员的实际选择是否在我们推测的候选池中?\n")
    f.write("="*90+"\n")
    f.write("候选池: T-1涨停的股票, 按V2评分排序\n\n")

    f.write(f"{'日期':<12} {'总候选':>5} {'交易员选':<10} {'模型排名':>8} {'Top3?':>6} {'Top5?':>6} {'Top10?':>6} {'不在池中?':>10}\n")
    f.write("-"*80+"\n")

    in_top3=0; in_top5=0; in_top10=0; not_in_pool=0; total=0
    rank_sum=0; rank_count=0
    missing_dates=[]

    for date in ad:
        rec=dict(tl).get(date,'休息')
        if rec=='休息': continue
        total+=1

        # Build candidate pool
        cands=[]
        for name in pdb:
            sc=score_v2(name,date)
            if sc>-999:
                kls=stock_data[name]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
                idx=idxs[0]; pd_=kls[idx-1]['day']; t1=pdb[name][pd_]
                cands.append({'name':name,'score':sc,'v20':t1.get('vol_ratio20',1)})
        cands.sort(key=lambda x:x['score'],reverse=True)

        # Find trader's pick in ranking
        rank=None
        for i,c in enumerate(cands):
            if c['name']==rec:
                rank=i+1; break

        # Also check if trader's pick even had T-1 LU
        t1_lu=False
        if rec in pdb and date in pdb[rec]:
            kls=stock_data[rec]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
            if idxs and idxs[0]>=1:
                pd_=kls[idxs[0]-1]['day']
                if pd_ in pdb[rec] and pdb[rec][pd_]['is_limit_up']:
                    t1_lu=True

        t3="Y" if rank and rank<=3 else "N"
        t5="Y" if rank and rank<=5 else "N"
        t10="Y" if rank and rank<=10 else "N"
        not_in="NOT IN POOL" if rank is None else ""

        if rank and rank<=3: in_top3+=1
        if rank and rank<=5: in_top5+=1
        if rank and rank<=10: in_top10+=1
        if rank is None: not_in_pool+=1; missing_dates.append((date,rec,t1_lu))
        if rank: rank_sum+=rank; rank_count+=1

        f.write(f"{date:<12} {len(cands):>5} {rec:<10} {rank if rank else 'N/A':>8} {t3:>6} {t5:>6} {t10:>6} {not_in:>10}\n")

    f.write(f"\n--- 统计 ---\n")
    f.write(f"总交易天数: {total}\n")
    f.write(f"交易员选在Top3内: {in_top3}/{total} ({in_top3/total*100:.0f}%)\n")
    f.write(f"交易员选在Top5内: {in_top5}/{total} ({in_top5/total*100:.0f}%)\n")
    f.write(f"交易员选在Top10内: {in_top10}/{total} ({in_top10/total*100:.0f}%)\n")
    f.write(f"交易员选不在候选池中: {not_in_pool}/{total} ({not_in_pool/total*100:.0f}%)\n")
    if rank_count>0: f.write(f"平均排名: {rank_sum/rank_count:.1f}\n")

    if missing_dates:
        f.write(f"\n不在候选池中的交易 (需扩展策略覆盖):\n")
        for dt,nm,has_lu in missing_dates:
            f.write(f"  {dt} {nm}: T-1涨停={has_lu}")
            if not has_lu:
                # Check T-2
                kls=stock_data[nm]; idxs=[i for i,k in enumerate(kls) if k['day']==dt]
                if idxs and idxs[0]>=2:
                    t2d=kls[idxs[0]-2]['day']
                    t2_lu=pdb[nm][t2d]['is_limit_up'] if t2d in pdb[nm] else False
                    f.write(f" T-2涨停={t2_lu}")
            f.write("\n")

print(f"Done: {out_path}")
