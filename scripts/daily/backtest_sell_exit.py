# -*- coding: utf-8 -*-
"""
卖出规则近期有效性回测 (2026-09-02, 用户问题驱动)
- 回测1 (海鸥式): 断板+低开 → 开盘卖 vs 持有到收盘/T+1
- 回测2 (我爱我家式): 昨涨停+低开, 按T-1炸板次数分组验证烂板低开卖是否正确
- 回测3 (金牛式): 炸板票次日盘中"拉升>7%离场"近似 vs 收盘卖 vs T+1

口径: 全策略收益均以T日开盘价为基准(=0), 与引擎回测口径一致(开盘价买入近似)
数据: zt_pool_history_ths(2025-07-10~2026-08-19) + zt_pool(2026-07-24~今) + kline_data
涨停判定: T日池成员优先, 无池文件时用K线pct>=9.8%
"""
import json
import os
import sys
import glob
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(BASE, 'data')

# ---------- 数据加载 ----------
def load_calendar():
    d = json.load(open(os.path.join(DATA, 'trading_calendar.json'), encoding='utf-8'))
    dates = sorted(d['dates'])
    return dates

def _norm_date(d8):
    return f'{d8[:4]}-{d8[4:6]}-{d8[6:8]}'

def load_pools():
    """返回 {date('YYYY-MM-DD'): {'recs': {code: rec}, 'code_set': set}}"""
    pools = {}
    # 当前池 (优先, 有break_times)
    for f in glob.glob(os.path.join(DATA, 'zt_pool', '*.json')):
        date = _norm_date(os.path.basename(f)[:8])
        # 2026-09-03: 池文件写盘已改utf-8, 旧文件仍是gbk → 双编码兜底
        try:
            try:
                raw = json.load(open(f, encoding='utf-8'))
            except UnicodeDecodeError:
                raw = json.load(open(f, encoding='gbk'))
        except Exception:
            continue
        items = raw if isinstance(raw, list) else raw.get('stocks', raw.get('pool', []))
        recs = {}
        for x in items:
            if not isinstance(x, dict) or not x.get('code'):
                continue
            code = str(x['code']).zfill(6)
            recs[code] = {
                'code': code, 'name': x.get('name', ''),
                'days': x.get('limit_days', x.get('high_days')),
                'turnover': x.get('turnover', x.get('turnover_rate')),
                'break_times': x.get('break_times'),
            }
        pools[date] = {'recs': recs, 'code_set': set(recs.keys())}
    # 历史池 (ths, 无break_times), 重叠日期不覆盖
    for f in glob.glob(os.path.join(DATA, 'zt_pool_history_ths', '*.json')):
        date = _norm_date(os.path.basename(f)[:8])
        if date in pools:
            continue
        try:
            try:
                raw = json.load(open(f, encoding='utf-8'))
            except UnicodeDecodeError:
                raw = json.load(open(f, encoding='gbk', errors='replace'))
        except Exception:
            continue
        items = raw if isinstance(raw, list) else raw.get('stocks', raw.get('pool', []))
        recs = {}
        for x in items:
            if not isinstance(x, dict) or not x.get('code'):
                continue
            code = str(x['code']).zfill(6)
            recs[code] = {
                'code': code, 'name': x.get('name', ''),
                'days': x.get('high_days', x.get('limit_days')),
                'turnover': x.get('turnover_rate', x.get('turnover')),
                'break_times': None,
            }
        pools[date] = {'recs': recs, 'code_set': set(recs.keys())}
    return pools

_KLINE_CACHE = {}
def get_kline(code):
    """返回 {date: bar}, 仅保留2025-07后bar"""
    if code in _KLINE_CACHE:
        return _KLINE_CACHE[code]
    f = os.path.join(DATA, 'kline_data', f'{code}.json')
    if not os.path.exists(f):
        _KLINE_CACHE[code] = {}
        return {}
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception:
        _KLINE_CACHE[code] = {}
        return {}
    data = d.get('data', []) if isinstance(d, dict) else d
    bars = {}
    for b in data:
        if not isinstance(b, dict):
            continue
        dt = b.get('date', '')
        if dt >= '2025-06-01':
            bars[dt] = b
    _KLINE_CACHE[code] = bars
    return bars

