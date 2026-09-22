# -*- coding: utf-8 -*-
"""A 盘中卖出规则验证台 (2026-09-23)

目的: 判断 A 资料里的盘中规则能否程序化 —— 即在 1 分钟粒度上, 该规则触发后
市场的实际走向是否支持"走"或"留"的判断。

为什么现在才做: 此前 `analysis_temp_a_intraday.py` 只能用腾讯 m15(15分钟),
**m15 在物理上无法验证「5分钟内破7%」**。2026-09-02 起 `data/minute_kline/`
开始成规模落 1 分钟数据(全天 240 根, 09:31~15:00), 覆盖 T-1 涨停池 56~90%,
本脚本是该数据的第一批使用者。

样本: T-1 涨停池股票在 T 日的 1 分钟路径, T ∈ [09-02, 09-22]
      (09-01 及之前覆盖率仅 9~17%, 不可用)

规则(源自 资料/连板模式_选股与卖点逻辑_Claude_Code知识库.md):
  §7.1 炸板真修复 = 高开 + 立即拉升 + 5分钟内破7% ; 破0% 或 跌破分时均线 → 走
  §6.3 爆量烂板回封 → 弱转强, 拉升>7%冲板
  §6.1 前日爆量+今日缩量强板 → 次日不足5%高开 = 第一卖点

口径说明:
  · 分时均线(VWAP) = Σ(典型价×V)/ΣV, 典型价=(H+L+C)/3
    (min1 无 amount 字段, 用典型价近似; 与 A 看的"分时均价线"同源但非精确)
  · 触发价: 破0%→昨收 | 破VWAP→当时VWAP | 破+7%→昨收×1.07
  · 全部用分钟级"触及即成交"近似, 不含滑点

用法: python scripts/analysis_temp_intraday_rules.py
"""
import os, sys, io, json, collections, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MK_DIR = 'data/minute_kline'
KL_DIR = 'data/kline_data'
T_LO, T_HI = '2026-09-02', '2026-09-22'
MIN_BARS = 100          # 少于此视为数据不全, 丢弃


def rd(p):
    for enc in ('utf-8', 'gbk'):
        try:
            raw = json.load(open(p, encoding=enc))
            return raw.get('data', raw) if isinstance(raw, dict) else raw
        except UnicodeDecodeError:
            continue
    return None


# ---------- 加载 ----------
mk = collections.defaultdict(set)
for f in os.listdir(MK_DIR):
    if f.endswith('.json') and not f.startswith('_'):
        c, d = f[:-5].rsplit('_', 1)
        mk[d].add(c)

pools = {}
for f in sorted(os.listdir('data/zt_pool')):
    if not f.endswith('.json') or f == 'stock_index.json':
        continue
    ymd = f[:-5]
    pools[ymd[:4] + '-' + ymd[4:6] + '-' + ymd[6:8]] = f
POOL_DAYS = sorted(pools)

_kl = {}


def kl(code):
    if code not in _kl:
        p = os.path.join(KL_DIR, code + '.json')
        _kl[code] = rd(p) if os.path.exists(p) else None
    return _kl[code]


def daily(code, date):
    """日线某日 bar"""
    k = kl(code)
    if not k:
        return None
    return next((b for b in k if str(b.get('date')) == date), None)


def prev_daily(code, date):
    """严格早于 date 的最后一根日线"""
    k = kl(code)
    if not k:
        return None
    prev = [b for b in k if str(b.get('date')) < date]
    return prev[-1] if prev else None


def load_path(code, T):
    """返回 (bars, prev_close) 或 None

    ⚠ 本脚本刻意**不用 T+1 数据**: 本地 T+1 覆盖率仅 43%, 且缺的是"T日没涨停"的票
      (K线库只更新当日涨停池+持仓 —— 见 memory: kline_update_scope_gap),
      是有偏样本。实测用它算出「5分钟内破7% 触发价→T+1收盘 +5.23%/67%胜」,
      但同一口径 kline 覆盖率恰好≈触发组的封板率 → 该数字是幸存者偏差, 已弃用。
    """
    p = os.path.join(MK_DIR, '%s_%s.json' % (code, T))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding='utf-8'))
    bars = d.get('min1') or []
    if len(bars) < MIN_BARS:
        return None
    pb = prev_daily(code, T)
    if not pb or not pb.get('close'):
        return None
    return bars, float(pb['close'])


