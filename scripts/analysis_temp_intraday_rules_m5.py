# -*- coding: utf-8 -*-
"""A 盘中卖出规则验证台 · 5分钟全历史版 (2026-09-23)

与 analysis_temp_intraday_rules.py(1分钟版, 窗口 09-02~09-22) 的关系:
  同一批规则, 独立数据源独立窗口 —— 两版同向 = 强证据, 分歧 = 需查因。
  1分钟版优势在触发时刻精度; 本版优势在**窗口长 7 倍**且 **T+1 列无偏**。

为什么能用 T+1 了(1分钟版做不到):
  1分钟版被迫弃用 T+1 列 —— 彼时 T+1 只能取自 data/kline_data, 而 K 线库只更新
  「当日涨停池 + 持仓」, 覆盖率 43% 且缺的恰是"T日没涨停"的票, 算出的
  「5分钟内破7% → T+1收盘 +5.23%/67%胜」是幸存者偏差。
  本版**不碰 K 线库**: 新浪 5 分钟一次给 5001 根(≈104 交易日), T-1 / T / T+1 三天
  全在同一份序列里 —— 昨收取 T 日前一根的 close, T+1 收取 T+1 日最后一根的 close,
  票停牌就自然缺 bar。口径自洽, 与"这票有没有涨停"无关, 偏差来源被移除。

数据: data/m5_research/{code}.json  (脚本 scripts/daily/fetch_m5_pool.py)
      [[time, open, close, high, low, volume, amount], ...]  time='YYYY-MM-DD HH:MM'
      ⚠ 新浪 volume 单位=股(东财=手), 本脚本只用价格, 不受影响。

⚠ 5分钟口径的固有近似(必须知道才能解读数字):
  · 第一根 bar 标注 09:35, 覆盖 09:31~09:35 —— 即 A 所说的"开盘后5分钟", 恰好对齐 ✓
  · 破0% / 破分时均线的**触发时刻精度降到 5 分钟**(1分钟版是 1 分钟)
  · 同一根 bar 内若既下探破0% 又上冲破7%(振幅>7%的巨震), 无法再分先后 → 单列「同bar双触」

用法: python scripts/analysis_temp_intraday_rules_m5.py
      python scripts/analysis_temp_intraday_rules_m5.py --lo 2026-09-01   # 只跑子窗口
"""
import os, sys, io, json, argparse, collections, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

M5_DIR = 'data/m5_research'
POOL_DIRS = ('data/zt_pool_history_ths', 'data/zt_pool')   # 后者优先(格式新)
DEFAULT_LO, DEFAULT_HI = '2026-04-24', '2026-09-22'
MIN_BARS = 40           # 当日 5 分钟 bar 少于此视为数据不全
T1_LAST = '15:00'


def rd(p):
    for enc in ('utf-8', 'gbk'):
        try:
            raw = json.load(open(p, encoding=enc))
            return raw.get('data', raw) if isinstance(raw, dict) else raw
        except (UnicodeDecodeError, ValueError):
            continue
    return None


# ---------- 池 ----------
def load_pools():
    """合并两个池目录 → {date: [{code,name,...}, ...]}, 同 zt_pool 优先"""
    import re
    out = {}
    for src in POOL_DIRS:
        if not os.path.isdir(src):
            continue
        for f in sorted(os.listdir(src)):
            if not f.endswith('.json') or f == 'stock_index.json':
                continue
            m = re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})\.json$', f)
            if not m:
                continue
            d = '%s-%s-%s' % m.groups()
            raw = rd(os.path.join(src, f))
            rows = raw if isinstance(raw, list) else (raw or {}).get('stocks', [])
            if rows:
                out.setdefault(d, []).extend(rows)
    return out


# ---------- 行情 ----------
_m5 = {}