# ---------- 样本构造 ----------
def build_samples(pools, cal):
    """返回 rows: [dict(T-1_date, code, days, turnover, break_times,
                     gap, ret_close, ret_t1_open, ret_t1_close, limit_T, bar_ok)]"""
    cal_set = set(cal)
    date_idx = {d: i for i, d in enumerate(cal)}
    rows = []
    for d in sorted(pools.keys()):
        if d not in date_idx:
            continue
        i = date_idx[d]
        if i + 1 >= len(cal):
            continue
        t = cal[i + 1]           # T日
        u = cal[i + 2] if i + 2 < len(cal) else None  # T+1日
        pool = pools[d]
        t_pool = pools.get(t)    # 可能无池文件
        for code in pool['code_set']:
            rec = pool['recs'][code]
            kb = get_kline(code)
            bar = kb.get(t)
            if not bar:
                continue
            bar_prev = kb.get(d)  # T-1日bar, 取昨收
            if not bar_prev:
                continue
            prev_close = float(bar_prev.get('close', 0))
            o, h, c = float(bar.get('open', 0)), float(bar.get('high', 0)), float(bar.get('close', 0))
            if prev_close <= 0 or o <= 0:
                continue
            gap = (o - prev_close) / prev_close * 100
            # 涨停判定: T日池优先, 否则K线pct
            if t_pool is not None:
                limit_T = code in t_pool['code_set']
            else:
                limit_T = float(bar.get('pct_change', 0)) >= 9.8
            row = {
                'prev_date': d, 'code': code, 'days': rec['days'],
                'turnover': rec['turnover'], 'break_times': rec['break_times'],
                'gap': gap, 'limit_T': limit_T,
                'ret_close': (c - o) / o * 100,
                'ret_t1_open': None, 'ret_t1_close': None,
            }
            if u:
                bar_u = kb.get(u)
                if bar_u:
                    uo, uc = float(bar_u.get('open', 0)), float(bar_u.get('close', 0))
                    if uo > 0:
                        row['ret_t1_open'] = (uo - o) / o * 100
                        row['ret_t1_close'] = (uc - o) / o * 100
            rows.append(row)
    return rows

def stat(rows, key=None, name=''):
    if key:
        rows = [r for r in rows if key(r)]
    n = len(rows)
    if n == 0:
        print(f'  {name}: 样本0, 跳过')
        return
    def avg(f):
        vals = [f(r) for r in rows if f(r) is not None]
        return sum(vals) / len(vals) if vals else float('nan')
    def win(f):
        vals = [f(r) for r in rows if f(r) is not None]
        return sum(1 for v in vals if v > 0) / len(vals) * 100 if vals else float('nan')
    print(f'  {name}: n={n} | 开盘卖0.0% | 收盘卖{avg(lambda r: r["ret_close"]):+.2f}%({win(lambda r: r["ret_close"]):.0f}%胜)'
          f' | T+1开{avg(lambda r: r["ret_t1_open"]):+.2f}% | T+1收{avg(lambda r: r["ret_t1_close"]):+.2f}%({win(lambda r: r["ret_t1_close"]):.0f}%胜)')

