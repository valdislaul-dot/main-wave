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

sm={
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

def lp(c): return 0.20 if (c.startswith('30') or c.startswith('688')) else 0.10
def lu(c,pc,lp_):
    if pc is None or pc<=0: return False
    return c>=round(pc*(1+lp_),2)-0.005

pdb={}
for name,code in sm.items():
    if name not in stock_data: continue
    pdb[name]={}; lpt=lp(code); kls=stock_data[name]; pc=None
    for i,k in enumerate(kls):
        dt=k['day']; o=float(k['open']); c=float(k['close'])
        h=float(k['high']); l=float(k['low']); v=float(k['volume'])
        e={'open':o,'close':c,'high':h,'low':l,'volume':v,'is_limit_up':False,'prev_close':pc,'change_pct':0,'gap_open_pct':0}
        if pc and pc>0:
            e['is_limit_up']=lu(c,pc,lpt); e['change_pct']=(c-pc)/pc*100; e['gap_open_pct']=(o-pc)/pc*100
        pdb[name][dt]=e; pc=c

tl=[]
for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
ad=sorted(set(d for d,_ in tl))
INIT=300000; TARGET=1000000

def sp_o(d,n): return pdb[n][d]['open'] if n in pdb and d in pdb[n] else None
def sp_c(d,n): return pdb[n][d]['close'] if n in pdb and d in pdb[n] else None
def sp_v(d,n):
    if n in pdb and d in pdb[n]:
        i=pdb[n][d]; return (i['high']+i['low']+i['close'])/3
    return None

out_path=r'C:\Users\Davis\Desktop\主升浪\simple_rule_results.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*80+"\n")
    f.write("简单卖出规则搜索\n")
    f.write("规则: 不涨停 → 卖 | 低开(超过X%) → 也卖\n")
    f.write("="*80+"\n\n")

    results=[]

    # "低开" threshold: what counts as "opening low"?
    # Also test sell price: open vs close vs VWAP
    for gap_threshold in [0, -0.5, -1, -1.5, -2, -2.5, -3, -4, -5]:
        for sp_fn,sp_lbl in [(sp_o,'OPEN'),(sp_v,'VWAP'),(sp_c,'CLOSE')]:
            pos_list=[]; cash=INIT; tlist=[]

            for didx,date in enumerate(ad):
                rec=dict(tl).get(date,'休息')
                pd_=ad[didx-1] if didx>0 else None

                # SELL: check each position
                for pos in pos_list[:]:
                    n=pos['name']; bp_=pos['buy_price']
                    if n not in pdb or date not in pdb[n]:
                        pos_list.remove(pos); continue

                    it=pdb[n][date]
                    ip=pdb[n].get(pd_) if pd_ else None

                    should_sell=False; sp=None

                    # Condition 1: 不涨停 → 卖
                    # (check if prev day was limit-up; if not, sell)
                    prev_lu = False
                    if ip and ip['is_limit_up']:
                        prev_lu = True

                    # Condition 2: 低开 → 卖
                    # (check if today's open is significantly below prev close)
                    opens_low = False
                    if ip:
                        pcv=ip['close']
                        if pcv>0:
                            gap=(it['open']-pcv)/pcv*100
                            if gap <= gap_threshold:
                                opens_low = True

                    # SELL if: 不涨停 OR 低开
                    if not prev_lu or opens_low:
                        should_sell=True
                        sp=sp_fn(date,n)

                    if should_sell and sp and sp>0:
                        pnl=(sp-bp_)/bp_*100
                        tlist.append({'pnl':pnl})
                        cash+=sp*pos['shares']
                        pos_list.remove(pos)

                # BUY
                if rec!='休息' and len(pos_list)==0:
                    bn=rec
                    if bn in pdb and date in pdb[bn]:
                        bp_=pdb[bn][date]['open']
                        sh=int(cash/bp_/100)*100
                        if sh>0: cash-=sh*bp_; pos_list.append({'name':bn,'buy_date':date,'buy_price':bp_,'shares':sh})

                pv=sum(p['shares']*pdb.get(p['name'],{}).get(date,{}).get('close',p['buy_price']) for p in pos_list)

            final=cash+pv; diff=final-TARGET
            ntr=len(tlist)
            wr_=sum(1 for t in tlist if t['pnl']>0)/max(ntr,1)*100
            results.append({'gt':gap_threshold,'sp':sp_lbl,'final':final,'diff':diff,'ntr':ntr,'wr':wr_})

    results.sort(key=lambda x: abs(x['diff']))

    f.write(f"{'低开阈值':>8} {'卖出价':<8} {'最终资产':>12} {'距目标':>10} {'交易':>5} {'胜率':>6}\n")
    f.write("-"*55+"\n")
    for r in results:
        marker=" <--" if abs(r['diff'])<100000 else ""
        f.write(f"{r['gt']:>+7.1f}% {r['sp']:<8} {r['final']:>12,.0f} {r['diff']:>+10,.0f} {r['ntr']:>5} {r['wr']:>5.0f}%{marker}\n")

    # Best match detail
    best=results[0]
    f.write(f"\n\n最佳匹配: 低开阈值={best['gt']:+.1f}% | 卖出价={best['sp']}\n")
    f.write(f"最终={best['final']:,.0f} | 距1M={best['diff']:+,.0f} | 交易={best['ntr']}笔 | 胜率={best['wr']:.0f}%\n")

    # Re-run best with full trade log
    f.write(f"\n\n逐笔明细 (低开阈值={best['gt']:+.1f}%, 卖出价={best['sp']}):\n")
    f.write(f"{'买入日':<12} {'标的':<10} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'盈亏':>8} {'持天':>4} {'原因':>12}\n")
    f.write("-"*80+"\n")

    sp_fn_best=sp_v if best['sp']=='VWAP' else (sp_c if best['sp']=='CLOSE' else sp_o)
    pos_list=[]; cash=INIT; tlist=[]

    for didx,date in enumerate(ad):
        rec=dict(tl).get(date,'休息')
        pd_=ad[didx-1] if didx>0 else None

        for pos in pos_list[:]:
            n=pos['name']; bp_=pos['buy_price']
            if n not in pdb or date not in pdb[n]:
                pos_list.remove(pos); continue
            it=pdb[n][date]; ip=pdb[n].get(pd_) if pd_ else None

            reason=""
            prev_lu=False; opens_low=False
            if ip and ip['is_limit_up']: prev_lu=True
            if ip:
                pcv=ip['close']
                if pcv>0:
                    gap=(it['open']-pcv)/pcv*100
                    if gap<=best['gt']: opens_low=True

            if not prev_lu and opens_low: reason="不涨停+低开"
            elif not prev_lu: reason="不涨停"
            elif opens_low: reason="低开"

            if not prev_lu or opens_low:
                sp=sp_fn_best(date,n)
                if sp and sp>0:
                    pnl=(sp-bp_)/bp_*100
                    hd=(datetime.strptime(date,'%Y-%m-%d')-datetime.strptime(pos['buy_date'],'%Y-%m-%d')).days
                    tlist.append({'name':n,'buy_date':pos['buy_date'],'buy_price':bp_,'sell_date':date,'sell_price':sp,'pnl':pnl,'hd':hd,'reason':reason})
                    cash+=sp*pos['shares']
                    pos_list.remove(pos)

        if rec!='休息' and len(pos_list)==0:
            bn=rec
            if bn in pdb and date in pdb[bn]:
                bp_=pdb[bn][date]['open']
                sh=int(cash/bp_/100)*100
                if sh>0: cash-=sh*bp_; pos_list.append({'name':bn,'buy_date':date,'buy_price':bp_,'shares':sh})

        pv=sum(p['shares']*pdb.get(p['name'],{}).get(date,{}).get('close',p['buy_price']) for p in pos_list)

    for t in tlist:
        f.write(f"{t['buy_date']:<12} {t['name']:<10} {t['buy_price']:>8.2f} "
                f"{t['sell_date']:<12} {t['sell_price']:>8.2f} {t['pnl']:>+7.1f}% {t['hd']:>4} {t['reason']:>12}\n")

    final=cash+pv
    wr_=sum(1 for t in tlist if t['pnl']>0)/max(len(tlist),1)*100
    f.write(f"\n总交易: {len(tlist)}笔 | 胜率: {wr_:.0f}% | 最终: {final:,.0f} | 持仓: {[(p['name'],p['buy_date']) for p in pos_list]}\n")

    # ================================================
    # Apply to MODEL picks
    # ================================================
    f.write(f"\n\n{'='*80}\n")
    f.write(f"应用相同规则到模型选股\n")
    f.write(f"{'='*80}\n")

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

    def get_mp(date):
        cs=[]
        for name in pdb:
            sc=score_v2(name,date)
            if sc>-999:
                kls=stock_data[name]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
                idx=idxs[0]; pd_=kls[idx-1]['day']; t1=pdb[name][pd_]
                cs.append({'name':name,'score':sc,'v20':t1.get('vol_ratio20',1)})
        cs.sort(key=lambda x:x['score'],reverse=True)
        if not cs: return None
        top3=cs[:3]; top3.sort(key=lambda x:x['v20'])
        return top3[0]['name']

    pos_list=[]; cash=INIT; tlist=[]
    for didx,date in enumerate(ad):
        rec=dict(tl).get(date,'休息')
        pd_=ad[didx-1] if didx>0 else None
        for pos in pos_list[:]:
            n=pos['name']; bp_=pos['buy_price']
            if n not in pdb or date not in pdb[n]: pos_list.remove(pos); continue
            it=pdb[n][date]; ip=pdb[n].get(pd_) if pd_ else None
            prev_lu=False; opens_low=False
            if ip and ip['is_limit_up']: prev_lu=True
            if ip:
                pcv=ip['close']
                if pcv>0 and (it['open']-pcv)/pcv*100 <= best['gt']: opens_low=True
            if not prev_lu or opens_low:
                sp=sp_fn_best(date,n)
                if sp and sp>0:
                    pnl=(sp-bp_)/bp_*100; tlist.append({'pnl':pnl})
                    cash+=sp*pos['shares']; pos_list.remove(pos)
        if rec!='休息' and len(pos_list)==0:
            mp=get_mp(date)
            if mp and mp in pdb and date in pdb[mp]:
                bp_=pdb[mp][date]['open']; sh=int(cash/bp_/100)*100
                if sh>0: cash-=sh*bp_; pos_list.append({'name':mp,'buy_date':date,'buy_price':bp_,'shares':sh})
        pv=sum(p['shares']*pdb.get(p['name'],{}).get(date,{}).get('close',p['buy_price']) for p in pos_list)

    mfinal=cash+pv; mret=(mfinal-INIT)/INIT*100
    mwins=sum(1 for t in tlist if t['pnl']>0); mwr=mwins/max(len(tlist),1)*100
    f.write(f"模型选股+同规则: 最终={mfinal:,.0f} | 收益={mret:+.1f}% | 交易={len(tlist)}笔 | 胜率={mwr:.0f}%\n")
    f.write(f"持仓={[(p['name'],p['buy_date']) for p in pos_list]}\n")

    # Final comparison
    f.write(f"\n{'='*80}\n")
    f.write(f"结论\n{'='*80}\n")
    f.write(f"卖出规则: 前日不涨停 → 卖 | 今日低开超{best['gt']:+.1f}% → 也卖\n")
    f.write(f"卖出价格: {best['sp']}\n\n")
    f.write(f"交易员选股+此规则: {final:,.0f} ({(final-INIT)/INIT*100:+.1f}%)\n")
    f.write(f"模型选股+此规则: {mfinal:,.0f} ({mret:+.1f}%)\n")

print(f"Done: {out_path}")
