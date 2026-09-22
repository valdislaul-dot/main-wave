"""
研究: 妖股因子时间稳定性检验 — 年度分层 + 前后段切分 (2026-09-19)
================================================================
背景: 用户对回测优化的不信任 (V3→V4 教训)。本检验回答:
      factors/factors2 发现的因子(量比<0.8x / 启动<10元 / 振幅<4% / 换手<5% /
      加速度<0.7x / 核心组合) 是"逐年稳定"还是"只在某些年份有效"?

方法:
  1. 年度分层: 每个条件按2板日年份分组, 对比当年基线成妖率 → 观察是否同向
  2. 前/后段切分: 2016-2022 (训练段) vs 2023-2026 (检验段)
  3. 因子定义固定(非搜出), 检验的是时间稳定性, 无参数搜索
"""
import json, os, sys, glob

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
IPO_GUARD = 40


def is_lu(close, prev_close, cyb):
    limit = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit - 0.005


def main():
    files = glob.glob(os.path.join(KLINE_DIR, '*.json'))
    print(f'K线库: {len(files)} 只')
    evs = []
    for fp in files:
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
            if start < IPO_GUARD or i >= n or streak < 2:
                continue
            b1, b2 = start, start + 1
            prev2 = kl[b2 - 1]
            sp = kl[start - 1].get('close', 0)
            vols = [kl[j].get('volume', 0) or 0 for j in range(max(0, b2 - 5), b2)]
            avg = sum(vols) / len(vols) if vols else 0
            vr = round((kl[b2].get('volume', 0) or 0) / avg, 2) if avg > 0 else None
            v1 = kl[b1].get('volume', 0) or 0
            v2 = kl[b2].get('volume', 0) or 0
            accel = round(v2 / v1, 2) if v1 > 0 else None
            turn2 = kl[b2].get('turnover_pct')
            pc2 = prev2.get('close') or 0
            amp2 = None
            if pc2 and kl[b2].get('high') is not None and kl[b2].get('low') is not None:
                amp2 = round((kl[b2]['high'] - kl[b2]['low']) / pc2 * 100, 2)
            evs.append({'y': kl[b2]['date'][:4], 'code': code, 'date': kl[b2]['date'],
                        'sp': sp, 'vr': vr, 'accel': accel, 'turn2': turn2, 'amp2': amp2,
                        'is7': streak >= 7, 'is5': streak >= 5})

    base7 = sum(e['is7'] for e in evs) / len(evs) * 100
    years = sorted(set(e['y'] for e in evs))
    ybase = {}
    for y in years:
        sub = [e for e in evs if e['y'] == y]
        ybase[y] = sum(x['is7'] for x in sub) / len(sub) * 100

    print(f'\n总事件 {len(evs)} | 全样本基线成妖率 {base7:.2f}%')
    print(f'\n== 年度基线 (成妖事件数/事件数) ==')
    for y in years:
        sub = [e for e in evs if e['y'] == y]
        n7 = sum(x['is7'] for x in sub)
        print(f'  {y}: n={len(sub):>5} 成妖{n7:>3}个 基线 {ybase[y]:>5.2f}%')

    conds = [
        ('C1 量比<0.8x', lambda e: e['vr'] is not None and e['vr'] < 0.8),
        ('C2 启动<10元', lambda e: e['sp'] is not None and e['sp'] < 10),
        ('C3 核心=量比<0.8+启动<10', lambda e: e['vr'] is not None and e['vr'] < 0.8
         and e['sp'] is not None and e['sp'] < 10),
        ('C4 振幅<4%', lambda e: e['amp2'] is not None and e['amp2'] < 4),
        ('C5 换手<5%', lambda e: e['turn2'] is not None and e['turn2'] < 5),
        ('C6 加速度<0.7x', lambda e: e['accel'] is not None and e['accel'] < 0.7),
    ]
    for label, cond in conds:
        sub = [e for e in evs if cond(e)]
        if not sub:
            continue
        r7 = sum(x['is7'] for x in sub) / len(sub) * 100
        print(f'\n-- {label} --')
        print(f'  全样本: n={len(sub)} 成妖率{r7:.2f}% ({r7/base7:.2f}x)')
        line = '  逐年 vs 当年基线: '
        parts = []
        for y in years:
            ys = [e for e in sub if e['y'] == y]
            if not ys:
                continue
            if len(ys) < 20:
                parts.append(f'{y}: n={len(ys)}(样本少)')
            else:
                rr = sum(x['is7'] for x in ys) / len(ys) * 100
                parts.append(f'{y}: {rr/ybase[y]:.2f}x(n={len(ys)})')
        print(line + ' | '.join(parts))
        for seg_name, seg_cond in [('训练段 2016-2022', lambda e: e['y'] <= '2022'),
                                   ('检验段 2023-2026', lambda e: e['y'] >= '2023')]:
            ss = [e for e in sub if seg_cond(e)]
            sb = [e for e in evs if seg_cond(e)]
            if ss and sb:
                rr = sum(x['is7'] for x in ss) / len(ss) * 100
                sbase = sum(x['is7'] for x in sb) / len(sb) * 100
                flag = '✓同向' if rr > sbase else '✗失效'
                print(f'  {seg_name}: n={len(ss)} 成妖率{rr:.2f}% vs 段基线{sbase:.2f}% = {rr/sbase:.2f}x {flag}')

    out = os.path.join(BASE, 'logs', 'research_yaogu_oos.json')
    json.dump({'total': len(evs), 'base7': base7, 'yearbase': ybase},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
