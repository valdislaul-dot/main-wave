"""巨量分歧修复: 形态解构 + 修复涨停概率统计 (2026-09-08深夜, 用户追问)
==================================================================
用户问题:
  1. "1号涨停 2号巨量分歧 3号涨停"是否为修复行情的形态本体?
  2. 还有哪些类似形态可描述这一现象?
  3. 这种形态下一交易日(修复日)涨停的概率是多少?

口径(复用 analysis_temp_a_mode.py 信号定义, 只读数据):
  分歧日D-1: vr20>=2 且 (涨停+大振幅>=10% [涨停型] 或 断板摸板未封 [断板型])
  修复日D:   D-1次日 — 统计涨停概率(收盘pct>=9.8), 并按D-2是否涨停(连板分歧)分层
  另统计: 修复涨停票的T+1接力涨停率(接两维概率框架口径)
"""
import json, os, sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
from backtest_common import FIXED_POS

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
ZT_DIR = os.path.join(BASE, 'data', 'zt_pool')
WS, WE = '20251009', '20260907'


def load_klines():
    ktbl, cache = {}, {}
    def get(code):
        if code in cache:
            return cache[code]
        for enc in ('utf-8', 'gbk'):
            try:
                with open(os.path.join(KLINE_DIR, f'{code}.json'), encoding=enc) as f:
                    raw = json.load(f)
                kls = raw.get('data', raw) if isinstance(raw, dict) else raw
                cache[code] = kls
                return kls
            except Exception:
                continue
        cache[code] = None
        return None
    for fn in os.listdir(KLINE_DIR):
        if not fn.endswith('.json') or fn.startswith('._'):
            continue
        code = fn.replace('.json', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        kls = get(code)
        if kls:
            ktbl[code] = kls
    return ktbl


def load_pools():
    files = {}
    for d in (THS_DIR, ZT_DIR):
        for fn in os.listdir(d):
            if fn.endswith('.json') and fn[:8].isdigit():
                files[fn[:8]] = os.path.join(d, fn)
    pools = {}
    for ymd, path in files.items():
        if not (WS <= ymd <= WE):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                pools[ymd] = json.load(f)
        except UnicodeDecodeError:
            with open(path, encoding='gbk', errors='replace') as f:
                pools[ymd] = json.load(f)
    return pools


def is_lu(k, pk):
    if k.get('pct_change') is not None:
        return k['pct_change'] >= 9.8
    return pk and pk['close'] > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098


def bar_on(kls, date_fmt):
    if not kls:
        return None, None
    idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date_fmt), None)
    if idx is None or idx < 1:
        return None, None
    return kls[idx], kls[idx - 1]


