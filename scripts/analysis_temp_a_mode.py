"""A模式 vs 现有体系 全样本回测 (2026-09-08晚, 用户提出"按A的来")
====================================================
背景: A两笔案例(国芳+8.4%/龙版+45%) — 巨量分歧次日开盘价买入, 均不在现有gap4-8%窗内
目的: 把A模式日线规则化, 全市场历史池回测, 与现有体系(V4评分+gap4-8%)同窗对比
研究脚本: 只读数据, 不写回定稿配置

A模式规则(日线近似, 源自 trader_a.strategy_notes + 两笔案例):
  候选: T-1涨停池股 + T-1断板摸板股(昨涨停今摸板未封)
  买入: T开盘价, 55%仓, 过滤(开一字/跌停开)
  卖出: 持有中每日: 涨停→持有; 断板→若H>=涨停价按涨停价卖(挂单), 否则开盘价卖;
        盘中low<=买价*0.9→硬止损
现有体系(对照组, 与backtest_v4口径一致):
  候选: T-1池内V4评分Top1, gap4-8%平滑窗, 过滤一字/4板+一字T字
  卖出: 昨涨停低开弱转强失败→HIGH卖 / 昨断板gap<4→HIGH卖 / 硬止损-10% / 否则留
"""
import json, os, sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
from backtest_common import FIXED_POS

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
ZT_DIR = os.path.join(BASE, 'data', 'zt_pool')
INIT = 200000
COST = 0.00125
WS, WE = '20251009', '20260907'  # 避开同花顺疯牛缺失段, 至最新


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
    """合并 history_ths + zt_pool(近期覆盖), 返回 {ymd: [rows]}"""
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


def backtest_a_mode(ktbl, pools, dates_fmt, parallel=True):
    """A模式: T-1涨停/断板摸板 → T开盘价买55% → 涨停持有, 断板兑现
    parallel=True: 多只并行(每只买入≤55%总资产, 现金可花完, A实盘口径)"""
    cash, positions, trades = INIT, [], []
    for i, d in enumerate(dates_fmt):
        prev_d = dates_fmt[i - 1] if i > 0 else None
        # ===== 卖出 =====
        if prev_d:
            survivors = []
            for p in positions:
                k, pk = bar_on(ktbl.get(p['code'], []), d)
                if not k:
                    survivors.append(p)
                    continue
                buy = p['buy_price']
                today_lu = is_lu(k, pk)
                loss_min = (k['low'] - buy) / buy * 100
                if loss_min <= -10:
                    sp = buy * 0.90
                    tag = '硬止损'
                elif today_lu:
                    sp, tag = None, None  # 继续持有
                else:
                    if k['high'] >= pk['close'] * 1.10 * 0.999:
                        sp = round(pk['close'] * 1.10, 2)
                        tag = '摸板涨停价卖'
                    else:
                        sp = k['open']
                        tag = '断板开盘卖'
                if sp:
                    pnl = (sp * (1 - COST) - buy) / buy * 100
                    cash += p['shares'] * sp * (1 - COST)
                    trades.append({'code': p['code'], 'buy': d, 'pnl': pnl, 'tag': tag, 'days': p['days']})
                else:
                    p['days'] += 1
                    survivors.append(p)
            positions = survivors
        # ===== 买入 =====
        if prev_d:
            rows = pools.get(prev_d.replace('-', ''), [])
            cands = []
            seen = set()

            def try_add(code):
                """分歧日D-1判定: vr>=2 且 (涨停+大振幅>=10% 或 断板摸板未封)"""
                if code in seen or code.startswith(('300', '301', '688', '8', '9')):
                    return
                kls = ktbl.get(code)
                if not kls:
                    return
                k1, k0 = bar_on(kls, prev_d)
                if not k1 or not k0:
                    return
                idx = next(i for i, x in enumerate(kls) if x.get('date') == prev_d)
                vr = vr20(kls, idx)
                if vr < 2.0:
                    return
                amp = (k1['high'] - k1['low']) / k0['close'] * 100 if k0['close'] else 0
                touch = k1['high'] >= k0['close'] * 1.098
                lu1 = is_lu(k1, k0)
                if not ((lu1 and amp >= 10) or (not lu1 and touch)):
                    return
                seen.add(code)
                cands.append((vr, code, kls))

            # 分歧日池内股(涨停分歧类, 如龙版09-02)
            for s in rows:
                try_add(str(s.get('code', '')))
            # D-2池内断板摸板股(如国芳09-04, 断板日不在池)
            if i >= 2:
                prev2 = dates_fmt[i - 2]
                for s in pools.get(prev2.replace('-', ''), []):
                    try_add(str(s.get('code', '')))
            # 分歧越剧烈(vr越高)越优先
            cands.sort(key=lambda x: -x[0])
            # 买入日 T 开盘价 (并行: 每只≤55%总资产, 现金花完为止)
            total = cash + sum(p['shares'] * p['buy_price'] for p in positions)
            for _, code, kls in cands:
                k, pk = bar_on(kls, d)
                if not k or k['open'] <= 0:
                    continue
                # 开一字买不进 / 开跌停排除
                if k['open'] >= pk['close'] * 1.098:
                    continue
                if k['open'] <= pk['close'] * 0.90:
                    continue
                price = k['open'] * (1 + COST)
                budget = min(cash, total * FIXED_POS)
                shares = int(budget / price / 100) * 100
                if shares <= 0:
                    continue
                cash -= shares * price
                positions.append({'code': code, 'buy_price': price, 'shares': shares, 'days': 0})
                if cash < price * 100:
                    break
    final = cash
    for p in positions:
        kls = ktbl.get(p['code'])
        final += p['shares'] * kls[-1]['close'] * (1 - COST) if kls else p['shares'] * p['buy_price']
    return final, trades


