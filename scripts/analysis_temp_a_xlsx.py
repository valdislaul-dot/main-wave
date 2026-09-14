# -*- coding: utf-8 -*-
"""还原A的真实操作序列: 5组并排时间线 → 合并 → 逐笔轮动表"""
import openpyxl, os, sys, io, datetime, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EPOCH = datetime.date(1899, 12, 30)
def ser2date(n):
    return (EPOCH + datetime.timedelta(days=int(n))).isoformat()

wb = openpyxl.load_workbook('data/副本主升浪.xlsx', data_only=True)
ws = wb['Sheet1']
events = []
for r in ws.iter_rows(min_row=2, values_only=True):
    for blk in range(5):
        t_, b_, s_ = r[blk*3], r[blk*3+1], r[blk*3+2]
        if isinstance(t_, (int, float)) and t_ > 40000:
            d = ser2date(t_)
            if b_: events.append((d, 'BUY', str(b_).strip()))
            if s_: events.append((d, 'SELL', str(s_).strip()))
events.sort()
print(f'事件 {len(events)} 条  {events[0][0]} ~ {events[-1][0]}')
buys = [e for e in events if e[1] == 'BUY']
sells = [e for e in events if e[1] == 'SELL']
print(f'买入 {len(buys)} 笔 | 卖出 {len(sells)} 笔')
print()

# 配成轮动: 每个买入对应下一次同名卖出
open_pos = {}
pairs = []
for d, act, name in events:
    if act == 'BUY':
        if name in open_pos:
            pairs.append((name, open_pos.pop(name), None))
        open_pos[name] = d
    else:
        if name in open_pos:
            pairs.append((name, open_pos.pop(name), d))
        else:
            pairs.append((name, None, d))
for name, b in open_pos.items():
    pairs.append((name, b, None))

def td(a, b):
    da = datetime.date.fromisoformat(a); db = datetime.date.fromisoformat(b)
    return len([1 for i in range((db-da).days) if (da+datetime.timedelta(days=i)).weekday() < 5]) - 1

ok = [(n, b, s) for n, b, s in pairs if b and s]
print(f'完整买卖对 {len(ok)} 笔')
hold = {}
for n, b, s in ok:
    hold.setdefault(td(b, s), []).append(n)
print('\n=== 持有交易日数分布 ===')
for k in sorted(hold):
    print(f'  持有{k}个交易日(买→卖): {len(hold[k]):3d}笔')

print('\n=== 前25笔 (买入日 → 卖出日) ===')
print('%-11s %-11s %-9s %s' % ('买入日', '卖出日', '标的', '持有交易日'))
for n, b, s in ok[:25]:
    print('%-11s %-11s %-9s %d' % (b, s, n, td(b, s)))

json.dump([{'name': n, 'buy': b, 'sell': s, 'hold_td': td(b, s)} for n, b, s in ok],
          open('data/_a_rotation.json', 'w', encoding='utf-8'), ensure_ascii=False)
