# -*- coding: utf-8 -*-
"""V3 模拟(带候选明细) — 可验证版
对每个买入日, 列出 T-1涨停池里所有通过 gap4-8% 过滤的候选及其 V3 评分,
标出哪只被选中(分数最高), 便于人工核对评分确实在跑。

用法: python scripts/v3_sim_with_candidates.py --start 2026-09-01 --end 2026-09-11
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


def aexit(b):
    if (b.get('pct_change') or 0) >= 9.8:
        return b['close'], 'T+1涨停→挂涨停价成交'
    return (0.7 * (b['high'] + b['open']) / 2 + 0.3 * b['close'],
            'T+1未涨停→70%(H+O)/2+30%收')


cfg = scoring.load_config()
print('评分版本 active = %s (V3量纲: 负分段)' % cfg.get('active'))
print('区间 %s ~ %s\n' % (START, END))

cand_rows, pick_rows = [], []
for T in DAYS:
    if not (START <= T <= END) or T not in auc:
        continue
    prev = [x for x in DAYS if x < T]
    if not prev:
        continue
    D = prev[-1]
    T1 = NX.get(T)
    _tc = {}
    for _c, _r in pools[D].items():
        for _t in str(_r.get('industry') or '').replace('+', '|').split('|'):
            _t = _t.strip()
            if _t:
                _tc[_t] = _tc.get(_t, 0) + 1
    for _c, _r in pools[D].items():
        _ts = [x.strip() for x in str(_r.get('industry') or '').replace('+', '|').split('|') if x.strip()]
        _r['_theme_cnt'] = max([_tc.get(t, 0) for t in _ts] or [0])

    cs = []
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
        _dr = {'turnover': row.get('turnover'),
               'seal_time': str(row.get('first_seal') or '1459')[:5].replace(':', ''),
               'zhaban': row.get('break_times'),
               'sector_bucket': ('>=10' if (row.get('_theme_cnt') or 0) >= 10 else
                                 '5-9' if (row.get('_theme_cnt') or 0) >= 5 else
                                 '3-4' if (row.get('_theme_cnt') or 0) >= 3 else '<3'),
               'float_cap': row.get('float_cap'), 'sector_count': row.get('_theme_cnt') or 1}
        sc, det = scoring.score_active(c, _kk, _dr)
        if sc is None:
            continue
        cs.append(dict(code=c, name=row.get('name', ''), score=sc,
                       gap=round(float(g), 2), cons=det.get('cons', 1),
                       bt=det.get('board_type', ''), vr=round(det.get('vr', 0), 2),
                       ind=(row.get('industry') or '')[:22]))
    if not cs:
        pick_rows.append(dict(T=T, code='', name='（无符合条件标的）', score=None, gap=None,
                              buy=None, t_seal=None, sell=None, ret=None, rule='空仓'))
        continue
    cs.sort(key=lambda x: -x['score'])
    for i, x in enumerate(cs):
        cand_rows.append(dict(买入日=T, 涨停日=D, 代码=x['code'], 名称=x['name'],
                              V3评分=x['score'], 竞价gap=x['gap'], 连板=x['cons'],
                              板型=x['bt'], 量比=x['vr'], 题材=x['ind'],
                              选中='★选中' if i == 0 else ''))
    top = cs[0]
    b0, b1 = kb(top['code'], T), (kb(top['code'], T1) if T1 else None)
    rec = dict(T=T, code=top['code'], name=top['name'], score=top['score'], gap=top['gap'],
               buy=b0['open'] if b0 else None,
               t_seal=(top['code'] in pools.get(T, set())) if b0 else None,
               sell=None, ret=None, rule='')
    if b0 and b1:
        ex, rule = aexit(b1)
        rec.update(sell=round(ex, 3), rule=rule,
                   ret=round((ex - b0['open']) / b0['open'] * 100, 2))
    elif b0 and T1:
        # T+1 交易日存在但个股无K线 → 停牌/无法卖出 (真实持仓风险, 不得当作无数据跳过)
        rec.update(sell=None, rule='⚠ T+1停牌, 无法卖出(仓位被锁)', ret=None)
    pick_rows.append(rec)

cand = pd.DataFrame(cand_rows)
pick = pd.DataFrame(pick_rows)
pick['累计收益%'] = pd.to_numeric(pick['ret'], errors='coerce').fillna(0).cumsum()

# 实际交易记录 (同区间)
j = json.load(open('logs/trading_journal.json', encoding='utf-8'))
recs = j if isinstance(j, list) else j.get('trades', j.get('records', []))
allr = sorted([r for r in recs if r.get('code')],
              key=lambda x: (str(x.get('date', ''))[:10], 0 if x.get('action') == 'BUY' else 1))
ob, arows, hold = {}, [], []
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
            hold.append(dict(买入日=str(b['date'])[:10], 卖出日='（持仓中）', 代码=c_,
                             名称=b.get('name'), 买入价=b.get('price'), 卖出价=None,
                             股数=b.get('shares'), 盈亏=None, 收益率=None, 备注='未卖出'))
act = pd.DataFrame(arows + hold)
if len(act):
    act['代码'] = act['代码'].astype(str).str.zfill(6)
    act = act.sort_values('卖出日')
closed = act[act['盈亏'].notna()] if len(act) else pd.DataFrame()

_picked = pick[pick['code'].notna() & (pick['code'] != '')]
_locked = pick[pick['rule'].astype(str).str.contains('停牌', na=False)]
sp_ = pd.to_numeric(pick['ret'], errors='coerce').dropna()
ap_ = pd.to_numeric(closed['收益率'], errors='coerce').dropna() if len(closed) else pd.Series(dtype=float)
cmp_ = pd.DataFrame([
    ['—', 'V3模型(每日Top1)', '实际交易(V4时期实盘)'],
    ['选出标的天数', '%d (含停牌锁定%d)' % (len(_picked), len(_locked)), '%d 笔平仓' % len(closed)],
    ['T日封板率', '%.1f%%' % (_picked['t_seal'].fillna(False).astype(bool).mean() * 100), '—'],
    ['均收益/笔', '%+.2f%%' % sp_.mean() if len(sp_) else '—',
     '%+.2f%%' % ap_.mean() if len(ap_) else '—'],
    ['胜率', '%.0f%%' % ((sp_ > 0).mean() * 100) if len(sp_) else '—',
     '%.0f%%' % ((ap_ > 0).mean() * 100) if len(ap_) else '—'],
    ['累计(单利)', '%+.2f%%' % sp_.sum() if len(sp_) else '—',
     '%+d 元' % int(closed['盈亏'].sum()) if len(closed) else '—'],
], columns=['指标', 'V3模型', '实际交易'])

OUT = os.path.join(DESK, '主升浪_V3模拟_vs_实际交易_%s_%s.xlsx' % (START.replace('-', ''), END.replace('-', '')))
with pd.ExcelWriter(OUT, engine='openpyxl') as w:
    cand.to_excel(w, sheet_name='候选明细(可验证)', index=False)
    pick.to_excel(w, sheet_name='V3模拟结果', index=False)
    cmp_.to_excel(w, sheet_name='对照汇总', index=False)
    if len(act):
        act.to_excel(w, sheet_name='实际交易记录', index=False)
print('已输出:', OUT)
print()
print(cmp_.to_string(index=False))
print()
print('=== 每日候选 (★=被选中, 按V3评分降序) ===')
for T, g in cand.groupby('买入日'):
    print('【%s】' % T)
    for _, r in g.iterrows():
        print('   %-6s %-8s V3分=%6.1f  gap=%5.2f  连板=%d  %-4s %s %s' % (
            r['代码'], r['名称'], r['V3评分'], r['竞价gap'], r['连板'], r['板型'],
            r['题材'], r['选中']))