def backtest_a_signals(ktbl, pools, dates_fmt):
    """A模式信号全样本: 每个分歧候选独立一笔(无资金约束), 买入=次日开盘, 卖出=涨停持有到断板兑现
    口径=模式质量本身, 不受资金序列/持仓冲突影响; A两笔案例应出现在这里"""
    trades = []
    for i, d in enumerate(dates_fmt):
        prev_d = dates_fmt[i - 1] if i > 0 else None
        if not prev_d:
            continue
        seen, cands = set(), []
        rows = pools.get(prev_d.replace('-', ''), [])
        if i >= 2:
            rows = rows + pools.get(dates_fmt[i - 2].replace('-', ''), [])
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
            if not ((lu1 and amp >= 10) or (not lu1 and touch)):
                continue
            seen.add(code)
            cands.append((vr, code, kls))
        for _, code, kls in cands:
            k, pk = bar_on(kls, d)
            if not k or k['open'] <= 0 or k['open'] >= pk['close'] * 1.098 or k['open'] <= pk['close'] * 0.90:
                continue
            buy = k['open'] * (1 + COST)
            # 按A卖出规则走后续K线
            idx = next(j for j, x in enumerate(kls) if x.get('date') == d)
            pnl, days, tag = None, 0, None
            j = idx
            while pnl is None and j + 1 < len(kls):
                j += 1
                days += 1
                kk, kp = kls[j], kls[j - 1]
                if (kk['low'] - buy) / buy <= -0.10:
                    pnl = (buy * 0.90 - buy) / buy * 100
                    tag = '硬止损'
                elif is_lu(kk, kp):
                    continue  # 涨停持有
                elif kk['high'] >= kp['close'] * 1.10 * 0.999:
                    pnl = (round(kp['close'] * 1.10, 2) * (1 - COST) - buy) / buy * 100
                    tag = '摸板涨停价卖'
                else:
                    pnl = (kk['open'] * (1 - COST) - buy) / buy * 100
                    tag = '断板开盘卖'
            if pnl is None and j + 1 >= len(kls) and j > idx:
                pnl = (kls[j]['close'] * (1 - COST) - buy) / buy * 100
                tag = '期末估值'
            if pnl is not None:
                trades.append({'code': code, 'buy': d, 'pnl': pnl, 'tag': tag, 'days': days})
    return trades


