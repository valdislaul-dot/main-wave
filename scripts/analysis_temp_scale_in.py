"""高板分批加仓 vs 首笔全仓 (2026-09-21 用户提议验证)

用户提议: "5进6时竞价小仓位进, 成功进6则在6进7时再观察, 能继续持有则加仓, 少量多次获取收益"

关键问题(不是"分批更稳"): **晋级之后再入场的那一笔, 期望是否高于第一次入场?**
  - 若两笔期望相同 → 分批=同一个赌注押得更少, 赢时必然输给全仓
  - 若后笔期望更高 → 加仓有真增量
  - 若后笔期望更低 → 加仓是负增量(越加越差)
入场口径: k板日次日的竞价 gap∈[4,8%] 硬边界, 开盘价成交(项目模拟口径)
出场口径: 持有到**断板**(首个非涨停日), 按T+1规则(买入当日不可卖)
排除: 300/688(项目买入规则), 一字板(开盘即涨停, gap窗已自然排除)
训练段 <2023 / 检验段 >=2023
只读本地 data/kline_data/
"""
import json, os, sys, glob

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
IPO_GUARD = 40
SPLIT = '2023-01-01'
SLOTS = 3


def is_lu(close, prev_close, cyb):
    limit_price = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit_price - 0.005


def walk(kl, lu, n, E, max_slots):
    """从 E 日开盘买入, 持有到断板(首个非涨停日)。返回 (buys[(day,frac)], exit_day)"""
    frac = 1.0 / max_slots if max_slots else 1.0
    buys = [(E, frac)]
    used = 1
    j = E
    while True:
        if j >= n:
            return buys, None                      # 数据尽头仍持仓
        if not lu[j]:
            ed = max(j, E + 1)                     # 断板日; T+1: 买入当日不可卖
            return buys, (ed if ed < n else None)
        nj = j + 1
        if nj >= n:
            return buys, None
        if max_slots is not None and used < max_slots:
            pc, op = kl[j].get('close'), kl[nj].get('open')
            if pc and op:
                g = (op - pc) / pc * 100
                if 4.0 <= g <= 8.0:
                    buys.append((nj, frac))
                    used += 1
        j = nj


