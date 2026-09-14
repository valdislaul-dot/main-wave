# -*- coding: utf-8 -*-
"""临时分析: A的77笔实盘 × 温度分档 交叉 + 温度开关模拟 (2026-09-07)
任务1: 从 zt_pool_history_ths 重建298天每日涨停数/最高板序列
任务2: A的77笔交易按温度分档统计盈亏/胜率/大赢单分布
任务3: 模拟"温度开关套在A身上"对收益的影响
只读数据, 不写回任何配置。
"""
import json, re, os, sys
sys.stdout.reconfigure(encoding='utf-8')

HIST_DIR = 'data/zt_pool_history_ths'

# ---------- 任务1: 重建每日涨停数/最高板 ----------
def parse_high_days(hd):
    m = re.search(r'(\d+)板', str(hd))
    return int(m.group(1)) if m else 1

def rebuild_series():
    rows = {}
    for fn in sorted(os.listdir(HIST_DIR)):
        if not fn.endswith('.json'):
            continue
        date = fn.replace('.json', '')  # YYYYMMDD
        try:
            with open(os.path.join(HIST_DIR, fn), encoding='utf-8') as f:
                pool = json.load(f)
        except Exception as e:
            print(f'  skip {fn}: {e}')
            continue
        if not isinstance(pool, list):
            continue
        cnt = len(pool)
        max_board = max((parse_high_days(p.get('high_days')) for p in pool), default=0)
        # 连板分布(1板/2板/3板+)
        b1 = sum(1 for p in pool if parse_high_days(p.get('high_days')) == 1)
        b2 = sum(1 for p in pool if parse_high_days(p.get('high_days')) == 2)
        b3p = cnt - b1 - b2
        rows[date] = {'cnt': cnt, 'max_board': max_board, 'b1': b1, 'b2': b2, 'b3p': b3p}
    return rows

rows = rebuild_series()
dates = sorted(rows.keys())
print(f'任务1: 重建 {len(dates)} 天序列 ({dates[0]} ~ {dates[-1]})')