def backtest_current(ktbl, pools, dates_fmt):
    """现有体系: V4评分Top1 + gap4-8平滑窗 + 决策树卖出 + 开盘价 (与backtest_v4口径一致)"""
    with open(os.path.join(BASE, 'data', 'scoring_config.json'), encoding='utf-8') as f:
        norm = json.load(f)['v4']['normalize']
    from collections import Counter
    cash, pos, trades = INIT, None, []
    for i, d in enumerate(dates_fmt):
        prev_d = dates_fmt[i - 1] if i > 0 else None
        # 卖出(决策树: 硬止损/昨涨停低开弱转强失败卖HIGH/昨断板gap<4卖HIGH/否则留)
        if pos and prev_d:
            k, pk = bar_on(ktbl.get(pos['code'], []), d)
            if k:
                buy = pos['buy_price']
                yest_lu = is_lu(pk, ktbl[pos['code']][next(i2 for i2, x in enumerate(ktbl[pos['code']]) if x.get('date') == prev_d) - 1] if prev_d else None)
                today_lu = is_lu(k, pk)
                gap = (k['open'] - pk['close']) / pk['close'] * 100
                loss_min = (k['low'] - buy) / buy * 100
                if loss_min <= -10:
                    sp = buy * 0.90
                elif yest_lu and gap < 0 and not today_lu:
                    sp = k['high']
                elif not yest_lu and gap < 4 and not today_lu:
                    sp = k['high']
                else:
                    sp = None
                if sp:
                    pnl = (sp * (1 - COST) - buy) / buy * 100
                    cash += pos['shares'] * sp * (1 - COST)
                    trades.append({'code': pos['code'], 'buy': d, 'pnl': pnl})
                    pos = None
        # 买入: T-1池内V4评分Top1, gap4-8
        if pos is None and prev_d:
            rows = pools.get(prev_d.replace('-', ''), [])
            cands = []
            for s in rows:
                code = str(s.get('code', ''))
                if not code or code.startswith(('300', '301', '688', '8', '9')):
                    continue
                kls = ktbl.get(code)
                k1, k0 = bar_on(kls, prev_d)
                if not k1:
                    continue
                cons = 1
                idx = next(i for i, x in enumerate(kls) if x.get('date') == prev_d)
                j = idx - 1
                while j >= 1 and is_lu(kls[j], kls[j - 1]):
                    cons += 1
                    j -= 1
                lu_px = round(k0['close'] * 1.10, 2)
                btype = '一字' if (k1['open'] >= lu_px - 0.005 and k1['low'] >= lu_px - 0.005) else 'T字' if (k1['open'] >= lu_px - 0.005 and k1['close'] >= lu_px - 0.005) else '换手'
                if btype == '一字' or (cons >= 4 and btype in ('一字', 'T字')):
                    continue
                vr = vr20(kls, idx)
                gap = (k1['open'] - k0['close']) / k0['close'] * 100
                try:
                    to = float(s.get('turnover_rate', 0) or 0)
                except Exception:
                    to = 0
                f = {
                    'vr': norm['vr'].get(('<0.5' if vr < 0.5 else '0.5-1' if vr < 1 else '1-2' if vr < 2 else '2-4' if vr < 4 else '>=4'), 50),
                    'gap': norm['gap'].get(('<0' if gap < 0 else '0-2' if gap < 2 else '2-4' if gap < 4 else '4-6' if gap < 6 else '6-8' if gap < 8 else '8-10' if gap < 10 else '>=10'), 50),
                    'board_type': norm['board_type'].get(btype, 50),
                    'cons': norm['cons'].get(('1' if cons == 1 else '2' if cons == 2 else '3' if cons == 3 else '4' if cons == 4 else '5+'), 55),
                    'turnover': norm.get('turnover', {}).get(('<2' if to < 2 else '2-20' if to < 20 else '>=20'), 50),
                }
                score = sum(f.values()) / len(f)
                cands.append((score, code))
            cands.sort(key=lambda x: -x[0])
            for score, code in cands:
                kls = ktbl.get(code)
                k, pk = bar_on(kls, d)
                if not k:
                    continue
                gap = (k['open'] - pk['close']) / pk['close'] * 100
                if not (4.0 <= gap <= 8.0):
                    continue
                price = k['open'] * (1 + COST)
                budget = cash * FIXED_POS
                shares = int(min(cash, budget) / price / 100) * 100
                if shares <= 0:
                    continue
                cash -= shares * price
                pos = {'code': code, 'buy_price': price, 'shares': shares}
                break
    final = cash
    if pos:
        kls = ktbl.get(pos['code'])
        final += pos['shares'] * kls[-1]['close'] * (1 - COST) if kls else pos['shares'] * pos['buy_price']
    return final, trades


