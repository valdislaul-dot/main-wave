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
        dt=k['day']; o=float(k['open']); c=float(k['close']); h=float(k['high']); l=float(k['low']); v=float(k['volume'])
        e={'open':o,'close':c,'high':h,'low':l,'volume':v,'is_limit_up':False,'prev_close':pc,'gap_open_pct':0}
        if pc and pc>0: e['is_limit_up']=lu(c,pc,lpt); e['gap_open_pct']=(o-pc)/pc*100
        if i>=20: e['v20']=sum(float(klines[j]['volume']) for j in range(i-20,i))/20
        else: e['v20']=v
        e['vr20']=v/e['v20'] if e['v20']>0 else 1
        pdb[name][dt]=e; pc=c

tl=[]
for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
ad=sorted(set(d for d,_ in tl))
INIT=200000

# Compare three sell models vs HIGH (trader's actual)
pos_list=[]; cash=INIT; trades=[]
for didx,date in enumerate(ad):
    rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
    for p in pos_list[:]:
        n=p['n']; bp_=p['bp']
        if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
        it=pdb[n][date]; ip=pdb[n].get(pd_) if pd_ else None
        if not (ip and ip['is_limit_up']):
            sp_high=it['high']
            sp_ho=(it['high']+it['open'])/2
            sp_close=it['close']
            pnl_high=(sp_high-bp_)/bp_*100
            pnl_ho=(sp_ho-bp_)/bp_*100
            pnl_close=(sp_close-bp_)/bp_*100
            trades.append({
                'name':n,'buy_date':p['b'],'sell_date':date,
                'pnl_high':pnl_high,'pnl_ho':pnl_ho,'pnl_close':pnl_close,
                'is_lu':it['is_limit_up'],
            })
            cash+=sp_high*p['s']; pos_list.remove(p)
    if rec!='休息' and len(pos_list)==0:
        bn=rec
        if bn in pdb and date in pdb[bn]:
            bp_=pdb[bn][date]['open']; deploy=cash*0.55; sh=int(deploy/bp_/100)*100
            if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})

out_path=r'C:\Users\Davis\Desktop\主升浪\logs\gap_analysis_v2.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*100+"\n")
    f.write("卖出执行差距分析: HIGH vs (H+O)/2 vs CLOSE\n")
    f.write("="*100+"\n\n")

    lu_trades=[t for t in trades if t['is_lu']]
    non_lu=[t for t in trades if not t['is_lu']]

    f.write(f"涨停日卖出: {len(lu_trades)}笔\n")
    f.write(f"  HIGH={sum(t['pnl_high'] for t in lu_trades)/len(lu_trades):+.1f}% avg\n")
    f.write(f"  CLOSE={sum(t['pnl_close'] for t in lu_trades)/len(lu_trades):+.1f}% avg\n")
    f.write(f"  差距(HIGH-CLOSE): {sum(t['pnl_high']-t['pnl_close'] for t in lu_trades)/len(lu_trades):.1f}%\n\n")

    f.write(f"不涨停日卖出: {len(non_lu)}笔\n")
    f.write(f"  HIGH={sum(t['pnl_high'] for t in non_lu)/len(non_lu):+.1f}% avg\n")
    f.write(f"  (H+O)/2={sum(t['pnl_ho'] for t in non_lu)/len(non_lu):+.1f}% avg\n")
    f.write(f"  CLOSE={sum(t['pnl_close'] for t in non_lu)/len(non_lu):+.1f}% avg\n")
    gap_ho=sum(t['pnl_high']-t['pnl_ho'] for t in non_lu)/len(non_lu)
    gap_c=sum(t['pnl_high']-t['pnl_close'] for t in non_lu)/len(non_lu)
    f.write(f"  HIGH-(H+O)/2差距: {gap_ho:.1f}% 每笔\n")
    f.write(f"  HIGH-CLOSE差距: {gap_c:.1f}% 每笔\n\n")

    # Impact on final return
    f.write("对最终资产的累积影响:\n")
    f.write(f"  每笔差{gap_ho:.1f}% x {len(non_lu)}笔 = 约{abs(gap_ho)*len(non_lu):.0f}%累计\n")
    f.write(f"  如果模型卖在(H+O)/2, 交易员卖在HIGH\n")
    f.write(f"  这就是{len(non_lu)}笔不涨停交易的累积差距\n")

    # Detail: biggest gaps
    non_lu.sort(key=lambda x:x['pnl_high']-x['pnl_ho'],reverse=True)
    f.write(f"\n不涨停日中差距最大的10笔:\n")
    f.write(f"{'买入日':<12} {'标的':<10} {'HIGH卖':>8} {'(H+O)/2卖':>10} {'差':>8}\n")
    for t in non_lu[:10]:
        diff=t['pnl_high']-t['pnl_ho']
        f.write(f"{t['buy_date']:<12} {t['name']:<10} {t['pnl_high']:>+7.1f}% {t['pnl_ho']:>+9.1f}% {diff:>+7.1f}%\n")

print(f"Done: {out_path}")
