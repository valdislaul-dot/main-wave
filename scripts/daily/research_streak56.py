"""
研究: 5-6板断板事件 (妖股研究7板+样本的向下延伸)
=========================================================
背景: 妖股研究_强连板发现体系.md 只覆盖 7板+ 样本, 结论"断板后无V型反转
      (+3日 中位-9.1%/31%上涨)"。闽东电力 6板断板(2026-09-17) + 次日反包
      未封(2026-09-18) 落在样本外, 本脚本回答: 5-6板断板后到底怎么走,
      反包(次日涨停)概率多少, 反包后/准涨停未封后如何演化。

口径:
  - 连板序列 streak in [5,6], 剔除次新(起点距K线首日<40根)
  - 断板日 = 连板结束后第一根非涨停K线
  - 所有收益以断板日收盘为基准
  - 量比 = 断板日量/前一日量 (环比, 与 research_streaks.py 一致)
  - 对照组: streak>=7 同口径复现, 验证与经典结论一致
"""
import json, os, sys, glob

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
IPO_GUARD = 40


def is_lu(close, prev_close, cyb):
    limit_price = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit_price - 0.005


def med(vals):
    if not vals:
        return None
    s = sorted(vals)
    return s[len(s) // 2]


def pct_up(vals):
    return sum(1 for v in vals if v > 0) / len(vals) * 100 if vals else None


def scan(code, klines):
    """找 streak in [5,6] 和 >=7 的连板事件, 返回断板日及后续"""
    if len(klines) < 30:
        return []
    cyb = code.startswith(('30', '68'))
    n = len(klines)
    lu = [False] * n
    for i in range(1, n):
        if klines[i].get('close') and klines[i - 1].get('close'):
            lu[i] = is_lu(klines[i]['close'], klines[i - 1]['close'], cyb)

    events = []
    i = 1
    while i < n:
        if not lu[i]:
            i += 1
            continue
        start = i
        while i < n and lu[i]:
            i += 1
        end = i  # 第一根非涨停 = 断板日; end==n 表示连板还在延续(未断板)
        streak = end - start
        if streak < 5 or end >= n:
            continue
        if start < IPO_GUARD:
            continue

        b = klines[end]
        prev = klines[end - 1]
        brk = {
            'date': b['date'],
            'pct': round((b['close'] - prev['close']) / prev['close'] * 100, 2),
            'vol_ratio': round(b.get('volume', 0) / max(prev.get('volume', 1), 1), 2),
        }
        base = b['close']
        after = {}
        for step in (1, 2, 3, 5):
            j = end + step
            if j < n:
                after[f'd{step}'] = {
                    'date': klines[j]['date'],
                    'ret': round((klines[j]['close'] - base) / base * 100, 2),
                    'lu': lu[j],
                }
        events.append({'code': code, 'streak': streak, 'start': klines[start]['date'],
                       'end': klines[end - 1]['date'], 'brk': brk, 'after': after})
    return events


def summarize(tag, evs):
    print(f'\n{"="*62}\n{tag}: {len(evs)} 个事件\n{"="*62}')
    if not evs:
        return
    b_pcts = [e['brk']['pct'] for e in evs]
    b_vols = [e['brk']['vol_ratio'] for e in evs]
    print(f"断板日: 收阴 {sum(1 for p in b_pcts if p < 0)}个({sum(1 for p in b_pcts if p < 0)/len(b_pcts)*100:.0f}%) "
          f"中位{b_pcts and med(b_pcts):+.1f}% | 量比中位 {med(b_vols):.2f}x "
          f"(>2x {sum(1 for v in b_vols if v > 2)/len(b_vols)*100:.0f}%, <1.5x {sum(1 for v in b_vols if v < 1.5)/len(b_vols)*100:.0f}%)")

    for step in (1, 2, 3, 5):
        key = f'd{step}'
        vals = [e['after'][key]['ret'] for e in evs if key in e['after']]
        lus = [e['after'][key]['lu'] for e in evs if key in e['after']]
        if vals:
            print(f"  断板后+{step}日(n={len(vals)}): 中位{med(vals):+.2f}% 上涨{pct_up(vals):.0f}% "
                  f"涨停{sum(lus)}个({sum(lus)/len(lus)*100:.0f}%)")

    # 分层: 断板收阴/收红 × 次日
    print('\n-- 分层: 断板日形态 → 次日(d1) --')
    for label, cond in [('收阴', lambda e: e['brk']['pct'] < 0),
                        ('收红', lambda e: e['brk']['pct'] >= 0),
                        ('收阴+放量≥2x', lambda e: e['brk']['pct'] < 0 and e['brk']['vol_ratio'] >= 2),
                        ('收阴+量<1.5x', lambda e: e['brk']['pct'] < 0 and e['brk']['vol_ratio'] < 1.5),
                        ('收红+缩量<1.5x', lambda e: e['brk']['pct'] >= 0 and e['brk']['vol_ratio'] < 1.5)]:
        sub = [e for e in evs if cond(e) and 'd1' in e['after']]
        if not sub:
            continue
        v1 = [e['after']['d1']['ret'] for e in sub]
        lu1 = [e['after']['d1']['lu'] for e in sub]
        print(f"  {label}(n={len(sub)}): d1中位{med(v1):+.2f}% 上涨{pct_up(v1):.0f}% 反包涨停{sum(lu1)/len(lu1)*100:.0f}%")

    # 子样本: d1 准涨停未封 (7% <= ret < 涨停未封) —— 闽东 09-18 形态 (+9.07%)
    print('\n-- 子样本: d1 大涨7%+但未涨停(闽东型) → d2/d3/d5 --')
    quazi = [e for e in evs if 'd1' in e['after'] and e['after']['d1']['ret'] >= 7 and not e['after']['d1']['lu']]
    if quazi:
        for step in (2, 3, 5):
            key = f'd{step}'
            vals = [e['after'][key]['ret'] for e in quazi if key in e['after']]
            if vals:
                print(f"  d{step}(n={len(vals)}): 中位{med(vals):+.2f}% 上涨{pct_up(vals):.0f}% "
                      f"(相对断板日收盘)")
    else:
        print('  无样本')

    # 子样本: d1 反包涨停 → 后续
    print('\n-- 子样本: d1 反包涨停 → d2/d3/d5 --')
    reb = [e for e in evs if 'd1' in e['after'] and e['after']['d1']['lu']]
    if reb:
        b1 = [e['after']['d1']['ret'] for e in reb]
        print(f"  样本 {len(reb)}个, d1中位{b1 and med(b1):+.1f}%")
        for step in (2, 3, 5):
            key = f'd{step}'
            vals = [e['after'][key]['ret'] for e in reb if key in e['after']]
            if vals:
                print(f"  d{step}(n={len(vals)}): 中位{med(vals):+.2f}% 上涨{pct_up(vals):.0f}%")

    # ===== 从 d1 收盘出发的增量收益 (决策相关口径) =====
    print('\n-- 增量口径: 相对 d1 收盘的后续收益 (从"已反包"状态出发) --')
    for label, cond in [
        ('全样本', lambda e: True),
        ('d1反包涨停', lambda e: e['after'].get('d1', {}).get('lu')),
        ('d1大涨7%+未封(闽东型)', lambda e: e['after'].get('d1', {}).get('ret', -99) >= 7 and not e['after'].get('d1', {}).get('lu')),
        ('d1大涨7%+未封 且断板收阴', lambda e: e['after'].get('d1', {}).get('ret', -99) >= 7 and not e['after'].get('d1', {}).get('lu') and e['brk']['pct'] < 0),
    ]:
        sub = [e for e in evs if cond(e) and 'd1' in e['after']]
        if not sub:
            continue
        print(f"  {label}(n={len(sub)}):")
        for step in (2, 3, 5):
            key = f'd{step}'
            vals = []
            for e in sub:
                if key in e['after']:
                    r1, rn = e['after']['d1']['ret'], e['after'][key]['ret']
                    vals.append(round(((1 + rn / 100) / (1 + r1 / 100) - 1) * 100, 2))
            if vals:
                print(f"    d{step}相对d1(n={len(vals)}): 中位{med(vals):+.2f}% 上涨{pct_up(vals):.0f}%")


def main():
    files = glob.glob(os.path.join(KLINE_DIR, '*.json'))
    print(f'K线库: {len(files)} 只, 扫描 streak>=5 连板事件...')
    ev56, ev7p = [], []
    for fi, fp in enumerate(files):
        code = os.path.basename(fp).replace('.json', '')
        if not code.isdigit():
            continue
        try:
            raw = json.load(open(fp, encoding='utf-8'))
            kl = raw['data'] if isinstance(raw, dict) else raw
            for e in scan(code, kl):
                e['name'] = raw.get('metadata', {}).get('name', '') if isinstance(raw, dict) else ''
                (ev56 if e['streak'] in (5, 6) else ev7p).append(e)
        except Exception:
            continue

    summarize('5-6板断板 (本次新增, 样本外延伸)', ev56)
    summarize('7板+断板 (对照, 复现经典口径)', ev7p)

    e5 = [e for e in ev56 if e['streak'] == 5]
    e6 = [e for e in ev56 if e['streak'] == 6]
    print(f'\n5板断板 {len(e5)}个 | 6板断板 {len(e6)}个')
    for tag, sub in [('5板', e5), ('6板', e6)]:
        vals = [e['after']['d1']['ret'] for e in sub if 'd1' in e['after']]
        lu1 = [e['after']['d1']['lu'] for e in sub if 'd1' in e['after']]
        negatives = [e for e in sub if e['brk']['pct'] < 0 and 'd1' in e['after']]
        nv = [e['after']['d1']['ret'] for e in negatives]
        nlu = [e['after']['d1']['lu'] for e in negatives]
        if vals:
            print(f'  {tag}: d1中位{med(vals):+.2f}% 上涨{pct_up(vals):.0f}% 反包{sum(lu1)/len(lu1)*100:.0f}% '
                  f'|| 断板收阴子组(n={len(nv)}): d1中位{med(nv):+.2f}% 反包{sum(nlu)/len(nlu)*100:.0f}%')

    out = os.path.join(BASE, 'logs', 'research_streak56.json')
    json.dump({'total_56': len(ev56), 'total_7p': len(ev7p), 'events_56': ev56},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
