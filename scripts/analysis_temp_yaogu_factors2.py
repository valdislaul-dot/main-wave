"""
研究: 2板时点扩展因子 — 换手率 / 板型 / 振幅 / 量能加速度 / 启动前波动 (2026-09-19)
==============================================================================
承接 analysis_temp_yaogu_factors.py（量比/启动价/前20日 已验证）:
  用户提出"结合量比、换手率、K线形态" → 本脚本验证后三类因子的全样本预测力。

口径与前一脚本一致:
  - 事件 = 每个连板段第2板日(段起点+1), 仅已结束段, IPO_GUARD=40
  - 标签: 段最终高度 >=7 (成妖) / >=5 (走强)

新增因子(均为2板时点可观测, 无未来函数):
  - turn2/turn1: 2板日/1板日换手率 (K线自带 turnover_pct)
  - vol_accel:   2板量/1板量 (A体系"缩量加速"的直接度量, 与量比正交)
  - amp2:        2板日振幅 (high-low)/prev_close
  - pre_std:     启动前20日日收益率标准差 (VCP式"蓄势收敛"的量化)
  - btype:       2板日板型 (一字/T字/换手板)
  - 相关性:      换手率 vs 量比 (双重计入检查)
"""
import json, os, sys, glob, statistics

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
IPO_GUARD = 40


def is_lu(close, prev_close, cyb):
    limit = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit - 0.005


