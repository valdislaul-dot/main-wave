"""
研究: 连板晋级率曲线 + 断板日开盘缺口分层 (2026-09-19, 妖股理论验证)
====================================================================
1. 晋级率 P(k板→k+1板): 全库连板段统计, 验证"二进三/三进四"民间说法
   及妖股高度分布("12-15板集中")
2. 5-6板断板日开盘缺口(gap)分层 → 断板后+1日, 验证"深水低开拉回型"
   (闽东 2026-09-17: gap-9.96% 后拉回收-2.76%) 是否区别于普通断板
3. 大样本增量口径: 相对 d1 收盘的 d2/d3/d5 (从"已反包"状态出发)

只读本地 kline_data/, 不做网络抓取。
"""
import json, os, sys, glob

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
IPO_GUARD = 40


def is_lu(close, prev_close, cyb):
    limit_price = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit_price - 0.005


def med(vals):
    s = sorted(vals)
    return s[len(s) // 2] if s else None


def pct_up(vals):
    return sum(1 for v in vals if v > 0) / len(vals) * 100 if vals else None


def main():
    files = glob.glob(os.path.join(KLINE_DIR, '*.json'))
    print(f'K线库: {len(files)} 只')
    streaks = []          # 所有连板段 (含未结束, 标注)
    break56 = []          # 5-6板断板事件(带gap)
    for fi, fp in enumerate(files):
        code = os.path.basename(fp).replace('.json', '')
        if not code.isdigit():
            continue
        try:
            raw = json.load(open(fp, encoding='utf-8'))
            kl = raw['data'] if isinstance(raw, dict) else raw
        except Exception:
            continue
        n = len(kl)
        if n < 30:
            continue
        cyb = code.startswith(('30', '68'))
        lu = [False] * n
        for i in range(1, n):
            if kl[i].get('close') and kl[i - 1].get('close'):
                lu[i] = is_lu(kl[i]['close'], kl[i - 1]['close'], cyb)
        i = 1
        while i < n:
            if not lu[i]:
                i += 1
                continue
            start = i
            while i < n and lu[i]:
                i += 1
            streak = i - start
            if start < IPO_GUARD:
                continue
            closed = i < n
            streaks.append({'code': code, 'streak': streak, 'closed': closed, 'start_idx': start, 'end_idx': i})
            # 5-6板断板事件 + 断板日 gap
            if streak in (5, 6) and closed:
                b, prev = kl[i], kl[i - 1]
                gap = (b['open'] - prev['close']) / prev['close'] * 100
                base = b['close']
                after = {}
                for step in (1, 2, 3, 5):
                    j = i + step
                    if j < n:
                        after[f'd{step}'] = {'ret': round((kl[j]['close'] - base) / base * 100, 2), 'lu': lu[j],
                                             'gap': round((kl[j]['open'] - (base if step == 1 else kl[j - 1]['close'])) / (base if step == 1 else kl[j - 1]['close']) * 100, 2)}
                break56.append({'code': code, 'streak': streak, 'gap': round(gap, 2),
                                'brk_pct': round((b['close'] - prev['close']) / prev['close'] * 100, 2),
                                'recover': b['close'] > b['open'], 'after': after})

    # ===== 1. 晋级率曲线 =====
    print(f'\n{"="*62}\n1. 连板段: {len(streaks)} 个 (含未结束 {sum(1 for s in streaks if not s["closed"])} 个)\n{"="*62}')
    closed = [s for s in streaks if s['closed']]
    maxk = 13
    hist = {k: sum(1 for s in closed if s['streak'] == k) for k in range(1, maxk + 1)}
    print('高度分布(已结束段):')
    for k in range(1, maxk + 1):
        bar = '#' * min(60, hist.get(k, 0) // 40)
        print(f'  {k:2d}板: {hist.get(k, 0):6d} {bar}')
    print(f'  >={maxk+1}板: {sum(1 for s in closed if s["streak"] > maxk)}')
    print('\n晋级率 P(k板 → k+1板) [已结束段口径]:')
    for k in range(1, maxk):
        hk = sum(1 for s in closed if s['streak'] >= k)
        hk1 = sum(1 for s in closed if s['streak'] >= k + 1)
        if hk:
            print(f'  {k:2d}→{k+1:2d}板: {hk1}/{hk} = {hk1/hk*100:5.1f}%')

    # ===== 2. 断板日 gap 分层 =====
    print(f'\n{"="*62}\n2. 5-6板断板日 gap 分层 (n={len(break56)})\n{"="*62}')
    for label, cond in [
        ('深水低开 gap<=-5%', lambda e: e['gap'] <= -5),
        ('  └ 其中拉回收阳(闽东型)', lambda e: e['gap'] <= -5 and e['recover']),
        ('低开 -5%~0', lambda e: -5 < e['gap'] < 0),
        ('平/高开 gap>=0', lambda e: e['gap'] >= 0),
    ]:
        sub = [e for e in break56 if cond(e) and 'd1' in e['after']]
        if not sub:
            continue
        v1 = [e['after']['d1']['ret'] for e in sub]
        lu1 = [e['after']['d1']['lu'] for e in sub]
        v2, v3 = [], []
        for e in sub:
            if 'd2' in e['after']:
                v2.append(round(((1 + e['after']['d2']['ret'] / 100) / (1 + e['after']['d1']['ret'] / 100) - 1) * 100, 2))
            if 'd3' in e['after']:
                v3.append(round(((1 + e['after']['d3']['ret'] / 100) / (1 + e['after']['d1']['ret'] / 100) - 1) * 100, 2))
        print(f"  {label}(n={len(sub)}): d1中位{med(v1):+.2f}% 上涨{pct_up(v1):.0f}% 反包涨停{sum(lu1)/len(lu1)*100:.0f}% "
              f"|| d2相对d1中位{med(v2):+.2f}%/{pct_up(v2):.0f}% d3相对d1中位{med(v3):+.2f}%/{pct_up(v3):.0f}%")

    # ===== 3. 全样本增量口径 =====
    print(f'\n{"="*62}\n3. 增量口径: 相对 d1 收盘 (5-6板断板全样本)\n{"="*62}')
    for step in (2, 3, 5):
        vals = []
        for e in break56:
            if f'd{step}' in e['after'] and 'd1' in e['after']:
                vals.append(round(((1 + e['after'][f'd{step}']['ret'] / 100) / (1 + e['after']['d1']['ret'] / 100) - 1) * 100, 2))
        print(f'  d{step}相对d1(n={len(vals)}): 中位{med(vals):+.2f}% 上涨{pct_up(vals):.0f}%')

    # ===== 4. d1(断板后首日) 开盘缺口分层 =====
    print(f'\n{"="*62}\n4. d1 开盘 gap 分层 (验证民间"次日不低开闷杀要素")\n{"="*62}')
    for label, cond in [
        ('d1高开 gap>=0', lambda e: e['after'].get('d1', {}).get('gap', 0) >= 0),
        ('d1小低开 -3%~0', lambda e: -3 <= e['after'].get('d1', {}).get('gap', 0) < 0),
        ('d1大低开闷杀 <-3%', lambda e: e['after'].get('d1', {}).get('gap', -99) < -3),
    ]:
        sub = [e for e in break56 if 'd1' in e['after'] and cond(e)]
        if not sub:
            continue
        v1 = [e['after']['d1']['ret'] for e in sub]
        lu1 = [e['after']['d1']['lu'] for e in sub]
        v2 = [round(((1 + e['after']['d2']['ret'] / 100) / (1 + e['after']['d1']['ret'] / 100) - 1) * 100, 2)
              for e in sub if 'd2' in e['after']]
        print(f"  {label}(n={len(sub)}): d1收盘中位{med(v1):+.2f}% 上涨{pct_up(v1):.0f}% 涨停{sum(lu1)/len(lu1)*100:.0f}% "
              f"|| d2相对d1中位{med(v2):+.2f}%/{pct_up(v2):.0f}%")

    out = os.path.join(BASE, 'logs', 'research_streak_ladder.json')
    json.dump({'ladder': {str(k): hist.get(k, 0) for k in range(1, maxk + 1)}, 'break56': break56},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
