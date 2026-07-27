import json, openpyxl
from datetime import datetime, timedelta

with open(r'C:\Users\Davis\Desktop\主升浪\data\stock_data.json', 'r', encoding='utf-8') as f:
    stock_data = json.load(f)
def ed(s): return datetime(1899,12,30)+timedelta(days=int(s))
wb = openpyxl.load_workbook(r'C:\Users\Davis\Desktop\主升浪\data\副本主升浪.xlsx')
ws = wb['Sheet1']
records = []
for row in ws.iter_rows(min_row=2, values_only=True):
    for i in range(0, 10, 2):
        dv = row[i]; sv = row[i+1] if i+1 < len(row) else None
        if dv is not None and dv != '' and sv is not None and sv != '':
            records.append((int(dv), sv.strip()))
records.sort(key=lambda x: x[0])

sm = {}
for n, c in [
    ('赤天化','600227'),('亚盛集团','600108'),('国星光电','002449'),('顺钠股份','000533'),
    ('美利云','000815'),('宇环数控','002903'),('金浦钛业','000545'),('郑州煤电','600121'),
    ('金正大','002470'),('京投发展','600683'),('正泰电源','002150'),('基蛋生物','603387'),
    ('华电辽能','600396'),('新日股份','603787'),('舒华体育','605299'),('新能泰山','000720'),
    ('美诺华','603538'),('津药药业','600488'),('安徽建工','600502'),('力诺药包','301188'),
    ('星辉环材','300834'),('中工国际','002051'),('康盛股份','002418'),('新朋股份','002328'),
    ('圣阳股份','002580'),('康恩贝','600572'),('昂利康','002940'),('蜀道装备','300540'),
    ('圣龙股份','603178'),('九鼎新材','002201'),('东望时代','600052'),('水发燃气','603318'),
    ('飞南资源','301500'),('宝光股份','600379'),('金螳螂','002081'),('波导股份','600130'),
    ('深圳华强','000062'),('大唐发电','601991'),('蒙娜丽莎','002918'),('滨化股份','601678'),
    ('合肥城建','002208'),('华能蒙电','600863'),('达实智能','002421'),('合百集团','000417'),
    ('安德利','605198'),('肯特股份','301591'),('香江控股','600162'),('泓淋电力','301439'),
    ('方大集团','000055'),('广西能源','600310'),('天洋新材','603330'),('龙源技术','300105'),
    ('金安国纪','002636'),('天地源','600665'),('翔鹭钨业','002842'),('金钼股份','601958'),
    ('盛龙股份','001257'),('立航科技','603261'),('黄河旋风','600172'),('世名科技','300522'),
    ('长裕集团','603407'),('宏柏新材','605366'),('兴业科技','002674'),('安洁科技','002635'),
    ('雷赛智能','002979'),('先锋新材','300163'),('恒尚节能','603137'),('同兴达','002845'),
    ('立方制药','003020'),('哈药股份','600664'),('立新能源','001258'),('长缆科技','002879'),
]:
    sm[n] = c

def lp(c): return 0.20 if (c.startswith('30') or c.startswith('688')) else 0.10
def lu(c, pc, lp_):
    if pc is None or pc <= 0: return False
    return c >= round(pc * (1 + lp_), 2) - 0.005

pdb = {}
for name, code in sm.items():
    if name not in stock_data: continue
    pdb[name] = {}
    lpt = lp(code); klines = stock_data[name]; pc = None
    for i, k in enumerate(klines):
        dt = k['day']; o = float(k['open']); c = float(k['close'])
        h = float(k['high']); l_ = float(k['low']); v = float(k['volume'])
        e = {'open': o, 'close': c, 'high': h, 'low': l_, 'volume': v,
             'is_limit_up': False, 'prev_close': pc, 'gap_open_pct': 0}
        if pc and pc > 0:
            e['is_limit_up'] = lu(c, pc, lpt)
            e['gap_open_pct'] = (o - pc) / pc * 100
        pdb[name][dt] = e
        pc = c

tl = []
for s, st in records:
    d = ed(s)
    tl.append((d.strftime('%Y-%m-%d'), st))
ad = sorted(set(d for d, _ in tl))