def main():
    cal = load_calendar()
    pools = load_pools()
    print(f'池文件: {len(pools)}个交易日 | 日历: {len(cal)}个交易日')
    rows = build_samples(pools, cal)
    print(f'有效样本: {len(rows)}条\n')

    # ===== 回测1: 断板+低开 (海鸥式) =====
    print('=' * 70)
    print('回测1: 断板+低开 — 开盘卖 vs 持有 (引擎规则: 断板gap<4%卖)')
    print('=' * 70)
    broken = [r for r in rows if not r['limit_T']]
    print(f'[断板样本总数] n={len(broken)}')
    print('-- 按gap分桶 (断板) --')
    stat(broken, lambda r: r['gap'] <= -5, '深水低开 gap<=-5%')
    stat(broken, lambda r: -5 < r['gap'] <= -4, '中低开 -5%~-4%')
    stat(broken, lambda r: -4 < r['gap'] < 0, '浅低开 -4%~0% (海鸥-2.3%落此)')
    stat(broken, lambda r: 0 <= r['gap'] < 4, '平开/小高开 0~4% (规则也卖)')
    stat(broken, lambda r: r['gap'] >= 4, '高开 >=4% (规则持有)')
    print('-- 断板浅低开 阶段检测 --')
    stat([r for r in broken if -4 < r['gap'] < 0 and r['prev_date'] < '2026-01-01'], name='2025年 (7-12月)')
    stat([r for r in broken if -4 < r['gap'] < 0 and '2026-01-01' <= r['prev_date'] < '2026-08-01'], name='2026上半年')
    stat([r for r in broken if -4 < r['gap'] < 0 and r['prev_date'] >= '2026-08-01'], name='2026-08起 (近期)')
    print('-- 断板深水低开 阶段检测 --')
    stat([r for r in broken if r['gap'] <= -5 and r['prev_date'] < '2026-08-01'], name='2026-08前')
    stat([r for r in broken if r['gap'] <= -5 and r['prev_date'] >= '2026-08-01'], name='2026-08起 (近期)')

    # ===== 回测2: 昨涨停+低开 按炸板次数分组 (我爱我家式) =====
    print()
    print('=' * 70)
    print('回测2: 昨涨停+今低开 — 按T-1炸板次数分组 (引擎: 低开=竞价卖)')
    print('=' * 70)
    low = [r for r in rows if r['gap'] < 0 and r['break_times'] is not None]
    print(f'[低开样本总数(有炸板字段, 07-24起)] n={len(low)}')
    stat([r for r in low if r['break_times'] == 0], name='健康板 炸0次')
    stat([r for r in low if 1 <= r['break_times'] <= 2], name='轻烂板 炸1-2次')
    stat([r for r in low if r['break_times'] >= 3], name='烂板 炸>=3次 (我爱我家炸6)')
    print('-- 烂板组按gap细分 --')
    stat([r for r in low if r['break_times'] >= 3 and r['gap'] <= -5], name='烂板+深水低开<=-5%')
    stat([r for r in low if r['break_times'] >= 3 and r['gap'] > -5], name='烂板+浅低开>-5%')
    print('-- 健康板组按gap细分 --')
    stat([r for r in low if r['break_times'] == 0 and r['gap'] <= -5], name='健康板+深水低开<=-5%')
    stat([r for r in low if r['break_times'] == 0 and r['gap'] > -5], name='健康板+浅低开>-5%')

    # ===== 回测3: 炸板票次日盘中拉升近似 (金牛式) =====
    print()
    print('=' * 70)
    print('回测3: 炸板票T+1 盘中拉升离场近似 (金牛式: 弱转强拉升>7%卖)')
    print('=' * 70)
    zb = [r for r in rows if r['break_times'] is not None and r['break_times'] >= 1]
    print(f'[炸板票样本] n={len(zb)}')
    # 近似: 若T日high>=open*1.07 → 卖open*1.07; 否则收盘卖
    # 需要high字段 → 重新从K线取
    cal_set = set(cal)
    date_idx = {d: i for i, d in enumerate(cal)}
    sim = []
    for r in zb:
        d, code = r['prev_date'], r['code']
        if d not in date_idx or date_idx[d] + 1 >= len(cal):
            continue
        t = cal[date_idx[d] + 1]
        kb = get_kline(code)
        bar = kb.get(t)
        if not bar:
            continue
        o, h = float(bar['open']), float(bar['high'])
        if o <= 0:
            continue
        r['ret_sell7'] = 7.0 if h >= o * 1.07 else r['ret_close']
        r['ret_sell5'] = 5.0 if h >= o * 1.05 else r['ret_close']
    def avg(f, rows_):
        vals = [f(r) for r in rows_ if f(r) is not None]
        return sum(vals) / len(vals) if vals else float('nan')
    def win(f, rows_):
        vals = [f(r) for r in rows_ if f(r) is not None]
        return sum(1 for v in vals if v > 0) / len(vals) * 100 if vals else float('nan')
    for name, sub in [('全部炸板票', zb), ('炸板+低开', [r for r in zb if r['gap'] < 0]), ('炸板+平开高开', [r for r in zb if r['gap'] >= 0])]:
        print(f'  {name}: n={len(sub)} | 拉升7%卖{avg(lambda r: r.get("ret_sell7"), sub):+.2f}%'
              f'({win(lambda r: r.get("ret_sell7"), sub):.0f}%胜) | 拉升5%卖{avg(lambda r: r.get("ret_sell5"), sub):+.2f}%'
              f' | 收盘卖{avg(lambda r: r["ret_close"], sub):+.2f}% | T+1收{avg(lambda r: r["ret_t1_close"], sub):+.2f}%'
              f'({win(lambda r: r["ret_t1_close"], sub):.0f}%胜)')

    # ===== 附加: 昨涨停+低开 全样本(含当日涨停) =====
    print()
    print('=' * 70)
    print('回测4(附加): 昨涨停+今低开全样本(含当日涨停的) — 开盘卖机会成本')
    print('=' * 70)
    stat([r for r in rows if r['gap'] < 0], name='全部低开(竞价不知道是否涨停)')
    stat([r for r in rows if r['gap'] < 0 and r['limit_T']], name='其中当日涨停的(开盘卖=卖飞)')
    stat([r for r in rows if r['gap'] < 0 and not r['limit_T']], name='其中当日未涨停的')