def analyze(bars, prev_close):
    """对单只股票单日, 算触发时点与后续收益"""
    open_px = float(bars[0]['o'])
    close_px = float(bars[-1]['c'])
    high = max(float(b['h']) for b in bars)
    low = min(float(b['l']) for b in bars)
    gap = (open_px - prev_close) / prev_close * 100
    chg = (close_px - prev_close) / prev_close * 100

    up7 = prev_close * 1.07
    r = dict(open=open_px, close=close_px, high=high, low=low, prev_close=prev_close,
             gap=gap, chg=chg, limit_up=chg >= 9.8,
             ret_open_close=(close_px - open_px) / open_px * 100)

    cum_pv = cum_v = 0.0
    t0 = t_vwap = t_up7 = t_up7_5 = None
    px0 = px_vwap = px_up7 = None
    for i, b in enumerate(bars, 1):
        o, h, l, c, v = float(b['o']), float(b['h']), float(b['l']), float(b['c']), float(b['v'])
        # --- 分时均线用"截至上一根"的累计值(与实盘看到的一致) ---
        vwap_so_far = (cum_pv / cum_v) if cum_v > 0 else o
        if t0 is None and l <= prev_close:
            t0, px0 = i, prev_close
        if t_vwap is None and cum_v > 0 and l <= vwap_so_far:
            t_vwap, px_vwap = i, vwap_so_far
        if t_up7 is None and h >= up7:
            t_up7, px_up7 = i, up7
            if i <= 5:
                t_up7_5 = i
        cum_pv += ((h + l + c) / 3.0) * v
        cum_v += v

    r.update(t_break0=t0, t_breakvwap=t_vwap, t_up7=t_up7, t_up7_5=t_up7_5)
    for tag, t, px in (('break0', t0, px0), ('breakvwap', t_vwap, px_vwap), ('up7', t_up7, px_up7)):
        r['ret_%s_close' % tag] = ((close_px - px) / px * 100) if (t and px) else None
    return r


def seg(rows, key):
    v = [x[key] for x in rows if x.get(key) is not None]
    if not v:
        return None
    return len(v), statistics.mean(v), sum(1 for y in v if y > 0) / len(v) * 100


