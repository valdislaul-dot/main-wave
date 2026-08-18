"""
研究: 7连板以上妖股 + 十几个交易日内仅断板1-2天的强势股 (v2)
================================================================
扫描 kline_data/ 全库, 识别强连板事件:
  A. 连续涨停 >= 7板 (剔除新股上市连板: 事件起点距K线首日<40根)
  B. 15个交易日内涨停 >= 13次 (断板<=2天)
  C. 20个交易日内涨停 >= 16次 (断板<=4天, 放宽样本)
分析: 事件清单 / 断板日特征 / 断板位置分布 / 事件后走势
"""
import json, os, sys, glob

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')

MIN_STREAK = 7
IPO_GUARD = 40      # 事件起点距K线首日<40根视为次新连板, 剔除
WINDOWS = [(15, 13, 'B_15日13板'), (20, 16, 'C_20日16板')]


def is_lu(close, prev_close, cyb):
    limit_price = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit_price - 0.005


def analyze(code, klines):
    if len(klines) < 30:
        return []
    cyb = code.startswith(('30', '68'))
    lu_flags = [False] * len(klines)
    for i in range(1, len(klines)):
        if klines[i].get('close') and klines[i - 1].get('close'):
            lu_flags[i] = is_lu(klines[i]['close'], klines[i - 1]['close'], cyb)

    events = []
    i = 1
    while i < len(klines):
        if not lu_flags[i]:
            i += 1
            continue
        start = i
        while i < len(klines) and lu_flags[i]:
            i += 1
        end = i
        streak = end - start
        is_ipo = start < IPO_GUARD

        # A类: 连续涨停>=7
        if streak >= MIN_STREAK:
            events.append({'code': code, 'type': 'A_连板', 'ipo': is_ipo,
                           'start_date': klines[start]['date'], 'end_date': klines[end - 1]['date'],
                           'streak': streak, 'start_idx': start, 'end_idx': end,
                           'after': _after(klines, end - 1)})
        # B/C类窗口
        for win_n, min_lu, tname in WINDOWS:
            w_end = min(start + win_n, len(klines))
            lu_cnt = sum(lu_flags[start:w_end])
            if lu_cnt >= min_lu:
                break_days = []
                for j in range(start + 1, w_end):
                    if not lu_flags[j]:
                        prev = klines[j - 1]['close']
                        break_days.append({
                            'date': klines[j]['date'],
                            'board': j - start,  # 第几板后断
                            'pct': round((klines[j]['close'] - prev) / prev * 100, 2),
                            'vol_ratio': round(klines[j].get('volume', 0) / max(klines[j - 1].get('volume', 0), 1), 2),
                        })
                events.append({'code': code, 'type': tname, 'ipo': is_ipo,
                               'start_date': klines[start]['date'], 'end_date': klines[w_end - 1]['date'],
                               'streak': lu_cnt, 'start_idx': start, 'end_idx': w_end,
                               'max_consec': streak, 'break_days': break_days,
                               'after': _after(klines, w_end - 1)})
    return events


def _after(klines, last_lu_idx):
    """事件最后涨停日之后的 +3/+5/+10 日收盘收益(以最后涨停日收盘为基准)"""
    base = klines[last_lu_idx]['close']
    out = {}
    for n in (3, 5, 10):
        idx = last_lu_idx + n
        if idx < len(klines):
            out[f'p{n}'] = round((klines[idx]['close'] - base) / base * 100, 2)
    return out