out_path = r'C:\Users\Davis\Desktop\主升浪\logs\improvement_analysis.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("=" * 60 + "\n")
    f.write("策略改进分析\n")
    f.write("=" * 60 + "\n\n")

    # 1. Analyze HIGH vs OPEN on non-LU sell days
    f.write("1. 不涨停日的卖出价改进空间\n")
    f.write("-" * 40 + "\n")
    # Simulate trader picks, track actual sell prices (HIGH) vs OPEN
    pos_list = []; cash = 200000
    sell_records = []
    for didx, date in enumerate(ad):
        rec = dict(tl).get(date, '休息')
        pd_ = ad[didx - 1] if didx > 0 else None
        for p in pos_list[:]:
            n = p['n']; bp_ = p['bp']
            if n not in pdb or date not in pdb[n]: pos_list.remove(p); continue
            it = pdb[n][date]
            if it['gap_open_pct'] < 6:
                sell_records.append({
                    'name': n, 'date': date, 'buy_price': bp_,
                    'open': it['open'], 'high': it['high'], 'close': it['close'],
                    'is_lu': it['is_limit_up'],
                    'h_vs_o': (it['high'] - it['open']) / it['open'] * 100,
                    'c_vs_o': (it['close'] - it['open']) / it['open'] * 100,
                })
                sp = it['high']
                cash += sp * p['s']; pos_list.remove(p)
        if rec != '休息' and len(pos_list) == 0:
            bn = rec
            if bn in pdb and date in pdb[bn]:
                bp_ = pdb[bn][date]['open']
                deploy = cash * 0.55; sh = int(deploy / bp_ / 100) * 100
                if sh > 0: cash -= sh * bp_; pos_list.append({'n': bn, 'b': date, 'bp': bp_, 's': sh})

    lu_sells = [s for s in sell_records if s['is_lu']]
    non_lu_sells = [s for s in sell_records if not s['is_lu']]

    if non_lu_sells:
        avg_h = sum(s['h_vs_o'] for s in non_lu_sells) / len(non_lu_sells)
        avg_c = sum(s['c_vs_o'] for s in non_lu_sells) / len(non_lu_sells)
        f.write(f"不涨停卖出: {len(non_lu_sells)}笔\n")
        f.write(f"  HIGH比OPEN高: {avg_h:+.1f}%\n")
        f.write(f"  CLOSE比OPEN高: {avg_c:+.1f}%\n")
        f.write(f"  可捕获空间: 如果卖在(H+O)/2, 比卖在OPEN多{avg_h/2:.1f}%\n")

    if lu_sells:
        f.write(f"涨停日卖出: {len(lu_sells)}笔 (全部捕获HIGH)\n")

    f.write("\n改进建议: 不涨停日按(H+O)/2卖出, 比纯开盘价卖更接近实际\n\n")

    # 2. Top-3 hit rate analysis
    f.write("2. 选股覆盖率改进\n")
    f.write("-" * 40 + "\n")
    f.write("当前Top3命中率66%, 还有34%的交易员选股不在前3\n")
    f.write("改进方向:\n")
    f.write("  - 引入行业/板块因子: 同板块多股涨停说明板块效应\n")
    f.write("  - 封板时间权重: 早盘封板(9:30-10:00)更强\n")
    f.write("  - 炸板历史: 之前炸板过的股票扣分\n")
    f.write("  - 市值因子: 小盘股更容易连板\n\n")

    # 3. Market condition filter
    f.write("3. 市场环境过滤\n")
    f.write("-" * 40 + "\n")
    # Count LU stocks per day as market strength proxy
    lu_counts = []
    for date in ad:
        cnt = 0
        for name in pdb:
            if date in pdb[name] and pdb[name][date]['is_limit_up']:
                cnt += 1
        lu_counts.append(cnt)

    avg_lu = sum(lu_counts) / len(lu_counts)
    f.write(f"每日平均涨停股数(72只池): {avg_lu:.1f}\n")
    f.write("涨停数少时市场弱, 应降低仓位或暂停交易\n\n")

    # 4. Forward test is the real improvement
    f.write("4. 最重要的改进: 实盘验证\n")
    f.write("-" * 40 + "\n")
    f.write("所有参数均来自77笔历史数据拟合\n")
    f.write("真正的改进只能来自样本外数据\n")
    f.write("模型模拟盘 vs 交易员A实盘 = 最好的验证\n")
    f.write("每积累一个月新数据, 重新评估模型表现\n")

print(f"Done: {out_path}")