if __name__ == '__main__':
    rows = []
    for T in sorted(mk):
        if not (T_LO <= T <= T_HI):
            continue
        prev = [d for d in POOL_DAYS if d < T]
        if not prev:
            continue
        pdf = pools[prev[-1]]
        data = rd(os.path.join('data/zt_pool', pdf))
        data = data if isinstance(data, list) else (data or {}).get('stocks', [])
        nBefore = len(rows)
        for s in data:
            c = str(s.get('code', '')).zfill(6)
            if c.startswith(('300', '301', '688', '8', '9')):
                continue
            if c not in mk[T]:
                continue
            lp = load_path(c, T)
            if not lp:
                continue
            r = analyze(*lp)
            r.update(code=c, date=T, name=s.get('name', ''), cons=s.get('limit_days', '?'),
                     _bars=lp[0])
            rows.append(r)
        print('  %s  池%3d  可用%3d' % (T, len(data), len(rows) - nBefore))

    print()
    print('=' * 78)
    print('样本: %d 个 (股票×交易日)  | 窗口 %s ~ %s' % (len(rows), T_LO, T_HI))
    print('=' * 78)
    base = seg(rows, 'ret_open_close')
    print('基线(开盘→收盘 均收益): %d笔 均%+.2f%% 胜%.0f%%' % base)
    print('当日收盘涨停比例: %.1f%%' % (100 * sum(1 for x in rows if x['limit_up']) / len(rows)))
    print()

    # ---------- 规则1: 破0% → 走 ----------
    print('【规则1】破0%(跌破昨收) → 走   §7.1/§6.3')
    hit = [x for x in rows if x['t_break0']]
    mis = [x for x in rows if not x['t_break0']]
    print('  触发 %d笔(%.0f%%) | 未触发 %d笔' % (len(hit), 100 * len(hit) / len(rows), len(mis)))
    s = seg(hit, 'ret_break0_close')
    print('  ★ 触发后持到收盘: %d笔 均%+.2f%% 胜%.0f%%   ← 为负=卖对了' % s)
    print('  未触发组 开盘→收盘 均%+.2f%%' % (seg(mis, 'ret_open_close')[1],))
    print('  触发组最终收盘涨停 %.1f%% | 未触发组 %.1f%%' % (
        100 * sum(1 for x in hit if x['limit_up']) / max(len(hit), 1),
        100 * sum(1 for x in mis if x['limit_up']) / max(len(mis), 1)))
    # 触发时点分布
    tk = collections.Counter('开盘首5min' if x['t_break0'] <= 5 else
                             '5-30min' if x['t_break0'] <= 30 else
                             '30-120min' if x['t_break0'] <= 120 else '尾盘' for x in hit)
    print('  触发时点:', dict(tk))
    print()

    # ---------- 规则2: 破分时均线 → 走 ----------
    print('【规则2】破分时均线(VWAP) → 走   §7.1')
    hit2 = [x for x in rows if x['t_breakvwap']]
    s2 = seg(hit2, 'ret_breakvwap_close')
    print('  触发 %d笔(%.0f%%)' % (len(hit2), 100 * len(hit2) / len(rows)))
    print('  ★ 触发后持到收盘: %d笔 均%+.2f%% 胜%.0f%%   ← 为负=卖对了' % s2)
    m2 = [x for x in rows if not x['t_breakvwap']]
    if m2:
        print('  未触发组 开盘→收盘 均%+.2f%% 涨停率%.0f%%' % (
            seg(m2, 'ret_open_close')[1], 100 * sum(1 for x in m2 if x['limit_up']) / len(m2)))
    print()

    # ---------- 规则3: 拉升>7% → 留(弱转强) ----------
    # 口径限定在当日: "留"的次日盈亏本地数据无偏不可得(见 load_path 注释)。
    # 但当日口径已足以回答"该不该被震出去" —— 看的是收盘涨停率, 不是收益。
    print('【规则3】盘中拉升>7% → 留(弱转强确认)   §6.3')
    for lab, key in (('5分钟内破7%', 't_up7_5'), ('任意时点破7%', 't_up7')):
        h3 = [x for x in rows if x[key]]
        n3 = [x for x in rows if not x[key]]
        if not h3:
            print('  %s: 0笔' % lab); continue
        print('  %s: 触发%d笔(%.0f%%) | 收盘涨停率 %.0f%% vs 未触发 %.0f%%' % (
            lab, len(h3), 100 * len(h3) / len(rows),
            100 * sum(1 for x in h3 if x['limit_up']) / len(h3),
            100 * sum(1 for x in n3 if x['limit_up']) / len(n3) if n3 else 0))
        s3 = seg(h3, 'ret_up7_close')
        print('     触发价→收盘 %d笔 均%+.2f%% (已涨7%%后再涨空间有限, 该列仅供参考)' % (s3[0], s3[1]))
        print('     未触发组 开盘→收盘 均%+.2f%%' % (seg(n3, 'ret_open_close')[1],))
    print()

    # ---------- 规则4: 高开档次 ----------
    print('【规则4】竞价gap分档 (§6.1 不足5%高开=第一卖点)')
    print('  %-12s %6s %14s %12s %10s' % ('gap档', '笔数', '开盘→收盘', '收盘涨停率', '破0%率'))
    for lab, lo, hi in (('<0 低开', -99, 0), ('0-5%', 0, 5), ('5-8%', 5, 8),
                        ('8-10%', 8, 10), ('>=10% 一字', 10, 999)):
        g = [x for x in rows if lo <= x['gap'] < hi]
        if not g:
            continue
        print('  %-12s %6d %13.2f%% %11.0f%% %9.0f%%' % (
            lab, len(g), seg(g, 'ret_open_close')[1],
            100 * sum(1 for x in g if x['limit_up']) / len(g),
            100 * sum(1 for x in g if x['t_break0']) / len(g)))
    print()

    # ---------- 规则5: 控制 gap 后的盘中规则增量 ----------
    # 规则1/2 的原始统计混入了 gap 分布差异 —— 低开票开局就在 0% 下方 "破0%" 必然触发,
    # 所以那条规则在竞价时已可知, 不是盘中信号。必须控制 gap 再看剩余增量。
    print('=' * 78)
    print('【规则5】控制 gap 后的盘中规则增量   ← 关键: 判定"盘中"二字的真实含量')
    print('=' * 78)
    print('  在 gap 同档内比较触发/未触发, 才是盘中规则本身的边际信息')
    print()
    print('  (a) 高开后盘中跌破0%  vs  高开且全天不破0%')
    print('  %-10s %-22s %-22s' % ('gap档', '跌破0%(n/后续%/涨停%)', '未跌破(n/开盘→收%/涨停%)'))
    for lab, lo, hi in (('0-3%', 0, 3), ('3-5%', 3, 5), ('5-8%', 5, 8)):
        g = [x for x in rows if lo <= x['gap'] < hi]
        if not g:
            continue
        a = [x for x in g if x['t_break0']]
        b = [x for x in g if not x['t_break0']]
        sa = seg(a, 'ret_break0_close')
        sb = seg(b, 'ret_open_close')
        print('  %-10s %-22s %-22s' % (
            lab,
            '—' if not sa else '%3d / %+6.2f%% / %3.0f%%' % (
                sa[0], sa[1], 100 * sum(1 for x in a if x['limit_up']) / len(a)),
            '—' if not sb else '%3d / %+6.2f%% / %3.0f%%' % (
                sb[0], sb[1], 100 * sum(1 for x in b if x['limit_up']) / len(b))))
    print('  ↑ 若两列"涨停%"差距大 → 该规则有真信息; 若接近 → 只是 gap 的影子')
    print()

    print('  (b) 5分钟内破7%  vs  未破7%')
    print('  %-10s %-22s %-22s' % ('gap档', '破7%(n/触发后续%/涨停%)', '未破7%(n/开盘→收%/涨停%)'))
    for lab, lo, hi in (('<0', -99, 0), ('0-3%', 0, 3), ('3-5%', 3, 5), ('5-8%', 5, 8)):
        g = [x for x in rows if lo <= x['gap'] < hi]
        if not g:
            continue
        a = [x for x in g if x['t_up7_5']]
        b = [x for x in g if not x['t_up7_5']]
        sa = seg(a, 'ret_up7_close') if a else None
        sb = seg(b, 'ret_open_close') if b else None
        print('  %-10s %-22s %-22s' % (
            lab,
            '—' if not sa else '%3d / %+6.2f%% / %3.0f%%' % (
                sa[0], sa[1], 100 * sum(1 for x in a if x['limit_up']) / len(a)),
            '—' if not sb else '%3d / %+6.2f%% / %3.0f%%' % (
                sb[0], sb[1], 100 * sum(1 for x in b if x['limit_up']) / len(b))))
    print()

    # ---------- 规则6: 破VWAP 的"有效性"变体 ----------
    # 原式"触及即走"触发率98% → 无区分度。A 原意应是"有效跌破"(跌破后不收回),
    # 此处试三种加强版, 看加强到什么程度才有信息量。
    print('  (c) 破分时均线的"有效性"变体  —— 仅在**高开(gap>=0)**样本内测')
    print('      原式的 94~98%% 触发率大半来自低开票(开局就在均线下方), 不控制 gap 会误判')
    print('  %-24s %8s %14s %12s %10s' % ('变体', '触发率', '触发组开盘→收', '触发组涨停率', '未触发组'))
    hi_rows = [x for x in rows if x['gap'] >= 0]
    print('  (高开子样本 n=%d)' % len(hi_rows))
    for lab, need in (('触及即走(原式)', 1), ('连续3分钟在线下', 3),
                      ('连续5分钟在线下', 5), ('连续10分钟在线下', 10),
                      ('连续20分钟在线下', 20)):
        h, n = [], []
        for x in hi_rows:
            bars = x.get('_bars')
            if not bars:
                continue
            run = mx = 0
            cum_pv = cum_v = 0.0
            for b in bars:
                o, hi_, lo_, c, v = (float(b['o']), float(b['h']), float(b['l']),
                                     float(b['c']), float(b['v']))
                vw = (cum_pv / cum_v) if cum_v > 0 else o
                run = run + 1 if (cum_v > 0 and c < vw) else 0
                mx = max(mx, run)
                cum_pv += ((hi_ + lo_ + c) / 3.0) * v
                cum_v += v
            (h if mx >= need else n).append(x)
        if not h or not n:
            continue
        sh, sn = seg(h, 'ret_open_close'), seg(n, 'ret_open_close')
        print('  %-24s %7.0f%% %13.2f%% %11.0f%% %9.2f%%' % (
            lab, 100 * len(h) / (len(h) + len(n)), sh[1],
            100 * sum(1 for x in h if x['limit_up']) / len(h), sn[1]))
    print()

    # ---------- 规则7: 跨期对照 ----------
    # 用户定死的纪律: 新因子必须附训练段/检验段对比, 检验段幅度打 6-7 折。
    # 14 个交易日太短, 此处只作**方向一致性**检验, 不看幅度。
    print('=' * 78)
    print('【规则7】跨期方向一致性 (训练 09-02~09-11 / 检验 09-14~09-22)')
    print('=' * 78)
    print('  %-26s %-18s %-18s %s' % ('指标', '训练段(涨停率)', '检验段(涨停率)', '方向'))
    TR, TE = ('2026-09-02', '2026-09-11'), ('2026-09-14', '2026-09-22')

    def rate(rs, lo, hi, f):
        g = [x for x in rs if lo <= x['date'] <= hi and f(x)]
        return (100 * sum(1 for x in g if x['limit_up']) / len(g), len(g)) if g else (None, 0)

    checks = [
        ('破0%(全样本)', lambda x: x['t_break0'], lambda x: not x['t_break0']),
        ('破0%(gap0-5%内)', lambda x: x['t_break0'] and 0 <= x['gap'] < 5,
         lambda x: (not x['t_break0']) and 0 <= x['gap'] < 5),
        ('5分钟内破7%', lambda x: x['t_up7_5'], lambda x: not x['t_up7_5']),
        ('5分钟内破7%(gap0-5%)', lambda x: x['t_up7_5'] and 0 <= x['gap'] < 5,
         lambda x: (not x['t_up7_5']) and 0 <= x['gap'] < 5),
    ]
    for lab, on, off in checks:
        line, d = [lab], []
        for seg_lo, seg_hi in (TR, TE):
            a, na = rate(rows, seg_lo, seg_hi, on)
            b, nb = rate(rows, seg_lo, seg_hi, off)
            line.append('—' if a is None or b is None else '%3.0f%%(%d) vs %3.0f%%(%d)' % (a, na, b, nb))
            # 一致性 = 两段"触发组−未触发组"的**符号相同**(方向可正可负, 不预设)
            d.append(None if (a is None or b is None) else (a - b))
        if d[0] is None or d[1] is None:
            verdict = '—'
        elif d[0] * d[1] > 0:
            verdict = '✅一致(触发组%s)' % ('高' if d[0] > 0 else '低')
        else:
            verdict = '⚠不一致'
        print('  %-26s %-18s %-18s %s' % (line[0], line[1], line[2], verdict))
    print()
    print('注: 样本仅 %d 个交易日, 且覆盖率 56~90%%(非全体); 结论需按此打折' % len(set(x['date'] for x in rows)))