def main():
    files = glob.glob(os.path.join(KLINE_DIR, '*.json'))
    print(f'K线库: {len(files)} 只, 开始扫描...')
    all_events = []
    for fi, fp in enumerate(files):
        code = os.path.basename(fp).replace('.json', '').split('_')[-1]
        if not code.isdigit():
            continue
        try:
            raw = json.load(open(fp, encoding='utf-8'))
            kl = raw['data'] if isinstance(raw, dict) else raw
            name = raw.get('metadata', {}).get('name', '') if isinstance(raw, dict) else ''
            for e in analyze(code, kl):
                e['name'] = name
                all_events.append(e)
        except Exception:
            continue
        if (fi + 1) % 500 == 0:
            print(f'  已扫 {fi + 1}/{len(files)}')

    real = [e for e in all_events if not e['ipo']]
    print(f'\n共 {len(all_events)} 个事件 (剔除次新后 {len(real)} 个)')

    for tname, label in [('A_连板', 'A类: 连续涨停>=7板'), ('B_15日13板', 'B类: 15日13板'), ('C_20日16板', 'C类: 20日16板')]:
        evs = [e for e in real if e['type'] == tname]
        print(f'\n===== {label}: {len(evs)} 个 =====')
        for e in sorted(evs, key=lambda x: -x['streak'])[:12]:
            if tname == 'A_连板':
                print(f"  {e['name'] or ''}({e['code']}) {e['start_date']} 起 {e['streak']}连板")
            else:
                brk = '、'.join(f"{b['board']}板后{b['pct']:+.0f}%(量{b['vol_ratio']:.1f}x)" for b in e['break_days'])
                print(f"  {e['name'] or ''}({e['code']}) {e['start_date']} 起 {e['streak']}板/15日 最长{e['max_consec']} | 断板: {brk}")

    # ===== 断板日特征 =====
    all_breaks = [b for e in real for b in e.get('break_days', [])]
    print(f'\n===== 断板日特征汇总 ({len(all_breaks)} 个断板日, 剔除次新) =====')
    if all_breaks:
        pcts = sorted(b['pct'] for b in all_breaks)
        vols = sorted(b['vol_ratio'] for b in all_breaks)
        boards = sorted(b['board'] for b in all_breaks)
        med = lambda x: x[len(x) // 2]
        print(f'断板位置: 第{med(boards)}板(中位) | 分布: <4板 {sum(1 for x in boards if x<4)}个, 4-7板 {sum(1 for x in boards if 4<=x<=7)}个, >7板 {sum(1 for x in boards if x>7)}个')
        print(f'断板日涨跌: 中位{med(pcts):+.1f}% | <0% {sum(1 for p in pcts if p<0)}个({sum(1 for p in pcts if p<0)/len(pcts)*100:.0f}%) | 0~5% {sum(1 for p in pcts if 0<=p<5)}个 | >=5% {sum(1 for p in pcts if p>=5)}个')
        print(f'断板日量比: 中位{med(vols):.2f}x | >1.5x {sum(1 for v in vols if v>1.5)}个({sum(1 for v in vols if v>1.5)/len(vols)*100:.0f}%) | <0.8x {sum(1 for v in vols if v<0.8)}个')
        # 断板日涨跌 vs 后续
        for label, cond in [('断板收阴', lambda b: b['pct'] < 0), ('断板收红', lambda b: b['pct'] >= 0)]:
            sub = [b for b in all_breaks if cond(b)]
            print(f'  {label}({len(sub)}个): 平均量比{sum(b["vol_ratio"] for b in sub)/max(len(sub),1):.2f}x')

    # ===== 事件后走势 =====
    print(f'\n===== 事件后走势 (最后涨停日收盘为基准) =====')
    for tname, label in [('A_连板', 'A类'), ('B_15日13板', 'B类'), ('C_20日16板', 'C类')]:
        evs = [e for e in real if e['type'] == tname]
        for n in (3, 5, 10):
            vals = [e['after'][f'p{n}'] for e in evs if f'p{n}' in e['after']]
            if vals:
                vals.sort()
                med = vals[len(vals) // 2]
                pos = sum(1 for v in vals if v > 0) / len(vals) * 100
                print(f'  {label}(n={len(vals)}): +{n}日 中位{med:+.1f}% 上涨概率{pos:.0f}%')

    out_path = os.path.join(BASE, 'logs', 'research_streaks.json')
    json.dump({'generated': '2026-08-18', 'total': len(real), 'events': real},
              open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out_path}')


if __name__ == '__main__':
    main()
