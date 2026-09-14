# -*- coding: utf-8 -*-
"""V3 模拟(持仓跟踪版) — 连续选中同一只则一直持有

规则(2026-09-12 用户拍板):
  ① 空仓时 → 买入当日V3评分Top1(开盘价)
  ② 持仓中且当日Top1 == 持仓 → 继续持有, 不卖不买
  ③ 持仓中且当日Top1 != 持仓 → 卖出持仓(轮换日开盘价, 与买入同步) + 买入新Top1
  ④ 持仓停牌 → 卖不掉, 仓位锁定, 当日无法买新票(现金不足)
  ⑤ 出场价可切换: --exit open(轮换日开盘, 默认/可执行) | a(当日A式) | high(当日最高,上限参考)

用法: python scripts/v3_sim_hold.py --start 2026-09-01 --end 2026-09-11
"""
import json, os, sys, io, warnings
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, 'scripts/daily')
import scoring

DESK = os.path.join(os.path.expanduser('~'), 'Desktop')
A = sys.argv
START = A[A.index('--start') + 1] if '--start' in A else '2026-09-01'
END = A[A.index('--end') + 1] if '--end' in A else '2026-09-11'
EXITM = A[A.index('--exit') + 1] if '--exit' in A else 'a'


def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))


pools = {}
for f in sorted(os.listdir('data/zt_pool')):
    if not f.endswith('.json') or f == 'stock_index.json':
        continue
    ymd = f[:-5]
    d = ymd[:4] + '-' + ymd[4:6] + '-' + ymd[6:8]
    data = rd('data/zt_pool/' + f)
    rows = data if isinstance(data, list) else data.get('stocks', [])
    pools[d] = {str(x.get('code', '')).zfill(6): x for x in rows if x.get('code')}
DAYS = sorted(pools)
NX = {d: DAYS[i + 1] for i, d in enumerate(DAYS) if i + 1 < len(DAYS)}
auc = {}
for f in sorted(os.listdir('data/auction')):
    if not f.endswith('.json') or '_' in f:
        continue
    dd = json.load(open('data/auction/' + f, encoding='utf-8'))
    auc[f[:-5]] = {str(s.get('code', '')).zfill(6): s for s in dd.get('stocks', [])}
AUG = json.load(open('data/_regime_klines_aug.json', encoding='utf-8'))
_kl = {}


def kl(c):
    if c in _kl:
        return _kl[c]
    p = 'data/kline_data/' + c + '.json'
    rows = []
    if os.path.exists(p):
        raw = rd(p)
        rows = raw.get('data', raw) if isinstance(raw, dict) else raw
    _kl[c] = rows
    return rows


def kb(c, d):
    for b in kl(c):
        if str(b.get('date')) == d:
            return b
    for b in (AUG.get(c) or []):
        if b.get('date') == d:
            return b
    return None


def pick_of(T):
    """当日 V3 评分 Top1 (gap4-8%, 排除一字)"""
    prev = [x for x in DAYS if x < T]
    if not prev or T not in auc:
        return None
    D = prev[-1]
    _tc = {}
    for _c, _r in pools[D].items():
        for _t in str(_r.get('industry') or '').replace('+', '|').split('|'):
            _t = _t.strip()
            if _t:
                _tc[_t] = _tc.get(_t, 0) + 1
    best = None
    for c, row in pools[D].items():
        if c.startswith(('300', '301', '688', '8', '9')):
            continue
        s = auc[T].get(c)
        if not s:
            continue
        g = s.get('gap_pct')
        if g is None and s.get('open') and s.get('prev_close'):
            g = (s['open'] - s['prev_close']) / s['prev_close'] * 100
        if g is None or not (4.0 <= float(g) <= 8.0):
            continue
        if '一字' in (row.get('board_type') or ''):
            continue
        _kk = [b for b in kl(c) if str(b.get('date')) <= D]
        if not _kk or _kk[-1].get('date') != D:
            continue
        ts = [x.strip() for x in str(row.get('industry') or '').replace('+', '|').split('|') if x.strip()]
        tmax = max([_tc.get(t, 0) for t in ts] or [0])
        sc, det = scoring.score_active(c, _kk, {
            'turnover': row.get('turnover'),
            'seal_time': str(row.get('first_seal') or '1459')[:5].replace(':', ''),
            'zhaban': row.get('break_times'),
            'sector_bucket': ('>=10' if tmax >= 10 else '5-9' if tmax >= 5 else '3-4' if tmax >= 3 else '<3'),
            'float_cap': row.get('float_cap'), 'sector_count': tmax or 1})
        if sc is None:
            continue
        if best is None or sc > best['score']:
            best = dict(code=c, name=row.get('name', ''), score=sc,
                        gap=round(float(g), 2), cons=det.get('cons', 1),
                        bt=det.get('board_type', ''))
    return best