def m5_by_day(code):
    """→ {date: [bars...]} 升序; bars=[time,o,c,h,l,v]"""
    if code in _m5:
        return _m5[code]
    p = os.path.join(M5_DIR, code + '.json')
    d = rd(p) if os.path.exists(p) else None
    days = collections.defaultdict(list)
    for r in (d or {}).get('m5') or []:
        t = str(r[0])
        days[t[:10]].append([t, float(r[1]), float(r[2]), float(r[3]),
                             float(r[4]), float(r[5])])   # [time,o,c,h,l,v]
    for k in days:
        days[k].sort(key=lambda b: b[0])
    _m5[code] = days
    return days


MAX_GAP_DAYS = 4       # 昨收/T+1 与 T 的最大自然日间隔(周五→周一=3天, 留1天余量)


def _span(d1, d2):
    from datetime import date
    return (date(*map(int, d2.split('-'))) - date(*map(int, d1.split('-')))).days


def analyze(bars, prev_close, next_bars=None):
    """bars=T日5分钟; prev_close=自带昨收; next_bars=T+1日(可None)"""
    if len(bars) < MIN_BARS or prev_close <= 0:
        return None
    open_px = bars[0][1]
    close_px = bars[-1][2]
    gap = (open_px - prev_close) / prev_close * 100
    chg = (close_px - prev_close) / prev_close * 100
    thr7 = prev_close * 1.07
    first_t = bars[0][0][11:16]

    r = dict(open=open_px, close=close_px, prev_close=prev_close, gap=gap, chg=chg,
             limit_up=chg >= 9.8, first_bar=first_t,
             ret_open_close=(close_px - open_px) / open_px * 100,
             high_pct=(max(b[3] for b in bars) - prev_close) / prev_close * 100,
             low_pct=(min(b[4] for b in bars) - prev_close) / prev_close * 100)

    cum_pv = cum_v = 0.0
    t0 = tv = t7 = t7_5 = None
    px_vw = None
    for t, o, c, h, l, v in bars:
        hm = t[11:16]
        vw = (cum_pv / cum_v) if cum_v > 0 else o          # 截至上一根
        if t0 is None and l <= prev_close:
            t0 = hm
        if tv is None and cum_v > 0 and l <= vw:
            tv, px_vw = hm, vw
        if t7 is None and h >= thr7:
            t7 = hm
            # 严格按钟点判"5分钟内" —— 不可退化成"取第一根": 若该票开盘即停牌,
            # 首根 bar 会晚于 09:35, 那样会把盘中突破误记成开盘5分钟内。
            if t7_5 is None and hm <= '09:35':
                t7_5 = hm
        cum_pv += ((h + l + c) / 3.0) * v
        cum_v += v

    r.update(t_break0=t0, t_vwap=tv, t_up7=t7, t_up7_5=t7_5, _bars=bars)
    # 同一根 bar 内既破0%又破7% → 5分钟粒度无法分先后
    r['both'] = bool(t0 and t7_5 and t0 == t7_5)

    # 触发价 → 当日收盘 / T+1收盘(无偏)
    nxt_close = next_bars[-1][2] if next_bars else None
    r['ret_open_next'] = ((nxt_close - open_px) / open_px * 100) if nxt_close else None
    for tag, t, px in (('break0', t0, prev_close), ('vwap', tv, px_vw),
                       ('up7_5', t7_5, thr7), ('up7', t7, thr7)):
        r['ret_%s_close' % tag] = ((close_px - px) / px * 100) if (t and px) else None
        r['ret_%s_next' % tag] = ((nxt_close - px) / px * 100) if (t and px and nxt_close) else None
    return r


def seg(rows, key):
    v = [x[key] for x in rows if x.get(key) is not None]
    if not v:
        return None
    return len(v), statistics.mean(v), sum(1 for y in v if y > 0) / len(v) * 100