def vr20(kls, idx):
    vols = [kls[t]['volume'] for t in range(max(0, idx - 20), idx) if kls[t].get('volume', 0) > 0]
    return kls[idx]['volume'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1.0


def pct(vals):
    return sum(1 for v in vals if v) / len(vals) * 100 if vals else 0.0


def show(name, n, lu):
    print(f'  {name:<34} {n:>5}笔   修复涨停率 {pct(lu):.1f}%')


def main():
    print(f'回测窗: {WS} ~ {WE} | 修复日=分歧日D-1的次日 | 涨停口径=收盘pct>=9.8')
    ktbl = load_klines()
    pools = load_pools()
    dates_fmt = sorted(f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in pools)
    print(f'K线{len(ktbl)}只 | 池文件{len(pools)}天 ({dates_fmt[0]} ~ {dates_fmt[-1]})')

    # ===== 信号枚举: 每个分歧日(D-1)的候选, 记录修复日(D)涨停与否 =====
    sigs = []
    for i, d in enumerate(dates_fmt):
        prev_d = dates_fmt[i - 1] if i > 0 else None
        if not prev_d or not d:
            continue
        seen, rows = set(), []
        rows += pools.get(prev_d.replace('-', ''), [])
        if i >= 2:
            rows += pools.get(dates_fmt[i - 2].replace('-', ''), [])
        temp = len(pools.get(prev_d.replace('-', ''), []))  # 分歧日温度近似=当日池涨停数
        for s in rows:
            code = str(s.get('code', ''))
            if code in seen or code.startswith(('300', '301', '688', '8', '9')):
                continue
            kls = ktbl.get(code)
            k1, k0 = bar_on(kls, prev_d)
            if not k1 or not k0:
                continue
            idx = next(j for j, x in enumerate(kls) if x.get('date') == prev_d)
            vr = vr20(kls, idx)
            if vr < 2.0:
                continue
            amp = (k1['high'] - k1['low']) / k0['close'] * 100 if k0['close'] else 0
            touch = k1['high'] >= k0['close'] * 1.098
            lu1 = is_lu(k1, k0)
            zt_type = 'lu' if lu1 and amp >= 10 else 'duan' if (not lu1 and touch) else None
            if not zt_type:
                continue
            seen.add(code)
            # 连板数(含分歧日) + D-2是否涨停
            cons = 1
            j = idx - 1
            while j >= 1 and is_lu(kls[j], kls[j - 1]):
                cons += 1
                j -= 1
            # 修复日D表现
            kD, kDp = bar_on(kls, d)
            if not kD or not kDp:
                continue
            gapD = (kD['open'] - kDp['close']) / kDp['close'] * 100
            rep_lu = is_lu(kD, kDp)
            # 修复涨停票的T+1接力(接两维概率框架)
            rep_t1 = None
            if rep_lu:
                kT1, kT1p = None, None
                if i + 1 < len(dates_fmt):
                    kT1, kT1p = bar_on(kls, dates_fmt[i + 1])
                if kT1 and kT1p:
                    rep_t1 = is_lu(kT1, kT1p)
            sigs.append({'code': code, 'dd': prev_d, 'type': zt_type, 'vr': vr, 'amp': amp,
                         'cons': cons, 'temp': temp, 'gapD': gapD, 'rep_lu': rep_lu,
                         't1': rep_t1})

    all_lu = [s['rep_lu'] for s in sigs]
    print(f'\n【全体分歧信号】{len(sigs)}笔 修复日涨停率 {pct(all_lu):.1f}%')
    for s in sigs:
        if s['code'] in ('601086', '605577'):
            print(f"  A案例: {s['code']} 分歧日{s['dd']} {s['type']} vr{s['vr']:.1f} "
                  f"振幅{s['amp']:.1f}% 连板{s['cons']} 修复涨停={'是' if s['rep_lu'] else '否'}")

    # ===== 形态解构: 涨停型(连板分歧/首板分歧) vs 断板型 =====
    print('\n【形态1: 1号涨停 2号巨量分歧(封板) 3号修复】 — 涨停型')
    lu_type = [s for s in sigs if s['type'] == 'lu']
    lu_chain = [s for s in lu_type if s['cons'] >= 2]   # 2号是连板中的分歧板(1号也涨停)
    lu_first = [s for s in lu_type if s['cons'] == 1]   # 2号是首板分歧(1号未涨停)
    show('涨停型·连板分歧(cons>=2, 用户问的形态)', len(lu_chain), [s['rep_lu'] for s in lu_chain])
    show('涨停型·首板分歧(cons=1)', len(lu_first), [s['rep_lu'] for s in lu_first])

    print('\n【形态2: 1号涨停 2号巨量炸板未封(断板) 3号反包】 — 断板型(国芳型)')
    duan = [s for s in sigs if s['type'] == 'duan']
    show('断板型·反包(N字)', len(duan), [s['rep_lu'] for s in duan])

    # ===== 连板数分层 =====
    print('\n【按分歧日连板数分层(全部信号)】')
    for c in (1, 2, 3, 4):
        sub = [s for s in sigs if s['cons'] == c]
        show(f'分歧日{c}板', len(sub), [s['rep_lu'] for s in sub])
    sub = [s for s in sigs if s['cons'] >= 5]
    show('分歧日5板+', len(sub), [s['rep_lu'] for s in sub])

    # ===== vr分层(涨停型) =====
    print('\n【涨停型按分歧日vr分层】')
    for lo, hi in ((2, 4), (4, 8), (8, 10), (10, 99)):
        sub = [s for s in lu_type if lo <= s['vr'] < hi]
        show(f'vr {lo}-{hi}', len(sub), [s['rep_lu'] for s in sub])

    # ===== 振幅分层(涨停型) =====
    print('\n【涨停型按分歧日振幅分层】')
    for lo, hi in ((10, 13), (13, 16), (16, 99)):
        sub = [s for s in lu_type if lo <= s['amp'] < hi]
        show(f'振幅 {lo}-{hi}%', len(sub), [s['rep_lu'] for s in sub])

    # ===== 温度分层(分歧日) =====
    print('\n【按分歧日温度分层(全部信号) — 冰点修复口径】')
    for lo, hi in ((0, 40), (40, 60), (60, 80), (80, 100), (100, 9999)):
        sub = [s for s in sigs if lo <= s['temp'] < hi]
        show(f'分歧日涨停数 {lo}-{hi if hi < 9999 else "+"}只', len(sub), [s['rep_lu'] for s in sub])
    ice = [s for s in sigs if s['temp'] < 40]
    ice_chain = [s for s in ice if s['type'] == 'lu' and s['cons'] >= 2]
    show('极弱(<40) × 连板分歧涨停型', len(ice_chain), [s['rep_lu'] for s in ice_chain])

    # ===== 修复涨停后的接力(T+1再涨停) =====
    print('\n【修复日涨停后的接力 — P(T+1涨停|T修复涨停)】')
    rep_hit = [s for s in sigs if s['rep_lu']]
    show('全体修复涨停票', len(rep_hit), [s['t1'] for s in rep_hit])
    rep_chain = [s for s in rep_hit if s['type'] == 'lu' and s['cons'] >= 2]
    show('连板分歧涨停型修复后', len(rep_chain), [s['t1'] for s in rep_chain])
    rep_duan = [s for s in rep_hit if s['type'] == 'duan']
    show('断板反包型修复后', len(rep_duan), [s['t1'] for s in rep_duan])

    # ===== 修复日gap分布(可买性) =====
    print('\n【修复日竞价gap分布(全体信号) — 可买性】')
    for lo, hi in ((0, 2), (2, 4), (4, 6), (6, 99)):
        sub = [s for s in sigs if lo <= s['gapD'] < hi]
        show(f'修复日高开 {lo}-{hi if hi < 99 else "+"}%', len(sub), [s['rep_lu'] for s in sub])
    sub = [s for s in sigs if s['gapD'] < 0]
    show('修复日低开', len(sub), [s['rep_lu'] for s in sub])


if __name__ == '__main__':
    main()
