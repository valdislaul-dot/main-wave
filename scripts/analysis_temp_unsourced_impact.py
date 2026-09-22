# -*- coding: utf-8 -*-
"""无来源因子暂停的实际影响 (2026-09-23)

用户拍板「跟A保持一致」后暂停了 seal_time / sector / activity_filter 三项
(dow_score 已直接删除)。本脚本量化这次改动到底改变了什么:

  改前 = disabled_factors: []                       (三项全开)
  改后 = ['seal_time','sector','activity_filter']   (现行配置)

不写回配置; 通过 score_active(config=...) 注入对照。
用法: python scripts/analysis_temp_unsourced_impact.py
"""
import copy, json, os, sys, io, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, 'scripts/daily')
import scoring

TRAIN = ('2026-07-27', '2026-08-25')
TEST = ('2026-08-26', '2026-09-22')
OFF = ['seal_time', 'sector', 'activity_filter']


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


def candidates(T, cfg):
    _lo, _hi = scoring.get_buy_window(cfg)
    prev = [x for x in DAYS if x < T]
    if not prev or T not in auc:
        return []
    D = prev[-1]
    _tc = {}
    for _c, _r in pools[D].items():
        for _t in str(_r.get('industry') or '').replace('+', '|').split('|'):
            _t = _t.strip()
            if _t:
                _tc[_t] = _tc.get(_t, 0) + 1
    out = []
    for c, row in pools[D].items():
        if c.startswith(('300', '301', '688', '8', '9')):
            continue
        s = auc[T].get(c)
        if not s:
            continue
        g = s.get('gap_pct')
        if g is None and s.get('open') and s.get('prev_close'):
            g = (s['open'] - s['prev_close']) / s['prev_close'] * 100
        if g is None or not (_lo <= float(g) <= _hi):
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
            'float_cap': row.get('float_cap'), 'sector_count': tmax or 1}, config=cfg)
        if sc is None:
            continue
        out.append(dict(code=c, name=row.get('name', ''), score=sc, gap=round(float(g), 2),
                        cons=det.get('cons', 1)))
    out.sort(key=lambda x: -x['score'])
    return out


def exit_px(code, d):
    b = kb(code, d)
    if not b or not b.get('open'):
        return None
    if (b.get('pct_change') or 0) >= 9.8:
        return b['close']
    return 0.7 * (b['high'] + b['open']) / 2 + 0.3 * b['close']


DATELIST = [d for d in DAYS if '2026-07-27' <= d <= '2026-09-22']
NEXT = {d: DATELIST[i + 1] for i, d in enumerate(DATELIST) if i + 1 < len(DATELIST)}


def run(cfg, topn):
    recs = []
    for T in DATELIST:
        cs = candidates(T, cfg)[:topn]
        T1 = NEXT.get(T)
        if not cs or not T1:
            continue
        for c in cs:
            b = kb(c['code'], T)
            sp = exit_px(c['code'], T1)
            if not b or not b.get('open') or sp is None:
                continue
            recs.append(dict(date=T, code=c['code'], name=c['name'], score=c['score'],
                             pnl=round((sp - b['open']) / b['open'] * 100, 2)))
    return recs


def stat(recs, lo, hi):
    v = [r['pnl'] for r in recs if lo <= r['date'] <= hi]
    if not v:
        return None
    return len(v), sum(v) / len(v), sum(1 for x in v if x > 0) / len(v) * 100, sum(v)


if __name__ == '__main__':
    base = scoring.load_config()
    before = copy.deepcopy(base); before['disabled_factors'] = []
    after = base

    print('=' * 92)
    print('无来源因子暂停的影响 | 改前=三项全开, 改后=暂停')
    print('=' * 92)

    # ---- 候选数量 ----
    print()
    print('### 候选池规模 (每日 gap 窗内可评分票数) ###')
    print('%-10s %-12s %-12s %s' % ('分段', '改前均', '改后均', '差'))
    for lab, (lo, hi) in (('训练段', TRAIN), ('检验段', TEST)):
        nb, na = [], []
        for T in DATELIST:
            if lo <= T <= hi:
                nb.append(len(candidates(T, before)))
                na.append(len(candidates(T, after)))
        if nb:
            print('%-10s %-12.1f %-12.1f %+.1f  (n=%d日)' % (
                lab, statistics.mean(nb), statistics.mean(na),
                statistics.mean(na) - statistics.mean(nb), len(nb)))

    # ---- 选票与收益 ----
    for topn in (1, 3):
        print()
        print('### 每日买入 Top%d ###' % topn)
        print('%-8s %-26s %-26s' % ('口径', '训练段(笔/均%/胜%/累计%)', '检验段(笔/均%/胜%/累计%)'))
        print('-' * 92)
        for lab, cfg in (('改前', before), ('改后', after)):
            recs = run(cfg, topn)
            cells = []
            for lo, hi in (TRAIN, TEST):
                s = stat(recs, lo, hi)
                cells.append('—' if s is None else '%2d / %+6.2f / %3.0f%% / %+7.1f' % s)
            print('%-8s %-26s %-26s' % (lab, cells[0], cells[1]))

    # ---- Top1 选票分歧 ----
    print()
    print('### Top1 选票分歧 ###')
    rb, ra = run(before, 1), run(after, 1)
    mb = {r['date']: r for r in rb}
    ma = {r['date']: r for r in ra}
    diff = sorted(d for d in ma if d in mb and ma[d]['code'] != mb[d]['code'])
    same = [d for d in ma if d in mb and ma[d]['code'] == mb[d]['code']]
    print('  共同交易日 %d 天 | 选票改变 %d 天 | 选票一致 %d 天' % (len(mb), len(diff), len(same)))
    if diff:
        print()
        print('  %-12s %-20s %-20s' % ('日期', '改前 Top1', '改后 Top1'))
        for d in diff:
            print('  %-12s %-20s %-20s' % (
                d, '%s %+.2f%%' % (mb[d]['name'], mb[d]['pnl']),
                '%s %+.2f%%' % (ma[d]['name'], ma[d]['pnl'])))
    print()
    print('注: 样本量小(全窗口 ~40 个交易日); 幅度差异需按检验段打折解读')