def lu(rows):
    return (100 * sum(1 for x in rows if x['limit_up']) / len(rows)) if rows else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lo', default=DEFAULT_LO)
    ap.add_argument('--hi', default=DEFAULT_HI)
    args = ap.parse_args()

    pools = load_pools()
    DAYS = sorted(pools)

    # 按【票】分组而非按日: 一只票要参与它出现在 T-1 池的每一个 T。
    # 若按日循环就会反复重读同一文件, 若全局缓存则 1986只×5001根 会 OOM
    # (纯 Python list 约 1.5GB) —— 分组后每只票读完即用即弃, 内存峰值=单票。
    tasks = collections.defaultdict(list)
    for i, T in enumerate(DAYS):
        if not (args.lo <= T <= args.hi) or i == 0:
            continue
        for s in pools[DAYS[i - 1]]:
            c = str(s.get('code', '')).zfill(6)
            if len(c) != 6 or c.startswith(('300', '301', '688', '8', '9')):
                continue
            tasks[c].append((T, s.get('name', ''),
                             s.get('limit_days', s.get('high_days', '?'))))

    rows, no_m5, no_prev, empty, bad_gap = [], 0, 0, 0, 0
    used_days = set()
    for c, items in tasks.items():
        days = m5_by_day(c)
        if not days:
            no_m5 += len(items)
            continue
        dd = sorted(days)
        for T, name, cons in items:
            if T not in days:
                no_m5 += 1
                continue
            pd = [d for d in dd if d < T]
            # 昨收必须来自**邻近交易日**: 若该票中间停牌, pd[-1] 会是几天前,
            # 用它的收盘算 gap 等于把停牌前价格当昨收 → gap 失真。除权同理。
            if not pd or _span(pd[-1], T) > MAX_GAP_DAYS:
                no_prev += 1
                continue
            nxt = [d for d in dd if d > T]
            nx = nxt[0] if nxt else None
            if nx and _span(T, nx) > MAX_GAP_DAYS:
                nx = None                      # T+1 停牌 → 不给"留到次日"的数
            r = analyze(days[T], days[pd[-1]][-1][2], days[nx] if nx else None)
            if not r:
                empty += 1
                continue
            if abs(r['gap']) > 11.5:           # 超出任何 A 股涨跌幅 → 数据异常
                bad_gap += 1
                continue
            r.update(code=c, date=T, name=name, cons=cons)
            rows.append(r)
            used_days.add(T)
        _m5.pop(c, None)                       # 显式释放

    print()
    print('=' * 90)
    print('样本: %d 个(股票×交易日) | 窗口 %s ~ %s | 覆盖 %d 个交易日'
          % (len(rows), args.lo, args.hi, len(used_days)))
    print('抓取缺口: 无当日5分钟 %d 票次 | 昨收非邻近交易日(停牌/新股) %d | 当日bar不足 %d'
          % (no_m5, no_prev, empty))
    print('数据异常剔除: |gap|>11.5%%(除权/脏数据) %d 票次' % bad_gap)
    print('=' * 90)
    if not rows:
        print('无样本 — 先跑 python scripts/daily/fetch_m5_pool.py')
        return

    fb = collections.Counter(x['first_bar'] for x in rows)
    print('当日首根5分钟bar时点(应为 09:35, 验证"开盘后5分钟"口径): %s'
          % dict(sorted(fb.most_common(4))))
    b = seg(rows, 'ret_open_close')
    print('基线: 开盘→收盘 %d笔 均%+.2f%% 胜%.0f%% | 当日涨停率 %.1f%%'
          % (b[0], b[1], b[2], lu(rows)))
    print()

    # ---------- 规则1 ----------
    print('【规则1】破0%(跌破昨收) → 走   §7.1/§6.3')
    hit = [x for x in rows if x['t_break0']]
    mis = [x for x in rows if not x['t_break0']]
    s = seg(hit, 'ret_break0_close')
    print('  触发 %d笔(%.0f%%) | 未触发 %d笔' % (len(hit), 100 * len(hit) / len(rows), len(mis)))
    print('  ★ 触发价→当日收盘: %d笔 均%+.2f%% 胜%.0f%%   ← 为负 = 卖对了' % s)
    print('  ★ 触发价→T+1收盘: %s' % _fmt(seg(hit, 'ret_break0_next')))
    print('  触发组收盘涨停率 %.1f%% | 未触发组 %.1f%% (差 %+.1fpt)'
          % (lu(hit), lu(mis), lu(hit) - lu(mis)))
    tk = collections.Counter((x['t_break0'] <= '09:35' and '开盘首5min') or
                             (x['t_break0'] <= '10:00' and '5-30min') or
                             (x['t_break0'] <= '11:30' and '30-120min') or '午后' for x in hit)
    print('  触发时点(5分钟粒度): %s' % dict(tk))
    print()

    # ---------- 规则2 ----------
    print('【规则2】破分时均线(VWAP) → 走   §7.1')
    h2 = [x for x in rows if x['t_vwap']]
    print('  触发 %d笔(%.0f%%)  ← 接近"全体"即无区分度'
          % (len(h2), 100 * len(h2) / len(rows)))
    print('  触发价→当日收盘: %s | 到T+1收盘: %s'
          % (_fmt(seg(h2, 'ret_vwap_close')), _fmt(seg(h2, 'ret_vwap_next'))))
    print()

    # ---------- 规则3 ----------
    print('【规则3】盘中拉升>7% → 留(弱转强确认)   §6.3')
    for lab, key in (('5分钟内破7%(09:35前)', 't_up7_5'), ('任意时点破7%', 't_up7')):
        h3 = [x for x in rows if x[key]]
        n3 = [x for x in rows if not x[key]]
        if not h3:
            print('  %s: 0笔' % lab); continue
        print('  %s: 触发%d笔(%.0f%%) | 收盘涨停率 %.0f%% vs 未触发 %.0f%% (差 %+.1fpt)'
              % (lab, len(h3), 100 * len(h3) / len(rows), lu(h3), lu(n3), lu(h3) - lu(n3)))
        print('     ★ 触发价→T+1收盘: %s   ← 无偏列(1分钟版做不到)'
              % _fmt(seg(h3, 'ret_%s_next' % key[2:])))
        print('     未触发组 开盘→收 %s' % _fmt(seg(n3, 'ret_open_close')))
    dup = [x for x in rows if x['both']]
    print('  ⚠ 同bar双触(既破0%%又破7%%, 5分钟粒度无法分先后): %d笔(%.1f%%)'
          % (len(dup), 100 * len(dup) / len(rows)))
    print()

    # ---------- 规则4 ----------
    print('【规则4】竞价gap分档   §6.1(不足5%高开=第一卖点)')
    print('  %-12s %6s %14s %12s %10s %14s' % ('gap档', '笔数', '开盘→收盘', '收盘涨停率', '破0%率', '破7%率(5min)'))
    for lab, lo, hi in (('<0 低开', -99, 0), ('0-5%', 0, 5), ('5-8%', 5, 8),
                        ('8-10%', 8, 10), ('>=10%', 10, 999)):
        g = [x for x in rows if lo <= x['gap'] < hi]
        if not g:
            continue
        print('  %-12s %6d %13.2f%% %11.0f%% %9.0f%% %13.0f%%' % (
            lab, len(g), seg(g, 'ret_open_close')[1], lu(g),
            100 * sum(1 for x in g if x['t_break0']) / len(g),
            100 * sum(1 for x in g if x['t_up7_5']) / len(g)))
    print()

    # ---------- 规则5: 控制 gap ----------
    print('=' * 90)
    print('【规则5】控制 gap 后的盘中规则增量   ← 判定"盘中"二字的真实含量')
    print('=' * 90)
    print('  (a) 高开后盘中跌破0%  vs  高开且全天不破0%')
    print('  %-10s %-26s %-26s' % ('gap档', '跌破0%(n/收盘涨停%)', '未跌破(n/开盘→收%/收盘涨停%)'))
    for lab, lo, hi in (('0-3%', 0, 3), ('3-5%', 3, 5), ('5-8%', 5, 8)):
        g = [x for x in rows if lo <= x['gap'] < hi]
        if not g:
            continue
        a = [x for x in g if x['t_break0']]
        b2 = [x for x in g if not x['t_break0']]
        print('  %-10s %-26s %-26s' % (
            lab,
            '—' if not a else '%3d / %3.0f%%' % (len(a), lu(a)),
            '—' if not b2 else '%3d / %+6.2f%% / %3.0f%%' % (
                len(b2), seg(b2, 'ret_open_close')[1], lu(b2))))
    print()
    print('  (b) 5分钟内破7%  vs  未破7%    ★ 含 T+1 收盘(无偏)')
    print('  %-10s %-30s %-30s' % ('gap档', '破7%(n/涨停%/触发→T+1)', '未破7%(n/涨停%/开盘→T+1)'))
    for lab, lo, hi in (('<0', -99, 0), ('0-3%', 0, 3), ('3-5%', 3, 5), ('5-8%', 5, 8)):
        g = [x for x in rows if lo <= x['gap'] < hi]
        if not g:
            continue
        a = [x for x in g if x['t_up7_5']]
        b2 = [x for x in g if not x['t_up7_5']]
        sa, sb = seg(a, 'ret_up7_5_next'), seg(b2, 'ret_open_close')
        print('  %-10s %-30s %-30s' % (
            lab,
            '—' if not a else '%3d / %3.0f%% / %s' % (
                len(a), lu(a), ('%+.2f%%' % sa[1]) if sa else '—'),
            '—' if not b2 else '%3d / %3.0f%% / %+6.2f%%' % (len(b2), lu(b2), sb[1])))
    print('  ↑ "触发→T+1" 用作"留"的代价/收益: 若触发组 T+1 明显更好 → 留是对的')
    print()

    # ---------- 规则6 ----------
    print('  (c) 破分时均线"有效性"变体  —— 仅高开(gap>=0)样本内')
    hi_rows = [x for x in rows if x['gap'] >= 0]
    print('  (高开子样本 n=%d)' % len(hi_rows))
    print('  %-22s %8s %16s %12s %14s' % ('变体', '触发率', '触发组开盘→收', '触发组涨停率', '未触发组开盘→收'))
    for lab, need in (('触及即走(原式)', 1), ('连续2根在线下', 2),
                      ('连续3根在线下', 3), ('连续6根在线下(30min)', 6),
                      ('连续12根在线下(1h)', 12)):
        h, n = [], []
        for x in hi_rows:
            bars = x.get('_bars')
            if not bars:
                continue
            run = mx = 0
            cum_pv = cum_v = 0.0
            for t, o, c, hi_, lo_, v in bars:
                vw = (cum_pv / cum_v) if cum_v > 0 else o
                run = run + 1 if (cum_v > 0 and c < vw) else 0
                mx = max(mx, run)
                cum_pv += ((hi_ + lo_ + c) / 3.0) * v
                cum_v += v
            (h if mx >= need else n).append(x)
        if not h or not n:
            continue
        print('  %-22s %7.0f%% %15.2f%% %11.0f%% %13.2f%%' % (
            lab, 100 * len(h) / (len(h) + len(n)), seg(h, 'ret_open_close')[1],
            lu(h), seg(n, 'ret_open_close')[1]))
    print()

    # ---------- 规则7 ----------
    print('=' * 90)
    print('【规则7】跨期方向一致性 (窗口对半切)')
    print('=' * 90)
    ds = sorted(used_days)
    mid = ds[len(ds) // 2]
    TR, TE = (ds[0], ds[len(ds) // 2 - 1]), (mid, ds[-1])
    print('  训练段 %s ~ %s (%d天) | 检验段 %s ~ %s (%d天)'
          % (TR[0], TR[1], len([d for d in ds if TR[0] <= d <= TR[1]]),
             TE[0], TE[1], len([d for d in ds if TE[0] <= d <= TE[1]])))
    print('  %-28s %-20s %-20s %s' % ('指标(触发组 vs 未触发组 的收盘涨停率)', '训练段', '检验段', '方向'))

    def rate(rs, lo, hi, f):
        g = [x for x in rs if lo <= x['date'] <= hi and f(x)]
        return (lu(g), len(g)) if g else (None, 0)

    checks = [
        ('破0% 全样本', lambda x: x['t_break0'], lambda x: not x['t_break0']),
        ('破0% gap0-5%内', lambda x: x['t_break0'] and 0 <= x['gap'] < 5,
         lambda x: (not x['t_break0']) and 0 <= x['gap'] < 5),
        ('5min破7% 全样本', lambda x: x['t_up7_5'], lambda x: not x['t_up7_5']),
        ('5min破7% gap0-5%', lambda x: x['t_up7_5'] and 0 <= x['gap'] < 5,
         lambda x: (not x['t_up7_5']) and 0 <= x['gap'] < 5),
        ('5min破7% gap5-8%', lambda x: x['t_up7_5'] and 5 <= x['gap'] < 8,
         lambda x: (not x['t_up7_5']) and 5 <= x['gap'] < 8),
    ]
    for lab, on, off in checks:
        cells, d = [], []
        for slo, shi in (TR, TE):
            a, na = rate(rows, slo, shi, on)
            b2, nb = rate(rows, slo, shi, off)
            cells.append('—' if a is None or b2 is None else '%3.0f%%(%d) vs %3.0f%%(%d)' % (a, na, b2, nb))
            d.append(None if (a is None or b2 is None) else (a - b2))
        v = ('—' if d[0] is None or d[1] is None else
             ('✅一致(触发组%s)' % ('高' if d[0] > 0 else '低') if d[0] * d[1] > 0 else '⚠反向'))
        print('  %-28s %-20s %-20s %s' % (lab, cells[0], cells[1], v))
    print()

    print('  T+1 收益跨期(触发价→T+1收盘, 均值):')
    print('  %-28s %-20s %-20s %s' % ('指标', '训练段', '检验段', '方向'))

    def mret(rs, lo, hi, f, key):
        s = seg([x for x in rs if lo <= x['date'] <= hi and f(x)], key)
        return (s[1], s[0]) if s else (None, 0)

    for lab, f, key in (
            ('5min破7% 触发→T+1', lambda x: x['t_up7_5'], 'ret_up7_5_next'),
            ('5min未破7% 开盘→T+1', lambda x: not x['t_up7_5'], 'ret_open_next')):
        cells, d = [], []
        for slo, shi in (TR, TE):
            m, n = mret(rows, slo, shi, f, key)
            cells.append('—' if m is None else '%+.2f%%(%d)' % (m, n))
            d.append(m)
        v = ('—' if None in d else ('✅一致' if d[0] * d[1] > 0 else '⚠反向'))
        print('  %-28s %-20s %-20s %s' % (lab, cells[0], cells[1], v))
    print()

    # ---------- 附: 逐段明细 ----------
    print('=' * 90)
    print('附: 逐段(12段) 关键指标')
    print('=' * 90)
    print('  %-22s %6s %9s %10s %11s %11s' % ('区间', '笔数', '涨停率', '破0%率', '5min破7%率', '日均涨停%'))
    step = max(1, len(ds) // 12)
    for i in range(0, len(ds), step):
        grp = ds[i:i + step]
        g = [x for x in rows if x['date'] in set(grp)]
        if not g:
            continue
        print('  %-22s %6d %8.0f%% %9.0f%% %10.0f%% %10.1f%%' % (
            '%s~%s' % (grp[0], grp[-1]), len(g), lu(g),
            100 * sum(1 for x in g if x['t_break0']) / len(g),
            100 * sum(1 for x in g if x['t_up7_5']) / len(g),
            100 * sum(1 for x in g if x['limit_up']) / len(g)))


def _fmt(s):
    return '—' if not s else '%d笔 均%+.2f%% 胜%.0f%%' % (s[0], s[1], s[2])


if __name__ == '__main__':
    main()