def backtest_fusion(ktbl, pools, dates_fmt):
    """融合: 现有通道(V4评分Top1 gap4-8)优先 → 无票时分歧修复通道(2-3板+vr2-10+gap2-4)补位
    卖出统一=现有决策树口径"""
    with open(os.path.join(BASE, 'data', 'scoring_config.json'), encoding='utf-8') as f:
        norm = json.load(f)['v4']['normalize']
    cash, pos, trades = INIT, None, []
    chan = {'existing': 0, 'divergence': 0}

    def score_v4(s, k1, k0, prev_d, kls):
        code = str(s.get('code', ''))
        cons = 1
        idx = next(i for i, x in enumerate(kls) if x.get('date') == prev_d)
        j = idx - 1
        while j >= 1 and is_lu(kls[j], kls[j - 1]):
            cons += 1
            j -= 1
        lu_px = round(k0['close'] * 1.10, 2)
        btype = '一字' if (k1['open'] >= lu_px - 0.005 and k1['low'] >= lu_px - 0.005) else 'T字' if (k1['open'] >= lu_px - 0.005 and k1['close'] >= lu_px - 0.005) else '换手'
        if btype == '一字' or (cons >= 4 and btype in ('一字', 'T字')):
            return None
        vr = vr20(kls, idx)
        gap = (k1['open'] - k0['close']) / k0['close'] * 100
        try:
            to = float(s.get('turnover_rate', 0) or 0)
        except Exception:
            to = 0
        f = {
            'vr': norm['vr'].get(('<0.5' if vr < 0.5 else '0.5-1' if vr < 1 else '1-2' if vr < 2 else '2-4' if vr < 4 else '>=4'), 50),
            'gap': norm['gap'].get(('<0' if gap < 0 else '0-2' if gap < 2 else '2-4' if gap < 4 else '4-6' if gap < 6 else '6-8' if gap < 8 else '8-10' if gap < 10 else '>=10'), 50),
            'board_type': norm['board_type'].get(btype, 50),
            'cons': norm['cons'].get(('1' if cons == 1 else '2' if cons == 2 else '3' if cons == 3 else '4' if cons == 4 else '5+'), 55),
            'turnover': norm.get('turnover', {}).get(('<2' if to < 2 else '2-20' if to < 20 else '>=20'), 50),
        }
        return sum(f.values()) / len(f)

    def try_buy(code, price, ch):
        nonlocal cash, pos, trades
        budget = cash * FIXED_POS
        shares = int(min(cash, budget) / price / 100) * 100
        if shares <= 0:
            return False
        cash -= shares * price
        pos = {'code': code, 'buy_price': price, 'shares': shares, 'chan': ch}
        return True

    for i, d in enumerate(dates_fmt):
        prev_d = dates_fmt[i - 1] if i > 0 else None
        # ===== 卖出(决策树, 与现有体系一致) =====
        if pos and prev_d:
            k, pk = bar_on(ktbl.get(pos['code'], []), d)
            if k:
                buy = pos['buy_price']
                yest_lu = is_lu(pk, ktbl[pos['code']][next(i2 for i2, x in enumerate(ktbl[pos['code']]) if x.get('date') == prev_d) - 1] if prev_d else None)
                today_lu = is_lu(k, pk)
                gap = (k['open'] - pk['close']) / pk['close'] * 100
                loss_min = (k['low'] - buy) / buy * 100
                if loss_min <= -10:
                    sp = buy * 0.90
                elif yest_lu and gap < 0 and not today_lu:
                    sp = k['high']
                elif not yest_lu and gap < 4 and not today_lu:
                    sp = k['high']
                else:
                    sp = None
                if sp:
                    pnl = (sp * (1 - COST) - buy) / buy * 100
                    cash += pos['shares'] * sp * (1 - COST)
                    trades.append({'code': pos['code'], 'buy': d, 'pnl': pnl, 'chan': pos.get('chan', 'x')})
                    pos = None
        # ===== 买入 =====
        if pos is None and prev_d:
            rows = pools.get(prev_d.replace('-', ''), [])
            # 通道1: 现有 V4评分Top1 gap4-8
            cands = []
            for s in rows:
                code = str(s.get('code', ''))
                if not code or code.startswith(('300', '301', '688', '8', '9')):
                    continue
                kls = ktbl.get(code)
                k1, k0 = bar_on(kls, prev_d)
                if not k1:
                    continue
                sc = score_v4(s, k1, k0, prev_d, kls)
                if sc is not None:
                    cands.append((sc, code))
            cands.sort(key=lambda x: -x[0])
            bought = False
            for sc, code in cands:
                kls = ktbl.get(code)
                k, pk = bar_on(kls, d)
                if not k:
                    continue
                gap = (k['open'] - pk['close']) / pk['close'] * 100
                if not (4.0 <= gap <= 8.0):
                    continue
                if try_buy(code, k['open'] * (1 + COST), 'e'):
                    chan['existing'] += 1
                    bought = True
                    break
            # 通道2: 分歧修复(2-3板+vr2-10+gap2-4)
            if not bought:
                cands2 = []
                seen = set()
                rows2 = rows
                if i >= 2:
                    rows2 = rows2 + pools.get(dates_fmt[i - 2].replace('-', ''), [])
                for s in rows2:
                    code = str(s.get('code', ''))
                    if code in seen or code.startswith(('300', '301', '688', '8', '9')):
                        continue
                    seen.add(code)
                    kls = ktbl.get(code)
                    k1, k0 = bar_on(kls, prev_d)
                    if not k1 or not k0:
                        continue
                    idx = next(j2 for j2, x in enumerate(kls) if x.get('date') == prev_d)
                    vr = vr20(kls, idx)
                    if not (2.0 <= vr < 10.0):
                        continue
                    amp = (k1['high'] - k1['low']) / k0['close'] * 100 if k0['close'] else 0
                    touch = k1['high'] >= k0['close'] * 1.098
                    lu1 = is_lu(k1, k0)
                    if not ((lu1 and amp >= 10) or (not lu1 and touch)):
                        continue
                    cons = 1
                    j = idx - 1
                    while j >= 1 and is_lu(kls[j], kls[j - 1]):
                        cons += 1
                        j -= 1
                    if cons not in (2, 3):
                        continue
                    cands2.append((vr, code))
                cands2.sort(key=lambda x: -x[0])
                for vr, code in cands2:
                    kls = ktbl.get(code)
                    k, pk = bar_on(kls, d)
                    if not k or k['open'] <= 0:
                        continue
                    if k['open'] >= pk['close'] * 1.098 or k['open'] <= pk['close'] * 0.90:
                        continue
                    gap = (k['open'] - pk['close']) / pk['close'] * 100
                    if not (2.0 <= gap < 4.0):
                        continue
                    if try_buy(code, k['open'] * (1 + COST), 'e'):
                        chan['divergence'] += 1
                        break
    final = cash
    if pos:
        kls = ktbl.get(pos['code'])
        final += pos['shares'] * kls[-1]['close'] * (1 - COST) if kls else pos['shares'] * pos['buy_price']
    return final, trades, chan


