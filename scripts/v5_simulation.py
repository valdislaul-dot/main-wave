# -*- coding: utf-8 -*-
"""V5 新模型交易模拟表 (2026-08-26 ~ 2026-09-11)
流程: T-1涨停池 → T日竞价gap(4-8%) → V5评分 → Top1 → T开盘买入 → T+1按A式出场
输出: 桌面 Excel
"""
import json, os, sys, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, 'scripts/daily')
import scoring

DESK = os.path.join(os.path.expanduser('~'), 'Desktop')
START, END = '2026-08-26', '2026-09-11'
CFG_TAG = sys.argv[sys.argv.index('--tag') + 1] if '--tag' in sys.argv else 'V5'
SCORER = sys.argv[sys.argv.index('--scorer') + 1] if '--scorer' in sys.argv else 'active'
CFG_FILE = sys.argv[sys.argv.index('--config') + 1] if '--config' in sys.argv else None
# 2026-09-12: 禁止本脚本写回定稿配置(改配置一律走人工确认)。--config 仅做只读对照,
# 通过临时替换配置对象实现, 不落盘。
if CFG_FILE:
    print('[只读对照] 指定配置', CFG_FILE, '(不写入 data/scoring_config.json)')


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
        if b.get('date') == d:
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


recs = []
for T in DAYS:
    if not (START <= T <= END) or T not in auc:
        continue
    prev = [x for x in DAYS if x < T]
    if not prev:
        continue
    D = prev[-1]
    T1 = NX.get(T)
    # 题材热度: 该题材在当日池中出现的只数 (用于 sector_bucket)
    _tc = {}
    for _c, _r in pools[D].items():
        for _t in str(_r.get('industry') or '').replace('+', '|').split('|'):
            _t = _t.strip()
            if _t:
                _tc[_t] = _tc.get(_t, 0) + 1
    for _c, _r in pools[D].items():
        _ts = [x.strip() for x in str(_r.get('industry') or '').replace('+', '|').split('|') if x.strip()]
        _r['_theme_cnt'] = max([_tc.get(t, 0) for t in _ts] or [0])
    cands = []
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
        bt = row.get('board_type') or ''
        ld = int(row.get('limit_days', 1) or 1)
        if '一字' in bt or (ld >= 4 and '一字' in bt):
            continue
        # ⚠ score_v4 以K线最后一根bar为"今天" → 历史模拟必须截断到 D 日
        _kk = [b for b in kl(c) if str(b.get('date')) <= D]
        if not _kk or _kk[-1].get('date') != D:
            continue
        _dr = {
            'turnover': row.get('turnover'),
            'seal_time': str(row.get('first_seal') or '1459')[:5].replace(':', ''),
            'zhaban': row.get('break_times'),
            'sector_bucket': ('>=10' if (row.get('_theme_cnt') or 0) >= 10 else
                              '5-9' if (row.get('_theme_cnt') or 0) >= 5 else
                              '3-4' if (row.get('_theme_cnt') or 0) >= 3 else '<3'),
            'float_cap': row.get('float_cap'),
        }
        if SCORER == 'active':
            sc, det = scoring.score_active(c, _kk, details_raw=_dr)
        elif SCORER == 'v3':
            _cfg3 = json.load(open('backup/scoring_config_v3全段_20260826.json', encoding='utf-8'))
            _r3 = scoring.compute_score(c, _kk, details_raw=_dr, version='v3', config=_cfg3)
            sc, det = (_r3[0], _r3[1]) if isinstance(_r3, tuple) else (_r3, {'factor_scores': {}, 'vr': 0, 'cons': 0, 'board_type': '', 'dt_p': 0})
            det = dict(det) if det else {}
            det.setdefault('factor_scores', {})
            det.setdefault('vr', 0); det.setdefault('cons', 0)
            det.setdefault('board_type', ''); det.setdefault('dt_p', 0)
        else:
            sc, det = scoring.score_v4(c, _kk, details_raw=_dr)
        if sc is None:
            continue
        cands.append(dict(code=c, name=row.get('name', ''), score=sc, gap=float(g),
                          det=det, row=row, ind=row.get('industry') or ''))
    if not cands:
        recs.append(dict(T=T, D=D, code='', name='（无符合条件标的）', score=None,
                         gap=None, buy=None, note='空仓'))
        continue
    cands.sort(key=lambda x: -x['score'])
    top = cands[0]
    b0, b1 = kb(top['code'], T), kb(top['code'], T1) if T1 else None
    rec = dict(T=T, D=D, code=top['code'], name=top['name'], score=top['score'],
               gap=top['gap'],
               t_close=b0['close'] if b0 else None,
               t_seal=(top['code'] in pools.get(T, set())),
               buy=b0['open'] if b0 else None,
               seal_txt=top['det']['factor_scores'],
               vr=top['det']['vr'], cons=top['det']['cons'],
               board_type=top['det']['board_type'], industry=top['ind'])
    if b0 and b1:
        ex, rule = aexit(b1)
        rec['t1_open'] = b1['open']
        rec['t1_high'] = b1['high']
        rec['t1_close'] = b1['close']
        rec['t1_seal'] = (top['code'] in pools.get(T1, set()))
        rec['sell'] = round(ex, 3)
        rec['rule'] = rule
        rec['ret'] = round((ex - b0['open']) / b0['open'] * 100, 2)
    recs.append(rec)