def stat(vals, days=None):
    if not vals:
        return None
    s = sorted(vals)
    d = {'n': len(vals), 'mean': sum(vals) / len(vals), 'med': s[len(s) // 2],
         'up': sum(1 for v in vals if v > 0) / len(vals) * 100}
    if days:
        d['days'] = sum(days) / len(days)
    return d


def main():
    files = [f for f in glob.glob(os.path.join(KLINE_DIR, '*.json')) if os.path.basename(f)[:-5].isdigit()]
    print(f'K线库: {len(files)} 只')
    ev = {k: [] for k in range(1, 13)}
    entry_ev = {k: [] for k in range(1, 13)}       # 单笔入场(不加仓) → 断板, 用于看逐板级入场期望
    gap_ev = {k: [] for k in range(1, 13)}         # 全 gap 谱系(不受4-8%窗限制)

    for fp in files:
        code = os.path.basename(fp).replace('.json', '')
        if code.startswith(('30', '68')):
            continue
        cyb = False
        try:
            raw = json.load(open(fp, encoding='utf-8'))
            kl = raw['data'] if isinstance(raw, dict) else raw
        except Exception:
            continue
        n = len(kl)
        if n < 60:
            continue
        lu = [False] * n
        for i in range(1, n):
            c, pc = kl[i].get('close'), kl[i - 1].get('close')
            if c and pc:
                lu[i] = is_lu(c, pc, cyb)

        i = 1
        while i < n:
            if not lu[i]:
                i += 1
                continue
            start = i
            while i < n and lu[i]:
                i += 1
            if start < IPO_GUARD:
                continue
            for j0 in range(start, i):                 # j0 = 该段第 (j0-start+1) 板
                k = j0 - start + 1
                if k > 12 or j0 + 1 >= n:
                    continue
                E = j0 + 1
                c0, o1 = kl[j0].get('close'), kl[E].get('open')
                if not c0 or not o1:
                    continue
                gap = (o1 - c0) / c0 * 100
                if gap < -3.0 or gap > 10.5:                # 跌停开/一字开: 不可交易, 不进任何研究
                    continue
                seg = 'train' if kl[j0]['date'] < SPLIT else 'test'
                band = ('低开<=0' if gap <= 0 else '0~2' if gap < 2 else '2~4' if gap < 4
                        else '4~8' if gap <= 8 else '8~9.5' if gap < 9.5 else '9.5~10.5')

                b1, ex1 = walk(kl, lu, n, E, None)          # 全仓 → 持有到断板
                if not ex1 or not kl[ex1].get('close'):
                    continue
                r_all = (kl[ex1]['close'] / o1 - 1) * 100
                gap_ev[k].append({'seg': seg, 'band': band, 'ret': r_all})

                if not (4.0 <= gap <= 8.0):
                    continue
                b3, ex3 = walk(kl, lu, n, E, SLOTS)         # 分批(最多3笔)
                if not ex3 or not kl[ex3].get('close'):
                    continue
                r_sc = sum(f * (kl[ex3]['close'] / kl[d]['open'] - 1) for d, f in b3) * 100
                entry_ev[k].append({'seg': seg, 'ret': r_all})
                ev[k].append({'seg': seg, 'all': r_all, 'scale': r_sc,
                              'days': ex1 - E, 'adds': len(b3) - 1})

    BANDS = ('低开<=0', '0~2', '2~4', '4~8', '8~9.5', '9.5~10.5')
    print(f'\n{"="*128}')
    print('入场 gap 分档 × 板级 → 持有到断板收盘卖 (单笔全额, 检验段 2023+)   注: 9.5~10.5 档=开盘即近涨停, 多半买不进')
    print('=' * 128)
    print(f"{'板级':<5}" + ''.join(f'{b:>15}' for b in BANDS) + f"{'  [训练段同档对照]':>40}")
    print('-' * 128)
    for k in range(1, 13):
        s = [e for e in gap_ev[k] if e['seg'] == 'test']
        if len(s) < 20:
            continue
        cells = ''
        for b in BANDS:
            sub = [e['ret'] for e in s if e['band'] == b]
            cells += f"{sum(sub)/len(sub):>+10.2f}%({len(sub):>3})" if sub else f"{'-':>15}"
        ref = ''
        for b in ('0~2', '4~8', '8~9.5'):
            tr = [e['ret'] for e in gap_ev[k] if e['seg'] == 'train' and e['band'] == b]
            ref += f"{b}:{sum(tr)/len(tr):>+7.2f}%({len(tr):>3})" if tr else f"{b}:    -"
        print(f'{k:<5}{cells}{ref:>40}')

    print(f'\n{"="*112}')
    print('逐板级入场期望 (gap4-8% 开盘买入 → 持有到断板收盘卖, 无加仓, 单笔全额)')
    print('=' * 112)
    print(f"{'板级':<5}{'训练n':>7}{'训练均%':>10}{'检验n':>7}{'检验均%':>10}{'检验胜率':>10}")
    print('-' * 112)
    for k in range(1, 13):
        t = [e for e in entry_ev[k] if e['seg'] == 'train']
        s = [e for e in entry_ev[k] if e['seg'] == 'test']
        if len(t) < 5 or len(s) < 5:
            continue
        tm, sm = sum(e['ret'] for e in t) / len(t), sum(e['ret'] for e in s) / len(s)
        sc = sum(1 for e in s if e['ret'] > 0) / len(s) * 100
        print(f"{k:<5}{len(t):>7}{tm:>9.2f}%{len(s):>7}{sm:>9.2f}%{sc:>9.0f}%")

    print(f'\n{"="*112}')
    print(f'分批加仓(1/{SLOTS}×最多{SLOTS}笔) vs 首笔全仓  [同一入场事件集, 未投出的钱收益按0计]')
    print('=' * 112)
    print(f"{'板级':<5}{'检验n':>7}{'分批均%':>10}{'全仓均%':>10}{'分批-全仓':>11}"
          f"{'分批胜率':>10}{'全仓胜率':>10}{'均加仓笔':>10}")
    print('-' * 112)
    for k in range(1, 13):
        s = [e for e in ev[k] if e['seg'] == 'test']
        t = [e for e in ev[k] if e['seg'] == 'train']
        if len(s) < 5 or len(t) < 5:
            continue
        sm_sc = sum(e['scale'] for e in s) / len(s)
        sm_al = sum(e['all'] for e in s) / len(s)
        tm_sc = sum(e['scale'] for e in t) / len(t)
        tm_al = sum(e['all'] for e in t) / len(t)
        w_sc = sum(1 for e in s if e['scale'] > 0) / len(s) * 100
        w_al = sum(1 for e in s if e['all'] > 0) / len(s) * 100
        ad = sum(e['adds'] for e in s) / len(s)
        print(f"{k:<5}{len(s):>7}{sm_sc:>9.2f}%{sm_al:>9.2f}%{sm_sc - sm_al:>10.2f}%"
              f"{w_sc:>9.0f}%{w_al:>9.0f}%{ad:>10.2f}   (训练 {tm_sc:+.2f}/{tm_al:+.2f})")

    out = os.path.join(BASE, 'logs', 'research_scale_in.json')
    json.dump({'generated': '2026-09-21', 'split': SPLIT, 'slots': SLOTS,
               'rows': {str(k): ev[k] for k in ev}}, open(out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
