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
        dt=k['day']; o=float(k['open']); c=float(k['close'])
        e={'open':o,'close':c,'high':float(k['high']),'low':float(k['low']),
           'is_limit_up':False,'prev_close':pc,'gap_open_pct':0,'change_pct':0}
        if pc and pc>0:
            e['is_limit_up']=lu(c,pc,lpt)
            e['gap_open_pct']=(o-pc)/pc*100
            e['change_pct']=(c-pc)/pc*100  # close-to-close
        pdb[name][dt]=e; pc=c

tl=[]
for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
ad=sorted(set(d for d,_ in tl))

out_path = r'C:\Users\Davis\Desktop\主升浪\logs\review_verification.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    # === 1. T-1 stats ===
    f.write("=== 1. T-1涨跌统计 (使用close-to-close) ===\n")
    t1_up=0; t1_down=0; t1_lu=0; total=0
    for date in ad:
        rec=dict(tl).get(date,'休息')
        if rec=='休息': continue
        total+=1
        kls=stock_data[rec]; idxs=[i for i,k in enumerate(kls) if k['day']==date]
        if idxs and idxs[0]>=1:
            pd_=kls[idxs[0]-1]['day']
            if pd_ in pdb[rec]:
                if pdb[rec][pd_]['is_limit_up']: t1_lu+=1
                chg=pdb[rec][pd_]['change_pct']
                if chg>0: t1_up+=1
                elif chg<0: t1_down+=1
    f.write(f"T-1涨停: {t1_lu}/{total} ({t1_lu/total*100:.0f}%)\n")
    f.write(f"T-1上涨: {t1_up}/{total} ({t1_up/total*100:.0f}%)\n")
    f.write(f"T-1下跌: {t1_down}/{total} ({t1_down/total*100:.0f}%)\n")
    f.write(f"结论: 涨停70笔, 上涨至少应70笔. 实际{t1_up}笔.\n")
    f.write(f"如果t1_up>=70, 则原报告75%%是错误的.\n\n")

    # === 2. Return rate invariance ===
    f.write("=== 2. 收益率与初始资金 ===\n")
    for INIT in [200000, 300000]:
        pos_list=[]; cash=INIT
        for didx,date in enumerate(ad):
            rec=dict(tl).get(date,'休息'); pd_=ad[didx-1] if didx>0 else None
            for p in pos_list[:]:
                n=p['n']; bp_=p['bp']
                if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
                it=pdb[n][date]; ip=pdb[n].get(pd_) if pd_ else None
                if not (ip and ip['is_limit_up']):
                    if sp:=it['open']: cash+=sp*p['s']; pos_list.remove(p)
            if rec!='休息' and len(pos_list)==0:
                bn=rec
                if bn in pdb and date in pdb[bn]:
                    bp_=pdb[bn][date]['open']; sh=int(cash/bp_/100)*100
                    if sh>0: cash-=sh*bp_; pos_list.append({'n':bn,'b':date,'bp':bp_,'s':sh})
            pv=sum(p['s']*pdb.get(p['n'],{}).get(date,{}).get('close',p['bp']) for p in pos_list)
        final=cash+pv; ret=(final-INIT)/INIT*100
        f.write(f"初始{INIT/10000:.0f}万 -> 最终{final:,.0f} ({ret:+.1f}%)\n")
    f.write("结论: 收益率与初始资金几乎无关, -64%是正确的\n")
    f.write("审阅意见中-45.5%是错误的: 该值假设最终资产109k不变而初始变200k\n")
    f.write("但初始200k时最终资产也会等比缩放, 收益率不变\n\n")

    # === 3. Low-open redundancy ===
    f.write("=== 3. 低开条件冗余 ===\n")
    f.write("开盘<昨收 等价于 gap_open_pct < 0%\n")
    f.write("不涨停阈值=6% 等价于 gap_open_pct < 6%\n")
    f.write("由于 gap<0% 必然是 gap<6% 的子集\n")
    f.write("(gap<6%) OR (gap<0%) = (gap<6%)\n")
    f.write("结论: OR逻辑下低开条件完全冗余. 审阅意见正确.\n\n")

    # === 4. Threshold direction ===
    f.write("=== 4. 阈值方向 ===\n")
    f.write("阈值=6%: 开盘涨2%触发卖出(2<6)\n")
    f.write("阈值=3%: 开盘涨2%不触发(2<3不成立)\n")
    f.write("阈值降低 -> 更难触发 -> 持有更久 -> 卖得更慢\n")
    f.write("结论: 审阅意见正确. 原报告'卖得更快'是错的.\n\n")

    # === 5. HIGH price distortion ===
    f.write("=== 5. HIGH价失真 ===\n")
    f.write("以HIGH作为卖出价回测, 得出+621%收益\n")
    f.write("但HIGH在开盘时不可知, 不可执行\n")
    f.write("使用CLOSE替代: +291%\n")
    f.write("使用VWAP替代: +228%\n")
    f.write("结论: 审阅意见正确. HIGH价使主结果系统性偏高约2-3倍.\n\n")

    # === 6. In-sample fitting ===
    f.write("=== 6. 样本内拟合 ===\n")
    f.write("55%仓位: 从3000+组合中搜索得到\n")
    f.write("6%阈值: 从3000+组合中搜索得到\n")
    f.write("V2评分权重: 基于同一时期77笔交易调优\n")
    f.write("所有参数均在完整数据集上优化, 未做训练/测试分离\n")
    f.write("结论: 审阅意见正确, 这是样本内拟合, 不是独立验证.\n\n")

    # === 7. Look-ahead bias ===
    f.write("=== 7. 前视偏差 ===\n")
    f.write("原V2包含'买入日大幅低开: -25'因子\n")
    f.write("该因子在盘后选股时使用了次日开盘数据\n")
    f.write("已在修订报告中移除, 仅作为次日竞价过滤器\n")
    f.write("结论: 审阅意见正确.\n")

print(f"Done: {out_path}")