# ---------- 温度分档(当前体系) ----------
def temp_tier(d_prev, d_prev2=None, me_latest=None):
    """T日决策: d_prev=T-1涨停数据, d_prev2=T-2, me_latest=最新可见赚效
    返回 (档位仓位pct, 说明)。只模拟分档+骤降防线+赚效降档, 竞价二次确认无数据。
    """
    r1, r2 = rows.get(d_prev), rows.get(d_prev2) if d_prev2 else None
    if not r1:
        return None, 'no data'
    cnt, mb = r1['cnt'], r1['max_board']
    # 极弱
    if cnt < 40 or mb <= 2:
        # 升温日例外: T-1涨停数 > T-2涨停数 且 T-1不是极弱(这里就是极弱档判断升温)
        warming = r2 and cnt > r2['cnt']
        return (50, '极弱升温例外') if warming else (0, '极弱空仓')
    pct = min(100, 10 * (cnt // 10))  # 40-49→40 ... ≥100→100
    note = f'{cnt}只/最高{mb}板'
    # 降档防线(只降一次)
    downgraded = False
    if r2:
        drop = (r2['cnt'] - cnt) / r2['cnt'] if r2['cnt'] else 0
        mb_drop = r2['max_board'] - mb
        if drop >= 0.30 or mb_drop >= 2:
            pct -= 10
            downgraded = True
            note += f'|骤降防线(降幅{drop:.0%}/{mb_drop}级)'
    if me_latest is not None and me_latest < 0 and not downgraded:
        pct -= 10
        downgraded = True
        note += f'|赚效转负({me_latest:+.2f}%)'
    if pct < 0:
        pct = 0
    return pct, note

# 赚效序列(近似: date→me, 池日期口径)
with open('data/money_effect_series.json', encoding='utf-8') as f:
    me_series = json.load(f)
me_by_date = {x['date'].replace('-', ''): x['me'] for x in me_series}

# ---------- 任务2: A的77笔 × 温度分档 ----------
with open('logs/trader_a.json', encoding='utf-8') as f:
    ta = json.load(f)
trades = ta['trade_history']

# 交易日序列(从重建序列得)
def prev_trading_day(d):
    idx = dates.index(d) - 1 if d in dates else None
    return dates[idx] if idx is not None and idx >= 0 else None

buckets = {'极弱空仓': [], '40-49': [], '50-59': [], '60-69': [], '70-79': [], '80-89': [], '90-99': [], '>=100': []}
tier_pct_map = {0: '极弱空仓', 40: '40-49', 50: '50-59', 60: '60-69', 70: '70-79', 80: '80-89', 90: '90-99', 100: '>=100'}

records = []
for t in trades:
    bd = t['buy_date'].replace('-', '')
    pnl = t.get('pnl_pct')
    d_prev = prev_trading_day(bd)
    d_prev2 = prev_trading_day(d_prev) if d_prev else None
    me_latest = me_by_date.get(d_prev2) if d_prev2 else None  # T-2池在T-1表现=T日盘前可见
    pct, note = temp_tier(d_prev, d_prev2, me_latest)
    if pct is None:
        records.append((t, None, None))
        continue
    bucket = tier_pct_map.get(pct, '极弱空仓')
    records.append((t, pct, note, bucket))
    if pnl is not None:
        buckets[bucket].append(pnl)

print('\n任务2: A的77笔(有盈亏数据的) × 温度分档')
print(f"{'档位':<8}{'笔数':>4}{'均收益':>8}{'胜率':>8}  {'明细'}")
for bk, pnls in buckets.items():
    if not pnls:
        continue
    avg = sum(pnls) / len(pnls)
    win = sum(1 for p in pnls if p > 0) / len(pnls)
    detail = ' '.join(f'{p:+.1f}' for p in sorted(pnls, reverse=True))
    print(f'{bk:<8}{len(pnls):>4}{avg:>+8.2f}%{win:>8.0%}  {detail}')

# 大赢单(>=+15%)与大亏单(<=-8%)落在哪个温度档
print('\n大赢单(>=+15%)与大亏单(<=-8%)的温度档分布:')
for t, pct, note, bucket in records:
    pnl = t.get('pnl_pct')
    if pnl is None:
        continue
    tag = '★赢' if pnl >= 15 else ('✗亏' if pnl <= -8 else None)
    if tag:
        print(f"  {t['buy_date']} {t['name']:<8}{pnl:+7.1f}% {tag}  温度档={bucket}({pct}%) {note or ''}")

# 无盈亏数据的笔落在哪个温度档(样本覆盖说明)
no_pnl = [r for r in records if r[0].get('pnl_pct') is None]
from collections import Counter
c_no = Counter(r[3] for r in no_pnl)
print(f"\n无盈亏数据的{len(no_pnl)}笔温度档分布: {dict(c_no)}")

# ---------- 任务3: 模拟温度开关套在A身上 ----------
# 口径: 温度仓位=0 → 跳过该笔(不投入); 温度仓位<55% → 半仓投入; >=55% → 全仓
# 无盈亏数据的笔: 分别按 (a)跳过不计 (b)假设0% 两种口径
print('\n任务3: 模拟温度开关对A的影响 (仅算有盈亏数据的笔, 每笔等权)')
for half_rule in [None, True]:
    kept, cut, cut_pnls, kept_half, kept_half_pnls = 0, [], [], 0, []
    for t, pct, note, bucket in records:
        pnl = t.get('pnl_pct')
        if pnl is None:
            continue
        if pct == 0:
            cut.append(t)
            cut_pnls.append(pnl)
        elif half_rule and pct < 55:
            kept_half += 1
            kept_half_pnls.append(pnl * 0.5)
        else:
            kept += 1
    tot_all = sum(t['pnl_pct'] for t, *_ in records if t.get('pnl_pct') is not None)
    label = '半仓口径(温度<55%减半)' if half_rule else '做/不做口径(温度>0全做)'
    tot_keep = tot_all - sum(cut_pnls) - (sum(kept_half_pnls) if half_rule else 0)
    # 半仓口径的"全做"基准=原收益
    print(f'[{label}]')
    print(f'  原始(全做): {tot_all:+.1f}% (N={sum(1 for t,*_ in records if t.get("pnl_pct") is not None)})')
    print(f'  砍掉(温度=0) {len(cut_pnls)}笔 合计{sum(cut_pnls):+.1f}%: ' + ' '.join(f"{t['name']}{t.get('pnl_pct'):+.1f}" for t in cut) if cut else '  砍掉0笔')
    if half_rule:
        print(f'  减半 {kept_half}笔 减少{sum(kept_half_pnls):+.1f}%')
    print(f'  模拟后: {tot_keep:+.1f}%  (变化 {tot_keep-tot_all:+.1f}%)')

# 分档视角: 每档合计盈亏(有数据笔)
print('\n分档合计盈亏(有数据笔, 等权求和):')
from collections import defaultdict
tier_sum = defaultdict(float)
tier_n = defaultdict(int)
for t, pct, note, bucket in records:
    pnl = t.get('pnl_pct')
    if pnl is None:
        continue
    tier_sum[bucket] += pnl
    tier_n[bucket] += 1
for bk in ['极弱空仓', '40-49', '50-59', '60-69', '70-79', '80-89', '90-99', '>=100']:
    if tier_n[bk]:
        print(f'  {bk:<8} N={tier_n[bk]:>2} 合计{tier_sum[bk]:+7.1f}%')

# 输出任务1序列供后续分析
out = {'dates': dates, 'rows': rows}
with open('logs/analysis/_temp_zt_series_20260907.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)
print(f'\n序列已存 logs/analysis/_temp_zt_series_20260907.json')
