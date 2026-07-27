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

out_path=r'C:\Users\Davis\Desktop\主升浪\logs\improved_sell.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*70+"\n")
    f.write("改进卖出规则: 不涨停日根据盘中强弱选择卖点\n")
    f.write("="*70+"\n\n")
    f.write(f"{'规则':<45} {'最终资产':>12} {'收益率':>10} {'距1022k':>10}\n")
    f.write("-"*80+"\n")

    for threshold in [6,5,4,3]:
        for rule_name, rule_fn in [
            ("1.统一(H+O)/2", lambda it: (it['high']+it['open'])/2),
            ("2.统一CLOSE", lambda it: it['close']),
            ("3.HIGH>OPEN*1.03->CLOSE否则OPEN",
             lambda it: it['close'] if it['high']>it['open']*1.03 else it['open']),
            ("4.HIGH>OPEN*1.02->CLOSE否则OPEN",
             lambda it: it['close'] if it['high']>it['open']*1.02 else it['open']),
            ("5.HIGH>OPEN*1.05->CLOSE否则OPEN",
             lambda it: it['close'] if it['high']>it['open']*1.05 else it['open']),
        ]:
            INIT=200000; TARGET=1022000
            pos_list=[]; cash=INIT; tlist=[]
            for didx,date in enumerate(ad):
                rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
                for p in pos_list[:]:
                    n=p['n']; bp_=p['bp']
                    if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
                    it=pdb[n][date]
                    if it['gap_open_pct']<threshold:
                        if it['is_limit_up']:
                            sp=it['close']  # LU day: sell at LU price
                        else:
                            sp=rule_fn(it)  # Non-LU day: rule-based
                        if sp>0:
                            pnl=(sp-bp_)/bp_*100; tlist.append({'pnl':pnl})
                            cash+=sp*p['s']; pos_list.remove(p)
                if rec!='休息' and len(pos_list)==0:
                    bn=rec
                    if bn in pdb and date in pdb[bn]:
                        bp_=pdb[bn][date]['open']; deploy=cash*0.55; sh=int(deploy/bp_/100)*100
                        if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})
                pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
            final=cash+pv; ret=(final-INIT)/INIT*100; diff=final-TARGET
            wr=sum(1 for t in tlist if t['pnl']>0)/max(len(tlist),1)*100
            marker=' <--' if abs(diff)<120000 else ''
            f.write(f"{rule_name:<45} {final:>12,.0f} {ret:>+9.1f}% {diff:>+10,.0f}{marker}\n")
        f.write("\n")

print(f"Done: {out_path}")
