import json, os
from collections import defaultdict

with open(r'C:\Users\Davis\Desktop\主升浪\data\stock_data.json','r',encoding='utf-8') as f:
    stock_data=json.load(f)

# Count LU streaks: for each stock, find consecutive LU sequences
transitions = defaultdict(lambda: {'next_lu':0, 'total':0})

for name, klines in stock_data.items():
    prev_close = None
    cons_before = 0  # how many consecutive LU before current day
    for i, k in enumerate(klines):
        o = float(k['open']); c = float(k['close'])
        # Determine if LU (simplified: close >= prev_close * 1.10 for 10% board)
        is_lu = False
        if prev_close and prev_close > 0:
            limit_up_price = round(prev_close * 1.10, 2)
            if c >= limit_up_price - 0.005:
                is_lu = True

        if is_lu:
            transitions[cons_before]['total'] += 1
            # Check if next day also LU
            if i + 1 < len(klines):
                next_c = float(klines[i+1]['close'])
                next_pc = c
                next_lu_price = round(next_pc * 1.10, 2)
                if next_c >= next_lu_price - 0.005:
                    transitions[cons_before]['next_lu'] += 1
            cons_before += 1
        else:
            cons_before = 0

        prev_close = c

out_path = r'C:\Users\Davis\Desktop\主升浪\logs\lianban_prob.txt'
with open(out_path,'w',encoding='utf-8') as f:
    f.write("="*65+"\n")
    f.write("连板延续概率分析 (72只标的, 2025-09至2026-07)\n")
    f.write("="*65+"\n\n")
    f.write(f"{'当前位置':<12} {'总样本':>8} {'延续到下一板':>12} {'概率':>10}\n")
    f.write("-"*48+"\n")

    for cons in sorted(transitions.keys()):
        t = transitions[cons]
        if t['total'] > 0:
            prob = t['next_lu'] / t['total'] * 100
            label = f'{cons+1}板->{cons+2}板' if cons > 0 else '首板->2板'
            f.write(f"{label:<12} {t['total']:>8} {t['next_lu']:>12} {prob:>9.1f}%\n")

    f.write("\n结论:\n")
    f.write("不存在'4板后肯定5板'这回事。\n")
    f.write("连板数越高, 下一板延续概率越低——资金接力意愿递减。\n")
    f.write("模型对第4板+只给+7分(低于2-3板的+10~12)正是基于这一事实。\n")

    # Part 2: Trader A's actual performance by board count
    import openpyxl
    wb=openpyxl.load_workbook(r'C:\Users\Davis\Desktop\主升浪\data\副本主升浪.xlsx')
    ws=wb['Sheet1']
    records=[]
    for row in ws.iter_rows(min_row=2,values_only=True):
        for i in range(0,10,2):
            dv=row[i]; sv=row[i+1] if i+1<len(row) else None
            if dv is not None and dv!='' and sv is not None and sv!='':
                records.append((int(dv),sv.strip()))
    records.sort(key=lambda x:x[0])

    from datetime import datetime, timedelta
    def ed(s): return datetime(1899,12,30)+timedelta(days=int(s))

    sm={}
    for n,c in [('赤天化','600227'),('亚盛集团','600108'),('国星光电','002449'),('顺钠股份','000533'),('美利云','000815'),('宇环数控','002903'),('金浦钛业','000545'),('郑州煤电','600121'),('金正大','002470'),('京投发展','600683'),('正泰电源','002150'),('基蛋生物','603387'),('华电辽能','600396'),('新日股份','603787'),('舒华体育','605299'),('新能泰山','000720'),('美诺华','603538'),('津药药业','600488'),('安徽建工','600502'),('力诺药包','301188'),('星辉环材','300834'),('中工国际','002051'),('康盛股份','002418'),('新朋股份','002328'),('圣阳股份','002580'),('康恩贝','600572'),('昂利康','002940'),('蜀道装备','300540'),('圣龙股份','603178'),('九鼎新材','002201'),('东望时代','600052'),('水发燃气','603318'),('飞南资源','301500'),('宝光股份','600379'),('金螳螂','002081'),('波导股份','600130'),('深圳华强','000062'),('大唐发电','601991'),('蒙娜丽莎','002918'),('滨化股份','601678'),('合肥城建','002208'),('华能蒙电','600863'),('达实智能','002421'),('合百集团','000417'),('安德利','605198'),('肯特股份','301591'),('香江控股','600162'),('泓淋电力','301439'),('方大集团','000055'),('广西能源','600310'),('天洋新材','603330'),('龙源技术','300105'),('金安国纪','002636'),('天地源','600665'),('翔鹭钨业','002842'),('金钼股份','601958'),('盛龙股份','001257'),('立航科技','603261'),('黄河旋风','600172'),('世名科技','300522'),('长裕集团','603407'),('宏柏新材','605366'),('兴业科技','002674'),('安洁科技','002635'),('雷赛智能','002979'),('先锋新材','300163'),('恒尚节能','603137'),('同兴达','002845'),('立方制药','003020'),('哈药股份','600664'),('立新能源','001258'),('长缆科技','002879')]:
        sm[n]=c

    def lp(c): return 0.20 if (c.startswith('30') or c.startswith('688')) else 0.10
    def lu(c,pc,lp_):
        if pc is None or pc<=0: return False
        return c>=round(pc*(1+lp_),2)-0.005

    pdb2={}
    for name,code in sm.items():
        if name not in stock_data: continue
        pdb2[name]={}; lpt=lp(code); klines=stock_data[name]; pc=None
        for i,k in enumerate(klines):
            dt=k['day']; o=float(k['open']); c=float(k['close']); h=float(k['high']); l=float(k['low'])
            e={'open':o,'close':c,'high':h,'low':l,'is_limit_up':False,'prev_close':pc,'gap_open_pct':0}
            if pc and pc>0: e['is_limit_up']=lu(c,pc,lpt); e['gap_open_pct']=(o-pc)/pc*100
            pdb2[name][dt]=e; pc=c

    tl=[]
    for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
    ad=sorted(set(d for d,_ in tl))

    by_board={1:[],2:[],3:[],4:[],5:[]}
    pos_list=[]
    for didx,date in enumerate(ad):
        rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
        for p in pos_list[:]:
            n=p['n']; bp_=p['bp']
            if n not in pdb2 or date not in pdb2[n]: pos_list.remove(p); continue
            it=pdb2[n][date]
            if it['gap_open_pct']<3:
                sp=it['close'] if it['is_limit_up'] else (it['high']+it['open'])/2
                if sp>0:
                    pnl=(sp-bp_)/bp_*100
                    b=p.get('board_at_buy',1)
                    if b in by_board: by_board[b].append(pnl)
                    pos_list.remove(p)
        if rec!='休息' and len(pos_list)==0:
            bn=rec
            if bn in pdb2 and date in pdb2[bn]:
                it=pdb2[bn][date]
                kls=stock_data[bn]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
                if idxs and idxs[0]>=1:
                    t1d=kls[idxs[0]-1]['day']
                    if t1d in pdb2[bn]:
                        cons=0; j=idxs[0]-1
                        while j>=0:
                            cd_=kls[j]['day']
                            if cd_ in pdb2[bn] and pdb2[bn][cd_]['is_limit_up']: cons+=1; j-=1
                            else: break
                        board_num=cons+1
                        gap=(it['open']-pdb2[bn][t1d]['close'])/pdb2[bn][t1d]['close']*100
                        if 4<=gap<=8:
                            pos_list.append({'n':bn,'b':date,'bp':it['open'],'s':0,'board_at_buy':board_num})

    f.write("\n\n=== 交易员A: 买入时连板数 vs 盈亏 (4-8%区间) ===\n\n")
    f.write(f"{'连板数':<8} {'笔数':>5} {'平均盈亏':>10} {'胜率':>8}\n")
    f.write("-"*35+"\n")
    for b in [1,2,3,4,5]:
        trades=by_board[b]
        if trades:
            avg=sum(trades)/len(trades)
            wr=sum(1 for t in trades if t>0)/len(trades)*100
            f.write(f'{b}连板     {len(trades):>5} {avg:>+9.1f}% {wr:>7.0f}%\n')
        else:
            f.write(f'{b}连板     {len(trades):>5}       N/A\n')

    f.write("\n结论: 2-3连板买入平均盈亏和胜率最高。\n")
    f.write("4连板后买入胜率和盈亏比均下降, 与全市场概率数据一致。\n")

    # Part 3: How often does trader sell on LU day, missing further gains?
    sell_lu_next_lu = []
    sell_lu_next_not = []
    pos_list2 = []
    for didx, date in enumerate(ad):
        rec = dict(tl).get(date, '休息')
        pd_ = ad[didx-1] if didx > 0 else None
        for p in pos_list2[:]:
            n = p['n']; bp_ = p['bp']
            if n not in pdb2 or date not in pdb2[n]:
                pos_list2.remove(p)
                continue
            it = pdb2[n][date]
            if it['gap_open_pct'] < 3:
                if it['is_limit_up']:
                    kls2 = stock_data[n]
                    idxs2 = [i for i, k in enumerate(kls2) if k['day'] == date]
                    if idxs2 and idxs2[0]+1 < len(kls2):
                        nd = kls2[idxs2[0]+1]['day']
                        next_lu = pdb2[n][nd]['is_limit_up'] if nd in pdb2[n] else False
                        entry = {'name': n, 'buy': p['b'], 'sell': date,
                                 'buy_price': bp_, 'sell_price': it['close'],
                                 'pnl': (it['close']-bp_)/bp_*100}
                        if next_lu:
                            sell_lu_next_lu.append(entry)
                        else:
                            sell_lu_next_not.append(entry)
                pos_list2.remove(p)
        if rec != '休息' and len(pos_list2) == 0:
            bn = rec
            if bn in pdb2 and date in pdb2[bn]:
                bp_ = pdb2[bn][date]['open']
                pos_list2.append({'n': bn, 'b': date, 'bp': bp_, 's': 0})

    f.write("\n\n=== 涨停日卖出分析 ===\n\n")
    f.write(f"涨停日卖出, 次日继续涨停(卖早了): {len(sell_lu_next_lu)}笔\n")
    for t in sell_lu_next_lu:
        f.write(f"  {t['buy']} -> {t['sell']} {t['name']}: {t['pnl']:+.1f}%\n")

    f.write(f"\n涨停日卖出, 次日断板(卖对了): {len(sell_lu_next_not)}笔\n")
    for t in sell_lu_next_not[:8]:
        f.write(f"  {t['buy']} -> {t['sell']} {t['name']}: {t['pnl']:+.1f}%\n")

    total_lu_sells = len(sell_lu_next_lu) + len(sell_lu_next_not)
    f.write(f"\n涨停日卖出总计: {total_lu_sells}笔\n")
    f.write(f"  卖早了(次日继续板): {len(sell_lu_next_lu)}笔\n")
    f.write(f"  卖对了(次日断板): {len(sell_lu_next_not)}笔\n")
    if total_lu_sells > 0:
        f.write(f"  卖对率: {len(sell_lu_next_not)/total_lu_sells*100:.0f}%\n")

    # Part 4: Test "eat one board then exit" rule
    f.write("\n\n=== 吃一板止盈规则测试 ===\n\n")
    f.write(f"{'规则':<40} {'最终':>10} {'收益':>8}\n")
    f.write("-"*60+"\n")

    INIT=200000
    # Baseline
    pos_list=[]; cash=INIT
    for didx,date in enumerate(ad):
        rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
        for p in pos_list[:]:
            n=p['n']; bp_=p['bp']
            if n not in pdb2 or date not in pdb2[n]: pos_list.remove(p); continue
            it=pdb2[n][date]
            if it['gap_open_pct']<3:
                sp=it['close'] if it['is_limit_up'] else (it['high']+it['open'])/2
                if sp>0: cash+=sp*p['s']; pos_list.remove(p)
        if rec!='休息' and len(pos_list)==0:
            bn=rec
            if bn in pdb2 and date in pdb2[bn]:
                it=pdb2[bn][date]
                kls2=stock_data[bn]; idxs2=[i for i,k in enumerate(kls2) if k['day']==date]
                if idxs2 and idxs2[0]>=1:
                    t1d=kls2[idxs2[0]-1]['day']
                    if t1d in pdb2[bn]:
                        gap=(it['open']-pdb2[bn][t1d]['close'])/pdb2[bn][t1d]['close']*100
                        if 4<=gap<=8:
                            cons=0; j=idxs2[0]-1
                            while j>=0:
                                cd_=kls2[j]['day']
                                if cd_ in pdb2[bn] and pdb2[bn][cd_]['is_limit_up']: cons+=1; j-=1
                                else: break
                            bp_=it['open']; sh=int(cash/bp_/100)*100
                            if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh,'board':cons+1})
        pv=sum(p['s']*pdb2.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
    final=cash+pv; ret=(final-INIT)/INIT*100
    f.write(f"{'基线(无主动止盈)':<40} {final:>10,.0f} {ret:>+7.1f}%\n")

    # With take-profit
    pos_list=[]; cash=INIT; tp_count=0
    for didx,date in enumerate(ad):
        rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
        for p in pos_list[:]:
            n=p['n']; bp_=p['bp']; buy_board=p.get('board',0)
            if n not in pdb2 or date not in pdb2[n]: pos_list.remove(p); continue
            it=pdb2[n][date]
            kls2=stock_data[n]; idxs2=[i for i,k in enumerate(kls2) if k['day']==date]
            cur_board=0
            if idxs2:
                j=idxs2[0]
                while j>=0:
                    cd_=kls2[j]['day']
                    if cd_ in pdb2[n] and pdb2[n][cd_]['is_limit_up']: cur_board+=1; j-=1
                    else: break
            take_profit = it['is_limit_up'] and cur_board > buy_board
            sell_weak = it['gap_open_pct']<3
            if take_profit or sell_weak:
                if take_profit: tp_count+=1
                sp=it['close'] if it['is_limit_up'] else (it['high']+it['open'])/2
                if sp>0: cash+=sp*p['s']; pos_list.remove(p)
        if rec!='休息' and len(pos_list)==0:
            bn=rec
            if bn in pdb2 and date in pdb2[bn]:
                it=pdb2[bn][date]
                kls2=stock_data[bn]; idxs2=[i for i,k in enumerate(kls2) if k['day']==date]
                if idxs2 and idxs2[0]>=1:
                    t1d=kls2[idxs2[0]-1]['day']
                    if t1d in pdb2[bn]:
                        gap=(it['open']-pdb2[bn][t1d]['close'])/pdb2[bn][t1d]['close']*100
                        if 4<=gap<=8:
                            cons=0; j=idxs2[0]-1
                            while j>=0:
                                cd_=kls2[j]['day']
                                if cd_ in pdb2[bn] and pdb2[bn][cd_]['is_limit_up']: cons+=1; j-=1
                                else: break
                            bp_=it['open']; sh=int(cash/bp_/100)*100
                            if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh,'board':cons+1})
        pv=sum(p['s']*pdb2.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
    final=cash+pv; ret=(final-INIT)/INIT*100
    f.write(f"{'基线+吃一板止盈':<40} {final:>10,.0f} {ret:>+7.1f}% (主动止盈{tp_count}笔)\n")

    # Part 5: Monthly performance
    f.write("\n\n=== 月度表现 ===\n\n")
    f.write(f"{'月份':<8} {'交易笔数':>6} {'月收益':>10} {'月末资产':>12} {'累计':>10}\n")
    f.write("-"*50+"\n")

    INIT2 = 200000
    pos_list3 = []; cash = INIT2; monthly = {}
    for didx, date in enumerate(ad):
        rec = dict(tl).get(date, '休息'); pd_ = ad[didx-1] if didx > 0 else None
        month = date[:7]
        if month not in monthly: monthly[month] = []
        for p in pos_list3[:]:
            n = p['n']; bp_ = p['bp']
            if n not in pdb2 or date not in pdb2[n]: pos_list3.remove(p); continue
            it = pdb2[n][date]
            if it['gap_open_pct'] < 3:
                sp = it['close'] if it['is_limit_up'] else (it['high']+it['open'])/2
                if sp > 0:
                    pnl = (sp-bp_)/bp_*100
                    monthly[month].append(pnl)
                    cash += sp * p['s']; pos_list3.remove(p)
        if rec != '休息' and len(pos_list3) == 0:
            bn = rec
            if bn in pdb2 and date in pdb2[bn]:
                bp_ = pdb2[bn][date]['open']
                kls2 = stock_data[bn]; idxs2 = [i for i,k in enumerate(kls2) if k['day']==date]
                if idxs2 and idxs2[0]>=1:
                    t1d = kls2[idxs2[0]-1]['day']
                    if t1d in pdb2[bn]:
                        gap = (bp_ - pdb2[bn][t1d]['close'])/pdb2[bn][t1d]['close']*100
                        if True:  # no buy filter, count all
                            sh = int(cash/bp_/100)*100
                            if sh > 0: cash -= sh*bp_; pos_list3.append({'n':bn,'b':date,'bp':bp_,'s':sh})
        pv = sum(p['s']*pdb2.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list3)
        monthly[month].append(('mark', cash+pv))

    running = INIT2
    for m in sorted(monthly.keys()):
        trades = [t for t in monthly[m] if isinstance(t, (int, float))]
        marks = [t for t in monthly[m] if isinstance(t, tuple)]
        last = marks[-1][1] if marks else running
        month_ret = (last-running)/running*100
        cum_ret = (last-INIT2)/INIT2*100
        f.write(f"{m:<8} {len(trades):>6} {month_ret:>+9.1f}% {last:>12,.0f} {cum_ret:>+9.1f}%\n")
        running = last

    # Part 6: Monthly PnL by sell threshold
    f.write("\n\n=== A的月度收益 (全量买入, 不同卖出阈值) ===\n\n")

    for sell_threshold in [3, 4, 5, 6, 8, 10]:
        f.write(f"\n--- 阈值: 开盘<{sell_threshold}%就卖 ---\n")
        f.write(f"{'月份':<6} {'交易':>4} {'月收益':>10} {'月末资产':>12}\n")
        f.write("-"*40+"\n")

        INIT3 = 200000
        pos_list4 = []; cash = INIT3; monthly_sells = {}; monthly_asset = {}
        for didx, date in enumerate(ad):
            rec = dict(tl).get(date, '休息'); pd_ = ad[didx-1] if didx > 0 else None
            m = date[:7]
            if m not in monthly_sells: monthly_sells[m] = []
            for p in pos_list4[:]:
                n = p['n']; bp_ = p['bp']
                if n not in pdb2 or date not in pdb2[n]: pos_list4.remove(p); continue
                it = pdb2[n][date]
                if it['gap_open_pct'] < sell_threshold:
                    sp = it['close'] if it['is_limit_up'] else (it['high']+it['open'])/2
                    if sp > 0:
                        monthly_sells[m].append((sp-bp_)/bp_*100)
                        cash += sp * p['s']; pos_list4.remove(p)
            if rec != '休息' and len(pos_list4) == 0:
                bn = rec
                if bn in pdb2 and date in pdb2[bn]:
                    it = pdb2[bn][date]
                    kls2 = stock_data[bn]; idxs2 = [i for i,k in enumerate(kls2) if k['day']==date]
                    if idxs2 and idxs2[0]>=1:
                        t1d = kls2[idxs2[0]-1]['day']
                        if t1d in pdb2[bn]:
                            bp_ = it['open']; sh = int(cash/bp_/100)*100
                            if sh > 0: cash -= sh*bp_; pos_list4.append({'n':bn,'b':date,'bp':bp_,'s':sh})
            pv = sum(p['s']*pdb2.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list4)
            monthly_asset[date] = cash + pv

        prev_asset = INIT3
        for m in sorted(set(d[:7] for d in ad)):
            sells = monthly_sells.get(m, [])
            month_end_dates = [d for d in ad if d[:7]==m]
            last = monthly_asset.get(month_end_dates[-1], prev_asset) if month_end_dates else prev_asset
            month_ret = (last-prev_asset)/prev_asset*100
            f.write(f"{m:<6} {len(sells):>4} {month_ret:>+9.1f}% {last:>12,.0f}\n")
            prev_asset = last

        pv_final = sum(p['s']*pdb2.get(p['n'],{}).get(ad[-1],{}).get('close',p['bp']) for p in pos_list4) if pos_list4 else 0
        f.write(f"最终: {cash+pv_final:,.0f}\n")

print(f"Done: {out_path}")
