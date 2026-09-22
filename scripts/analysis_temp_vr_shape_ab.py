# -*- coding: utf-8 -*-
"""V3 vr_tiers 形状 A/B 对照 (2026-09-23)

背景: A 实际买入的信号日量比分布是 U 型(超额倍数 <0.5x=2.31 / 0.5-1=0.64 /
1-2=0.50 / 2-5=1.13 / >=5=5.59), 而现行 V3 vr_tiers 单调递减(<0.2 给 +40,
>=5 给 0) —— A 超额最多的 >=5x 档在现行体系里得 0 分。

本脚本在同一候选宇宙/同买入窗/同出场口径下, 只换 vr_tiers 形状做对照。
不写回配置; 通过 score_active(config=...) 注入, 生产配置不受影响。

用法: python scripts/analysis_temp_vr_shape_ab.py
"""
import copy, json, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, 'scripts/daily')
import scoring

TRAIN = ('2026-07-27', '2026-08-25')   # 与 09-22 gap窗口分析同一分段
TEST = ('2026-08-26', '2026-09-22')

BASE_TIERS = [[0.2, 40], [0.3, 34], [0.4, 27], [0.5, 20], [0.6, 14], [0.7, 8],
              [0.85, 3], [1.2, -1], [2.5, -2], [5.0, -1], [99, 0]]

CANDIDATES = {
    '现状(单调递减)':    BASE_TIERS,
    # 最小改动: 只把 A 超额(1.90x / 5.23x)的两个高档位补成正分, 其余原样
    'A-最小改(抬高两档)': [[0.2, 40], [0.3, 34], [0.4, 27], [0.5, 20], [0.6, 14], [0.7, 8],
                          [0.85, 3], [1.2, -1], [2.5, -2], [5.0, 19], [99, 40]],
    'A-最小改·半幅':     [[0.2, 40], [0.3, 34], [0.4, 27], [0.5, 20], [0.6, 14], [0.7, 8],
                          [0.85, 3], [1.2, -1], [2.5, -2], [5.0, 9], [99, 20]],
    # 按 A 的四段对数超额倍数线性映射到 [-2,40]: <0.5->22.4 / 0.5-2.5->-2.0 / 2.5-5->19.3 / >=5->40
    'A-四段全量':        [[0.2, 22], [0.3, 22], [0.4, 22], [0.5, 22], [0.6, -2], [0.7, -2],
                          [0.85, -2], [1.2, -2], [2.5, -2], [5.0, 19], [99, 40]],
}


def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))


# ---- 数据加载(与 v3_sim_hold.py 同口径) ----
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
    """当日候选按评分降序(完整列表), 与 v3_sim_hold.pick_of 同一宇宙与入参"""
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
                        cons=det.get('cons', 1), bt=det.get('board_type', '')))
    out.sort(key=lambda x: -x['score'])
    return out


def exit_px(code, d):
    """v3_sim_hold 的 A式出场口径"""
    b = kb(code, d)
    if not b or not b.get('open'):
        return None
    if (b.get('pct_change') or 0) >= 9.8:
        return b['close']
    return 0.7 * (b['high'] + b['open']) / 2 + 0.3 * b['close']


DATELIST = [d for d in DAYS if '2026-07-27' <= d <= '2026-09-22']
NEXT = {d: DATELIST[i + 1] for i, d in enumerate(DATELIST) if i + 1 < len(DATELIST)}


def run(cfg, topn):
    """按 topn 选股: 每日买入前 topn 只(等权), 次日A式出场"""
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
                             cons=c['cons'], gap=c['gap'],
                             pnl=round((sp - b['open']) / b['open'] * 100, 2)))
    return recs


def stat(recs, lo, hi):
    v = [r['pnl'] for r in recs if lo <= r['date'] <= hi]
    if not v:
        return None
    return len(v), sum(v) / len(v), sum(1 for x in v if x > 0) / len(v) * 100, sum(v)


if __name__ == '__main__':
    base_cfg = scoring.load_config()
    print('=' * 96)
    print('V3 vr_tiers 形状 A/B 对照 | 买入=T日开盘, 出场=次日A式(70%(H+O)/2+30%收, 涨停→收盘)')
    print('分段: 训练段 %s~%s | 检验段 %s~%s' % (TRAIN[0], TRAIN[1], TEST[0], TEST[1]))
    print('=' * 96)
    for topn in (1, 3):
        print()
        print('### 每日买入 Top%d ###' % topn)
        print('%-18s %-26s %-26s' % ('形状', '训练段(笔/均%/胜%/累计%)', '检验段(笔/均%/胜%/累计%)'))
        print('-' * 96)
        for name, tiers in CANDIDATES.items():
            cfg = copy.deepcopy(base_cfg)
            cfg['tables']['v3']['vr_tiers'] = copy.deepcopy(tiers)
            recs = run(cfg, topn)
            cells = []
            for lo, hi in (TRAIN, TEST):
                s = stat(recs, lo, hi)
                cells.append('—' if s is None else '%2d / %+6.2f / %3.0f%% / %+7.1f' % s)
            print('%-18s %-26s %-26s' % (name, cells[0], cells[1]))
    print()
    print('注: 样本量小(全窗口仅 ~40 个交易日), 检验段笔数见上表; 幅度差异需按检验段打折解读')

    # ---- 差异诊断: 形状改动到底影响了几天的 Top1 ----
    print()
    print('### 差异诊断 (Top1) — 与"现状"选了不同票的天数, 及差异归属 ###')
    print('%-18s %-12s %-24s %-24s' % ('形状', '选票不同', '仅差异日 笔/均%/累计%', '共同日 笔/均%'))
    print('-' * 84)
    base_pick = {r['date']: r for r in run(base_cfg, 1)}
    for name, tiers in CANDIDATES.items():
        if name.startswith('现状'):
            continue
        cfg = copy.deepcopy(base_cfg)
        cfg['tables']['v3']['vr_tiers'] = copy.deepcopy(tiers)
        alt = {r['date']: r for r in run(cfg, 1)}
        diff = [d for d in alt if d in base_pick and alt[d]['code'] != base_pick[d]['code']]
        same = [d for d in alt if d in base_pick and alt[d]['code'] == base_pick[d]['code']]
        dv = [alt[d]['pnl'] for d in diff]
        sv = [alt[d]['pnl'] for d in same]
        print('%-18s %-12s %-24s %-24s' % (
            name,
            '%d 天' % len(diff),
            '—' if not dv else '%2d / %+6.2f / %+6.1f' % (len(dv), sum(dv) / len(dv), sum(dv)),
            '—' if not sv else '%2d / %+6.2f' % (len(sv), sum(sv) / len(sv))))