df = pd.DataFrame(recs)
df['累计收益%'] = df['ret'].fillna(0).cumsum()
df['code'] = df['code'].astype(str)
outed = df[['T', 'D', 'code', 'name', 'score', 'gap', 'buy', 't_close', 't_seal',
            't1_open', 't1_high', 't1_close', 't1_seal', 'sell', 'rule', 'ret', '累计收益%']].copy()
outed.columns = ['买入日', '涨停日', '代码', '名称', 'V5评分', '竞价gap%', '买入价(开盘)',
                 'T日收盘', 'T日封板', 'T+1开盘', 'T+1最高', 'T+1收盘', 'T+1封板',
                 '卖出价', '卖出规则', '单笔收益%', '累计收益%']
outed.insert(6, '连板数', df['cons'])
outed.insert(7, '板型', df['board_type'])
outed.insert(8, '量比', df['vr'])
outed.insert(9, '题材', df['industry'])

traded = df[df['ret'].notna()]
summary = pd.DataFrame([
    ['统计区间', '%s ~ %s' % (START, END)],
    ['交易日数', len(df)],
    ['有交易天数', len(traded)],
    ['封板天数(T日)', int(df['t_seal'].fillna(False).sum())],
    ['T日封板率', '%.1f%%' % (df['t_seal'].fillna(False).mean() * 100)],
    ['单笔均收益', '%+.2f%%' % traded['ret'].mean()],
    ['胜率', '%.0f%%' % ((traded['ret'] > 0).mean() * 100)],
    ['最好', '%+.2f%%' % traded['ret'].max()],
    ['最差', '%+.2f%%' % traded['ret'].min()],
    ['累计(单利)', '%+.2f%%' % traded['ret'].sum()],
], columns=['指标', '值'])

# 同期实际推荐对照
rev = json.load(open('logs/recommendation_review.json', encoding='utf-8'))['reviews']
act = [dict(买入日=d, 代码=s.get('code'), 名称=s.get('name'), 评分=s.get('score'),
            竞价gap=s.get('rec_gap'),
            T日封板='是' if s.get('T', {}).get('limit_up') else '否',
            单笔收益=s.get('pnl_pct'))
       for d, r in rev.items() if START <= d <= END for s in r['stocks']]
adf = pd.DataFrame(act)
acmp = pd.DataFrame([
    ['实际推荐 笔数', len(adf)],
    ['实际推荐 封板率', '%.1f%%' % (adf['T日封板'].eq('是').mean() * 100)],
    ['实际推荐 均收益', '%+.2f%%' % adf['单笔收益'].mean()],
    ['模型 Top1 封板率', '%.1f%%' % (df['t_seal'].fillna(False).mean() * 100)],
    ['模型 Top1 均收益', '%+.2f%%' % traded['ret'].mean()],
], columns=['指标', '值'])

OUT = os.path.join(DESK, '模拟交易_对照_20260826-20260911_%s.xlsx' % CFG_TAG)
with pd.ExcelWriter(OUT, engine='openpyxl') as w:
    outed.to_excel(w, sheet_name='V5模拟明细', index=False)
    _ws = w.sheets['V5模拟明细']
    for _r in range(2, len(outed) + 2):
        _ws.cell(row=_r, column=3).number_format = '@'   # 代码列存文本, 防变数字
        _ws.cell(row=_r, column=3).value = str(outed.iloc[_r - 2, 2])
    summary.to_excel(w, sheet_name='汇总', index=False)
    acmp.to_excel(w, sheet_name='与实际推荐对照', index=False)
    adf.to_excel(w, sheet_name='同期实际推荐', index=False)
print('已输出:', OUT)
print()
print(summary.to_string(index=False))
print()
print(acmp.to_string(index=False))