def sell_price(code, d, buy_px):
    b = kb(code, d)
    if not b or not b.get('open'):
        return None, '⚠ 停牌/无行情, 卖不掉'
    if EXITM == 'open':
        return b['open'], '轮换日开盘价卖'
    if EXITM == 'high':
        return b['high'], '轮换日最高价卖(上限参考)'
    if (b.get('pct_change') or 0) >= 9.8:
        return b['close'], '轮换日涨停→挂涨停价成交'
    return 0.7 * (b['high'] + b['open']) / 2 + 0.3 * b['close'], '轮换日A式(70%(H+O)/2+30%收)'


log = []
holding = None
for T in DAYS:
    if not (START <= T <= END):
        continue
    p = pick_of(T)
    if holding and p is None:
        # 今日无候选 → 无可换标的, 继续持有(不因空仓日而卖出)
        log.append(dict(日期=T, 动作='继续持有', 代码=holding['code'], 名称=holding['name'],
                        V3评分=None, 价格=None, 收益=None, 说明='当日无候选 → 持仓延续'))
        holding['days'] += 1
        continue
    if holding:
        if p and p['code'] == holding['code']:
            log.append(dict(日期=T, 动作='继续持有', 代码=holding['code'], 名称=holding['name'],
                            V3评分=p['score'], 价格=None, 收益=None,
                            说明='当日Top1仍是它 → 不卖不买, 持仓延续'))
            continue
        sp, rule = sell_price(holding['code'], T, holding['buy'])
        if sp is None:
            log.append(dict(日期=T, 动作='⚠ 锁仓', 代码=holding['code'], 名称=holding['name'],
                            V3评分=(p['score'] if p else None), 价格=None, 收益=None,
                            说明=rule + ' → 无法换股, 今日空转'))
            continue
        pnl = round((sp - holding['buy']) / holding['buy'] * 100, 2)
        log.append(dict(日期=T, 动作='卖出', 代码=holding['code'], 名称=holding['name'],
                        V3评分=None, 价格=round(sp, 3), 收益=pnl,
                        说明='%s 持有%d个交易日' % (rule, holding['days'])))
        holding = None
    if p:
        b = kb(p['code'], T)
        if b and b.get('open'):
            holding = dict(code=p['code'], name=p['name'], buy=b['open'], days=1)
            log.append(dict(日期=T, 动作='买入', 代码=p['code'], 名称=p['name'],
                            V3评分=p['score'], 价格=b['open'], 收益=None,
                            说明='V3 Top1 (gap %.2f%%, %d板, %s)' % (p['gap'], p['cons'], p['bt'])))
        else:
            log.append(dict(日期=T, 动作='放弃', 代码=p['code'], 名称=p['name'],
                            V3评分=p['score'], 价格=None, 收益=None, 说明='无开盘价数据'))
    else:
        log.append(dict(日期=T, 动作='空仓', 代码='', 名称='（无符合条件标的）',
                        V3评分=None, 价格=None, 收益=None, 说明='当日无候选'))
    if holding:
        holding['days'] += 1

# 期末未平仓: 用停牌前最后收盘价做市值参考(无法卖出, 仅标注)
unreal = None
if holding:
    last = None
    for b in sorted(kl(holding['code']), key=lambda x: str(x.get('date'))):
        if str(b.get('date')) <= END:
            last = b
    if last and last.get('close'):
        unreal = round((last['close'] - holding['buy']) / holding['buy'] * 100, 2)
    log.append(dict(日期='期末', 动作='持仓中(无法卖出)', 代码=holding['code'], 名称=holding['name'],
                    V3评分=None, 价格=(last['close'] if last else None), 收益=unreal,
                    说明='停牌锁定; 按停牌前收盘%s估值' % (last['date'] if last else '?')))

L = pd.DataFrame(log)
trades = L[L['动作'] == '卖出'].copy()
trades['收益'] = pd.to_numeric(trades['收益'], errors='coerce')
locked = L[L['动作'] == '⚠ 锁仓']