def report(name, final, trades):
    n = len(trades)
    wr = sum(1 for t in trades if t['pnl'] > 0) / n * 100 if n else 0
    avg = sum(t['pnl'] for t in trades) / n if n else 0
    if final is None:
        print(f'{name}: {n}笔 | 胜率{wr:.1f}% | 均笔{avg:+.2f}%')
    else:
        ret = (final / INIT - 1) * 100
        print(f'{name}: 收益{ret:+.1f}% | {n}笔 | 胜率{wr:.1f}% | 均笔{avg:+.2f}%')
    if trades:
        wins = sorted([t['pnl'] for t in trades if t['pnl'] > 0])
        losses = sorted([t['pnl'] for t in trades if t['pnl'] <= 0])
        print(f'  最大赢{max(t["pnl"] for t in trades):+.1f}% 最大亏{min(t["pnl"] for t in trades):+.1f}% | 盈亏比{sum(wins)/len(wins)/abs(sum(losses)/len(losses)) if wins and losses else 0:.2f}')
    if final is None:
        return None
    return ret


def main():
    print(f'回测窗: {WS} ~ {WE} | 仓位: A式恒定{FIXED_POS*100:.0f}% | 成本+滑点 {COST*2*100:.2f}%往返')
    ktbl = load_klines()
    print(f'K线: {len(ktbl)}只(主板)')
    pools = load_pools()
    dates_fmt = sorted(f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in pools)
    print(f'池文件: {len(pools)}天 ({dates_fmt[0]} ~ {dates_fmt[-1]})')

    print('\n' + '=' * 60)
    print('【A模式·信号全样本】每个分歧候选独立一笔(模式质量口径)')
    print('=' * 60)
    trades_s = backtest_a_signals(ktbl, pools, dates_fmt)
    report('A模式信号', None, trades_s)

    print()
    print('=' * 60)
    print('【A模式·并行资金】每只≤55%总资产, 现金花完为止')
    print('=' * 60)
    final_a, trades_a = backtest_a_mode(ktbl, pools, dates_fmt, parallel=True)
    report('A模式资金', final_a, trades_a)

    print()
    print('=' * 60)
    print('【现有体系】V4评分Top1 + gap4-8%窗 + 决策树卖出')
    print('=' * 60)
    final_c, trades_c = backtest_current(ktbl, pools, dates_fmt)
    report('现有体系', final_c, trades_c)

    print()
    print('=' * 60)
    print('【融合】现有通道优先 + 分歧修复通道(2-3板+vr2-10+gap2-4)补位')
    print('=' * 60)
    final_f, trades_f, chan_f = backtest_fusion(ktbl, pools, dates_fmt)
    report('融合体系', final_f, trades_f)
    print(f'  通道构成: 现有{chan_f["existing"]}笔 + 分歧补位{chan_f["divergence"]}笔')
    div_pnl = [t['pnl'] for t in trades_f if t.get('chan') == 'd']
    if div_pnl:
        print(f'  分歧通道贡献: {len(div_pnl)}笔 均{sum(div_pnl)/len(div_pnl):+.2f}%')

    # 检查A两笔案例是否在信号样本中
    print()
    print('A两笔案例复现检查(信号口径):')
    for t in trades_s:
        if t['code'] in ('601086', '605577'):
            print(f'  {t["code"]} 买入日{t["buy"]} 持有{t["days"]}天 {t["tag"]} {t["pnl"]:+.2f}%')
    hit = [t for t in trades_s if t['code'] in ('601086', '605577')]
    if not hit:
        print('  (未捕获——需检查分歧日判定口径)')


if __name__ == '__main__':
    main()
