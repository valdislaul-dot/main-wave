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
    pdb[name]={}; lpt=lp(code); kls=stock_data[name]; pc=None
    for i,k in enumerate(kls):
        dt=k['day']; o=float(k['open']); c=float(k['close']); h=float(k['high']); l=float(k['low'])
        e={'open':o,'close':c,'high':h,'low':l,'is_limit_up':False,'prev_close':pc}
        if pc and pc>0:
            e['is_limit_up']=lu(c,pc,lpt)
            today_lu_price=round(pc*(1+lpt),2)
            e['opens_at_lu']=(o>=today_lu_price-0.005)
            e['gap_open_pct']=(o-pc)/pc*100
        else: e['opens_at_lu']=False; e['gap_open_pct']=0
        pdb[name][dt]=e; pc=c

tl=[]
for s,st in records: d=ed(s); tl.append((d.strftime('%Y-%m-%d'),st))
ad=sorted(set(d for d,_ in tl))
INIT=300000

print('='*60)
print('核心矛盾分析')
print('='*60)
print()
print('已确认:')
print('  买入: 开盘价, 5分钟内完成')
print('  卖出: 开盘价, 5分钟内完成')
print('  卖出条件: 不涨停(昨) 或 低开(今)')
print('  初始资金: 300,000 (假设)')
print('  实际结果: ~1,000,000 (你确认)')
print()
print('模拟结果: 交易员选股+确认规则 = ~166,000 (-45%)')
print('差距: 834,000')
print()
print('这个差距太大, 无法用参数微调解释。')
print('可能的原因:')
print('  1. 初始资金不是30万')
print('  2. 实际买入/卖出价与K线数据有系统性偏差')
print('  3. 有其他未提及的规则')
print()
print('能否确认初始资金金额? 或者指出买卖价格方面的差异?')
