# -*- coding: utf-8 -*-
"""一次性核验: A 实际买入的 T-1 板型分布 vs 当日涨停池基线分布
问题: screen_candidates 的「非一字优先」偏好(源自首个 commit a87cb59)是否与 A 行为冲突?
若 A 的一字/T字占比 ~= 池子基线 → 无偏好 → 该偏好是凭空加的; 若明显更低 → A 确实在回避。
"""
import json, os, sys, glob
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts', 'daily'))

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
KD = os.path.join(BASE, 'data', 'kline_data')


def board_type(k, prev_close):
    """单根K线的板型 (沿用 scoring.py:257-268 口径)"""
    h, l, o, c = k.get('high'), k.get('low'), k.get('open'), k.get('close')
    if None in (h, l, o, c) or h <= 0 or l <= 0:
        return None
    lpct = 0.20 if str(k.get('code', '')).startswith(('30', '68')) else 0.10
    if c < round(prev_close * (1 + lpct), 2) - 0.005:
        return None                      # 该日没涨停 → 不在池内
    if abs(h - l) < 0.001:
        return '一字'
    if h > l:
        us = (h - max(o, c)) / (h - l)
        body = abs(c - o) / (h - l)
        return 'T字' if (us < 0.1 and body < 0.1) else '换手'
    return '换手'


trades = json.load(open(os.path.join(BASE, 'backup', '_a_trades_recon.json'), encoding='utf-8'))
need_dates = {t['D'] for t in trades}
print(f'A交易 {len(trades)} 笔, 涉及 {len(need_dates)} 个买入日')

from collections import Counter
pool_bt = Counter()       # 池内全体: 各买入日 T-1 涨停股的板型
win_bt = Counter()        # 其中次日 gap 落在 [4,8] 的 (最接近A当年的实际操作域)
win0_bt = Counter()       # 其中次日 gap 落在 [0,8] 的 (现行窗口)
dirs = [''] + [os.path.basename(d) for d in glob.glob(os.path.join(KD, '*')) if os.path.isdir(d)]
scanned = 0
for sub in dirs:
    dpath = os.path.join(KD, sub) if sub else KD
    for fp in glob.glob(os.path.join(dpath, '*.json')):
        code = os.path.basename(fp)[:-5].split('_')[-1]
        if not code.isdigit() or len(code) != 6:
            continue
        try:
            raw = json.load(open(fp, encoding='utf-8'))
            kl = raw.get('data', raw) if isinstance(raw, dict) else raw
        except Exception:
            continue
        if not isinstance(kl, list):
            continue
        scanned += 1
        for i, k in enumerate(kl):
            d = str(k.get('date', ''))[:10]
            if i == 0 or d not in need_dates:
                continue
            pc = kl[i - 1].get('close')
            if not pc:
                continue
            bt = board_type(k, pc)
            if not bt:
                continue
            pool_bt[bt] += 1
            # 次日(买入日)竞价gap = 次日开盘 / 本日收盘 - 1
            if i + 1 < len(kl):
                o, h, l = kl[i + 1].get('open'), kl[i + 1].get('high'), kl[i + 1].get('low')
                c2 = k.get('close')
                if o and c2 and h is not None and l is not None:
                    gap = (o / c2 - 1) * 100
                    if abs(h - l) >= 0.001:          # 次日一字(买不到) 剔除
                        if 4.0 <= gap <= 8.0:
                            win_bt[bt] += 1
                        if 0.0 <= gap <= 8.0:
                            win0_bt[bt] += 1
print(f'扫描K线 {scanned} 只')

a_bt = Counter(t['bt'] for t in trades)
print()
print('%-28s %s' % ('', '一字      T字      换手     断板/其他'))
for name, c in (('A实际买入 (T-1板型)', a_bt), ('当日涨停池全体基线', pool_bt),
                ('  池∩次日gap 4-8%', win_bt), ('  池∩次日gap 0-8%', win0_bt)):
    tot = sum(c.values())
    cells = []
    for k in ('一字', 'T字', '换手', '断板/普通'):
        v = c.get(k, 0)
        cells.append(f'{v:>5}({v / tot * 100:>4.1f}%)' if tot else '     -')
    print('%-24s %s' % (name + f' n={tot}', ' '.join(cells)))

if pool_bt:
    tot = sum(pool_bt.values())
    pool_ol = (pool_bt.get('一字', 0) + pool_bt.get('T字', 0)) / tot * 100
    ta = sum(a_bt.values())
    a_ol = (a_bt.get('一字', 0) + a_bt.get('T字', 0)) / ta * 100
    print()
    print(f'一字/T字 占比:  A实买 {a_ol:.1f}%  vs  池子基线 {pool_ol:.1f}%   →  倍数 {a_ol / pool_ol:.2f}x' if pool_ol else '')
    print('倍数≈1 = A 对板型无偏好; <1 = A 回避一字/T字(该偏好成立); >1 = A 反而偏好一字/T字')
