# -*- coding: utf-8 -*-
"""主升浪 V3 模拟 vs 实际交易记录 对照表 → 桌面 Excel
左：V3评分在 08-26~09-11 的模拟结果（每日Top1）
右：同期真实交易记录（= V4 时期实盘）
"""
import json, os, sys, io, warnings
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DESK = os.path.join(os.path.expanduser('~'), 'Desktop')
START, END = '2026-08-26', '2026-09-11'
_SIM = os.path.join(DESK, '模拟交易_对照_20260826-20260911_V3现行.xlsx')
if not os.path.exists(_SIM):
    raise SystemExit('缺少模拟输出 %s —— 请先运行: python scripts/v5_simulation.py --tag V3现行' % _SIM)
sim = pd.read_excel(_SIM, sheet_name=0)
sim.columns = [str(c).replace('V5评分', 'V3评分') for c in sim.columns]
sim['代码'] = sim['代码'].apply(lambda x: '' if pd.isna(x) else str(int(float(x))).zfill(6))

# ---- 真实交易记录: FIFO 配对 BUY→SELL ----
j = json.load(open('logs/trading_journal.json', encoding='utf-8'))
recs = j if isinstance(j, list) else j.get('trades', j.get('records', []))
allrecs = sorted([r for r in recs if r.get('code')],
                 key=lambda x: (str(x.get('date', ''))[:10], 0 if x.get('action') == 'BUY' else 1))
open_buys = {}
rows, hold = [], []
for r in allrecs:
    act_ = r.get('action')
    code = r.get('code')
    d = str(r.get('date', ''))[:10]
    if act_ == 'BUY':
        open_buys.setdefault(code, []).append(r)
        continue
    if act_ != 'SELL':
        continue
    b = open_buys.get(code, [None])[0] if open_buys.get(code) else None
    if b and str(b.get('date', ''))[:10] == d:
        b = None                      # 同日买卖(补报), 用记录自带 pnl
    bp = b.get('price') if b else None
    sp = r.get('price')
    sh = r.get('shares') or (b.get('shares') if b else None)
    pnl = r.get('pnl')
    if pnl is None and bp and sp and sh:
        pnl = round(sh * (sp - bp), 1)
    pct = round((sp / bp - 1) * 100, 2) if (bp and sp) else None
    if START <= d <= END:             # 只保留窗口内平仓的
        rows.append(dict(买入日=(str(b.get('date', ''))[:10] if b else ''), 卖出日=d,
                         代码=code, 名称=r.get('name'), 买入价=bp, 卖出价=sp, 股数=sh,
                         盈亏=pnl, 收益率=pct, 备注=(r.get('note') or '')[:46]))
    if open_buys.get(code):
        open_buys[code].pop(0)
# 未平仓: 仅保留窗口内的买入(真实持仓)
for c, lst in open_buys.items():
    for b in lst:
        if START <= str(b.get('date', ''))[:10] <= END:
            hold.append(dict(买入日=str(b['date'])[:10], 卖出日='（持仓中）', 代码=c,
                             名称=b.get('name'), 买入价=b.get('price'), 卖出价=None,
                             股数=b.get('shares'), 盈亏=None, 收益率=None,
                             备注='截至09-11未卖出'))
act = pd.DataFrame(rows + hold)
act['代码'] = act['代码'].astype(str).str.zfill(6)
act = act.sort_values('卖出日')
closed = act[act['盈亏'].notna()]

# ---- 对照 ----
simpnl = pd.to_numeric(sim['单笔收益%'], errors='coerce').dropna()
actpnl = pd.to_numeric(closed['收益率'], errors='coerce').dropna()
acmp = pd.DataFrame([
    ['—', 'V3模拟(每日Top1)', '实际交易(=V4时期实盘)'],
    ['笔数/天数', '%d 个交易日' % pd.to_numeric(sim['单笔收益%'], errors='coerce').notna().sum(),
     '%d 笔平仓' % len(closed)],
    ['封板率', '%.1f%%' % (sim['T日封板'].fillna(False).astype(bool).mean() * 100), '—'],
    ['均收益/笔', '%+.2f%%' % simpnl.mean(), '%+.2f%%' % actpnl.mean()],
    ['胜率', '%.0f%%' % ((simpnl > 0).mean() * 100), '%.0f%%' % ((actpnl > 0).mean() * 100)],
    ['累计(单利)', '%+.2f%%' % simpnl.sum(), '%+d 元' % int(closed['盈亏'].sum())],
    ['最好', '%+.2f%%' % simpnl.max(), '%+.2f%%' % actpnl.max()],
    ['最差', '%+.2f%%' % simpnl.min(), '%+.2f%%' % actpnl.min()],
], columns=['指标', 'V3模型', '实际交易'])

OUT = os.path.join(DESK, '主升浪_V3模拟_vs_实际交易_20260826-20260911.xlsx')
with pd.ExcelWriter(OUT, engine='openpyxl') as w:
    sim.to_excel(w, sheet_name='V3模拟明细', index=False)
    acmp.to_excel(w, sheet_name='对照汇总', index=False)
    act.to_excel(w, sheet_name='实际交易记录', index=False)
print('已输出:', OUT)
print()
print(acmp.to_string(index=False))
print()
print('实际交易明细:')
print(act.to_string(index=False))