def board_type(bar, prev_close, cyb):
    limit = round(prev_close * (1.2 if cyb else 1.1), 2)
    o, h, l, c = bar.get('open'), bar.get('high'), bar.get('low'), bar.get('close')
    if None in (o, h, l, c):
        return None
    if l >= limit - 0.005:
        return '一字'
    if o >= limit - 0.005 and c >= limit - 0.005:
        return 'T字'
    return '换手'


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
            # 量比 (与前一脚本同口径: 2板量/前5日均量)
            vols = [kl[j].get('volume', 0) or 0 for j in range(max(0, b2 - 5), b2)]
            avg = sum(vols) / len(vols) if vols else 0
            vr = round((kl[b2].get('volume', 0) or 0) / avg, 2) if avg > 0 else None
            # 量能加速度
            v1 = kl[b1].get('volume', 0) or 0
            v2 = kl[b2].get('volume', 0) or 0
            accel = round(v2 / v1, 2) if v1 > 0 else None
            # 换手率
            turn2 = kl[b2].get('turnover_pct')
            turn1 = kl[b1].get('turnover_pct')
            # 振幅
            pc2 = prev2.get('close') or 0
            amp2 = None
            if pc2 and kl[b2].get('high') is not None and kl[b2].get('low') is not None:
                amp2 = round((kl[b2]['high'] - kl[b2]['low']) / pc2 * 100, 2)
            # 启动前20日日收益率标准差
            pcs = [kl[j].get('pct_change') for j in range(max(1, start - 20), start)
                   if kl[j].get('pct_change') is not None]
            pre_std = round(statistics.pstdev(pcs), 2) if len(pcs) >= 10 else None
            bt = board_type(kl[b2], pc2, cyb)
            evs.append({'code': code, 'date': kl[b2]['date'], 'sp': sp, 'vr': vr, 'accel': accel,
                        'turn2': turn2, 'turn1': turn1, 'amp2': amp2, 'pre_std': pre_std,
                        'bt': bt, 'streak': streak, 'is7': streak >= 7, 'is5': streak >= 5})

    base7 = sum(e['is7'] for e in evs) / len(evs) * 100
    base5 = sum(e['is5'] for e in evs) / len(evs) * 100
    print(f'\n2板事件 (已结束段): {len(evs)} 个 | 基线成妖率(>=7板) {base7:.2f}% | 走强率(>=5板) {base5:.2f}%')

    def show(field, bins, label):
        print(f'\n-- {label} --')
        print(f'{"档位":<20} {"样本":>6} {"成妖率>=7":>9} {"走强率>=5":>9} {"倍数(vs基线)":>12}')
        valid = [e for e in evs if e.get(field) is not None]
        if not valid:
            print('  (无有效样本)')
            return
        for lo, hi, name in bins:
            sub = [e for e in valid if lo <= e[field] < hi]
            if not sub:
                continue
            r7 = sum(x['is7'] for x in sub) / len(sub) * 100
            r5 = sum(x['is5'] for x in sub) / len(sub) * 100
            print(f'{name:<20} {len(sub):>6} {r7:>8.2f}% {r5:>8.2f}% {r7/base7:>11.2f}x')

    show('turn2', [(0, 5, '<5%'), (5, 10, '5-10%'), (10, 20, '10-20%'),
                   (20, 30, '20-30%'), (30, 999, '>30%')], '2板日换手率')
    show('turn1', [(0, 5, '<5%'), (5, 10, '5-10%'), (10, 20, '10-20%'),
                   (20, 30, '20-30%'), (30, 999, '>30%')], '1板日(首板)换手率')
    show('accel', [(0, 0.7, '<0.7x'), (0.7, 1.2, '0.7-1.2x'), (1.2, 2, '1.2-2x'),
                   (2, 4, '2-4x'), (4, 9999, '>4x')], '量能加速度 (2板量/1板量)')
    show('amp2', [(0, 1, '<1%(贴一字)'), (1, 4, '1-4%'), (4, 8, '4-8%'), (8, 9999, '>8%')],
         '2板日振幅')
    show('pre_std', [(0, 1.5, '<1.5'), (1.5, 3, '1.5-3'), (3, 5, '3-5'), (5, 999, '>5')],
         '启动前20日日收益标准差 (蓄势收敛度)')

    # 板型
    print('\n-- 2板日板型 --')
    for bt in ('一字', 'T字', '换手'):
        sub = [e for e in evs if e['bt'] == bt]
        if not sub:
            continue
        r7 = sum(x['is7'] for x in sub) / len(sub) * 100
        r5 = sum(x['is5'] for x in sub) / len(sub) * 100
        print(f'{bt:<6} {len(sub):>6} 成妖率{r7:>7.2f}% ({r7/base7:.2f}x) 走强率{r5:>7.2f}%')

    # 相关性: turn2 vs vr
    pair = [(e['turn2'], e['vr']) for e in evs if e.get('turn2') is not None and e.get('vr') is not None]
    if len(pair) > 100:
        xs = [p[0] for p in pair]
        ys = [p[1] for p in pair]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in pair) / len(pair)
        sx = (sum((x - mx) ** 2 for x in xs) / len(xs)) ** 0.5
        sy = (sum((y - my) ** 2 for y in ys) / len(ys)) ** 0.5
        r = cov / (sx * sy) if sx and sy else 0
        print(f'\n-- 相关性: 2板换手率 vs 量比 (n={len(pair)}) --')
        print(f'  Pearson r = {r:.3f}  (|r|>0.7 视为重复计入)')

    # 组合: 已验证最优(量比<0.8+启动<10) 叠加板型/换手
    print('\n-- 组合叠加 (已验证核心: 量比<0.8x 且 启动价<10元) --')
    core = [e for e in evs if e.get('vr') is not None and e['vr'] < 0.8 and e.get('sp') is not None and e['sp'] < 10]
    if core:
        r7 = sum(x['is7'] for x in core) / len(core) * 100
        print(f'  核心组合基准: n={len(core)} 成妖率{r7:.2f}%')
        for label, cond in [
            ('+ 换手<10%', lambda e: e.get('turn2') is not None and e['turn2'] < 10),
            ('+ 换手10-20%', lambda e: e.get('turn2') is not None and 10 <= e['turn2'] < 20),
            ('+ 换手>=20%', lambda e: e.get('turn2') is not None and e['turn2'] >= 20),
            ('+ 加速度<0.7x', lambda e: e.get('accel') is not None and e['accel'] < 0.7),
            ('+ 板型=换手板', lambda e: e.get('bt') == '换手'),
            ('+ 振幅<4%', lambda e: e.get('amp2') is not None and e['amp2'] < 4),
        ]:
            sub = [e for e in core if cond(e)]
            if sub:
                rr = sum(x['is7'] for x in sub) / len(sub) * 100
                print(f'  {label:<14} n={len(sub):>5} 成妖率{rr:>6.2f}% ({rr/base7:.2f}x)')
        # 核心组合内按板型拆分 (可交易性视角: 一字买不进, T字有窗口, 换手板随便买)
        for bt in ('一字', 'T字', '换手'):
            sub = [e for e in core if e.get('bt') == bt]
            if sub:
                rr = sum(x['is7'] for x in sub) / len(sub) * 100
                print(f'  [板型]{bt:<4} n={len(sub):>5} 成妖率{rr:>6.2f}% ({rr/base7:.2f}x)')

    out = os.path.join(BASE, 'logs', 'research_yaogu_factors2.json')
    json.dump({'total': len(evs), 'base7': base7, 'events': evs},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