# ---------- 盘后月度跟踪 (Step 8.6, 2026-09-02) ----------
def watch_summary():
    """盘后跟踪: 断板浅低开/烂板低开 持有vs卖 月度序列, 存档 logs/sell_rule_watch.json
    结论口径: 开盘卖=0基准, 收盘卖/T+1收盘为正说明持有占优"""
    cal = load_calendar()
    pools = load_pools()
    rows = build_samples(pools, cal)
    broken = [r for r in rows if not r['limit_T']]
    shallow = [r for r in broken if -4 < r['gap'] < 0]
    deep = [r for r in broken if r['gap'] <= -5]
    rot = [r for r in rows if r['gap'] < 0 and r['break_times'] is not None and r['break_times'] >= 3]

    def avg(rs, key):
        vals = [r[key] for r in rs if r[key] is not None]
        return sum(vals) / len(vals) if vals else None

    print('\n[Step 8.6] 卖点规则月度跟踪 (断板浅低开-4%~0%, 开盘卖=0基准)')
    by_month = defaultdict(list)
    for r in shallow:
        by_month[r['prev_date'][:7]].append(r)
    recent_hold_win = 0
    total_checked = 0
    for m in sorted(by_month)[-12:]:
        sub = by_month[m]
        n = len(sub)
        if n == 0:
            continue
        c, t1 = avg(sub, 'ret_close'), avg(sub, 'ret_t1_close')
        if n >= 10:
            total_checked += 1
            if (c or 0) > 0:
                recent_hold_win += 1
        print(f'  {m}: n={n:4d} | 开盘卖0.0% | 收盘卖{c:+.2f}% | T+1收{t1:+.2f}%'
              f'{"  ⚠持有占优" if n >= 10 and (c or 0) > 0 and (t1 or 0) > 0 else ""}')
    print(f'  烂板(炸>=3)+低开 累计: n={len(rot)} | 开盘卖0.0% | 收盘卖{avg(rot, "ret_close") or 0:+.2f}% | T+1收{avg(rot, "ret_t1_close") or 0:+.2f}%')
    print(f'  断板深水低开(<=-5%, 引擎等自救分支) 累计: n={len(deep)} | 收盘卖{avg(deep, "ret_close") or 0:+.2f}%')
    if total_checked >= 2 and recent_hold_win == total_checked:
        print('  ⚠⚠ 连续月份持有占优, 建议启动规则修订评估 (数据裁决前仍需更多样本)')
    else:
        print('  ✓ 开盘卖规则维持 (持有未连续占优)')
    # 存档
    out = os.path.join(BASE, 'logs', 'sell_rule_watch.json')
    hist = []
    if os.path.exists(out):
        try:
            hist = json.load(open(out, encoding='utf-8'))
        except Exception:
            hist = []
    today = max(pools.keys())
    hist.append({
        'date': today,
        'shallow_months': {m: {'n': len(by_month[m]), 'close_ret': round(avg(by_month[m], 'ret_close'), 2) if avg(by_month[m], 'ret_close') is not None else None, 't1_ret': round(avg(by_month[m], 'ret_t1_close'), 2) if avg(by_month[m], 'ret_t1_close') is not None else None} for m in sorted(by_month)[-12:]},
        'rot_low': {'n': len(rot), 'close_ret': round(avg(rot, 'ret_close'), 2) if avg(rot, 'ret_close') is not None else None, 't1_ret': round(avg(rot, 'ret_t1_close'), 2) if avg(rot, 'ret_t1_close') is not None else None},
        'deep_low': {'n': len(deep), 'close_ret': round(avg(deep, 'ret_close'), 2) if avg(deep, 'ret_close') is not None else None},
    })
    json.dump(hist, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--watch':
        watch_summary()
    else:
        main()