# 实际交易
j = json.load(open('logs/trading_journal.json', encoding='utf-8'))
recs = j if isinstance(j, list) else j.get('trades', j.get('records', []))
allr = sorted([r for r in recs if r.get('code')],
              key=lambda x: (str(x.get('date', ''))[:10], 0 if x.get('action') == 'BUY' else 1))
ob, arows, hold_a = {}, [], []
for r in allr:
    a_, c_, d_ = r.get('action'), r.get('code'), str(r.get('date', ''))[:10]
    if a_ == 'BUY':
        ob.setdefault(c_, []).append(r)
        continue
    if a_ != 'SELL':
        continue
    b = ob.get(c_, [None])[0] if ob.get(c_) else None
    if b and str(b.get('date', ''))[:10] == d_:
        b = None
    bp, sp = (b.get('price') if b else None), r.get('price')
    sh = r.get('shares') or (b.get('shares') if b else None)
    pnl = r.get('pnl')
    if pnl is None and bp and sp and sh:
        pnl = round(sh * (sp - bp), 1)
    pct = round((sp / bp - 1) * 100, 2) if (bp and sp) else None
    if START <= d_ <= END:
        arows.append(dict(买入日=(str(b.get('date', ''))[:10] if b else ''), 卖出日=d_,
                          代码=c_, 名称=r.get('name'), 买入价=bp, 卖出价=sp, 股数=sh,
                          盈亏=pnl, 收益率=pct, 备注=(r.get('note') or '')[:44]))
    if ob.get(c_):
        ob[c_].pop(0)
for c_, lst in ob.items():
    for b in lst:
        if START <= str(b.get('date', ''))[:10] <= END:
            hold_a.append(dict(买入日=str(b['date'])[:10], 卖出日='（持仓中）', 代码=c_,
                               名称=b.get('name'), 买入价=b.get('price'), 卖出价=None,
                               股数=b.get('shares'), 盈亏=None, 收益率=None, 备注='未卖出'))
act = pd.DataFrame(arows + hold_a)
if len(act):
    act['代码'] = act['代码'].astype(str).str.zfill(6)
    act = act.sort_values('卖出日')
closed = act[act['盈亏'].notna()] if len(act) else pd.DataFrame()

tp = trades['收益'].dropna()
ap = pd.to_numeric(closed['收益率'], errors='coerce').dropna() if len(closed) else pd.Series(dtype=float)
cmp_ = pd.DataFrame([
    ['—', 'V3模型(持仓跟踪)', '实际交易(V4实盘)'],
    ['平仓笔数', len(tp), len(closed)],
    ['均收益/笔', '%+.2f%%' % tp.mean() if len(tp) else '—', '%+.2f%%' % ap.mean() if len(ap) else '—'],
    ['胜率', '%.0f%%' % ((tp > 0).mean() * 100) if len(tp) else '—',
     '%.0f%%' % ((ap > 0).mean() * 100) if len(ap) else '—'],
    ['累计(单利)', '%+.2f%%' % tp.sum() if len(tp) else '—',
     '%+d 元' % int(closed['盈亏'].sum()) if len(closed) else '—'],
    ['最好/最差', ('%+.2f%% / %+.2f%%' % (tp.max(), tp.min())) if len(tp) else '—',
     ('%+.2f%% / %+.2f%%' % (ap.max(), ap.min())) if len(ap) else '—'],
    ['锁仓(无法卖出)天数', len(locked), '—'],
    ['期末被锁仓位浮盈', ('%+.2f%% (未实现)' % unreal) if unreal is not None else '无',
     '—'],
    ['合计(已平仓+锁仓浮盈)', ('%+.2f%%' % (tp.sum() + (unreal or 0))) if len(tp) else '—', '—'],
], columns=['指标', 'V3模型', '实际交易'])

OUT = os.path.join(DESK, '主升浪_V3模拟(持有版)_vs_实际交易_%s_%s.xlsx'
                   % (START.replace('-', ''), END.replace('-', '')))
with pd.ExcelWriter(OUT, engine='openpyxl') as w:
    L.to_excel(w, sheet_name='V3模拟流水', index=False)
    cmp_.to_excel(w, sheet_name='对照汇总', index=False)
    if len(act):
        act.to_excel(w, sheet_name='实际交易记录', index=False)
print('出场价口径 =', EXITM)
print('已输出:', OUT)
print()
print(cmp_.to_string(index=False))
print()
print('=== V3 模拟流水 ===')
print(L.to_string(index=False))
