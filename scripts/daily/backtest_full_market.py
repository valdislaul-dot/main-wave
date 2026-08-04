"""
全市场回测: V3评分 + 龙虎榜增强
区间: 2026-03-03 → 2026-07-24 (5个月)
数据: kline_data/ + backtest_kline/ + dt_block/
"""
import json, os, sys, glob, math
from datetime import datetime, timedelta
from functools import lru_cache
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import score_v3, load_config

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 全局配置 ──
INIT_CASH = 200000
START = '2026-03-03'
END = '2026-07-24'

# ── 核心工具 ──
def is_lu(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0: return False
    return close >= round(prev_close * (1 + lpct), 2) - 0.005

def get_lp(code):
    return 0.20 if str(code).startswith(('30', '301', '688')) else 0.10

def clean_k(k):
    """所有价格字段统一转float并四舍五入2位"""
    for f in ['open', 'close', 'high', 'low', 'volume']:
        try: k[f] = round(float(k[f]), 2)
        except: k[f] = 0.0
    # 日期字段兼容
    if 'date' in k and 'day' not in k:
        k['day'] = k['date']
    return k


# ── 数据加载 ──
def load_kline_index():
    """建立全市场K线索引: code→[(date, file_idx, line_idx), ...]"""
    kline_dir = os.path.join(BASE, 'data', 'kline_data')
    stock_files = {}  # code → filepath
    for fn in os.listdir(kline_dir):
        if not fn.endswith('.json'): continue
        parts = fn.replace('.json', '').rsplit('_', 1)
        if len(parts) == 2:
            name, code = parts
            stock_files[code] = (name, os.path.join(kline_dir, fn))

    # 预加载日期范围
    date_range = {}
    for code, (name, fpath) in stock_files.items():
        try:
            with open(fpath, encoding='utf-8') as f:
                kls = json.load(f)
            if kls:
                date_range[code] = (kls[0].get('date', kls[0].get('day', '')),
                                    kls[-1].get('date', kls[-1].get('day', '')),
                                    name, fpath)
        except:
            pass

    return stock_files, date_range


def load_klines(fpath, target_date=None):
    """加载单只股的K线, 可选只加载到target_date"""
    try:
        with open(fpath, encoding='utf-8') as f:
            kls = json.load(f)
        for k in kls:
            clean_k(k)
        return kls
    except:
        return []


def load_dt_all():
    """加载龙虎榜数据 {YYYY-MM-DD: data}"""
    dt_dir = os.path.join(BASE, 'data', 'dt_block')
    dt_all = {}
    if os.path.exists(dt_dir):
        for fn in os.listdir(dt_dir):
            if fn.startswith('_') or not fn.endswith('.json'): continue
            dk = fn.replace('.json', '')
            for enc in ['utf-8', 'gbk']:
                try:
                    with open(os.path.join(dt_dir, fn), encoding=enc) as f:
                        dt_all[dk] = json.load(f)
                    break
                except: continue
    return dt_all


# ── V2评分 ──
def v2_score_simple(klines, idx, code):
    """委托给 scoring.score_v3, 保持向后兼容签名"""
    sub_klines = klines[:idx+1]
    score, details = score_v3(code, sub_klines, {})
    if score is None:
        return None, None, None
    return score, details, code


def dt_adjust(code, t_minus_1_date, dt_all):
    """DT因子调整: 席位级分析 (机构/拉萨/集中度/游资)"""
    day = dt_all.get(t_minus_1_date)
    if not day: return 0

    adj = 0
    for d in day.get('dragon_tiger', []):
        if d.get('code') != code:
            continue

        a = d.get('analysis', {})
        if not a:
            # fallback: 无席位数据时用概要
            nb = d.get('net_buy_wan', 0)
            bw = d.get('buy_wan', 0)
            if nb > 10000: adj += 3
            elif nb < -5000: adj -= 4
            if bw > 0 and nb / bw > 0.5: adj += 3
            break

        # ── 席位级因子 ──

        # 1. 机构买入占比 (核心信号)
        inst_buy = a.get('inst_buy_pct', 0)
        if inst_buy >= 40: adj += 10
        elif inst_buy >= 20: adj += 5
        elif inst_buy >= 10: adj += 2

        # 2. 机构卖出占比 (危险信号)
        inst_sell = a.get('inst_sell_pct', 0)
        if inst_sell >= 50: adj -= 8
        elif inst_sell >= 30: adj -= 4

        # 3. 机构净买入
        inst_net = a.get('inst_net_wan', 0)
        if inst_net > 5000: adj += 5
        elif inst_net < -5000: adj -= 5

        # 4. 拉萨席位 = 散户 (强烈负信号)
        if a.get('lhasa_flag', False):
            adj -= 8

        # 5. 买一集中度 (>25%一家独大)
        top1 = a.get('top1_pct', 0)
        if top1 > 30: adj -= 5
        elif top1 > 20: adj -= 2

        # 6. 知名游资参与 (正面, 有接力意愿)
        buyers = a.get('known_buyers', [])
        if buyers and len(buyers) >= 2:
            adj += 3

        # 7. 买方数量 (分散>集中)
        bc = a.get('buyer_count', 0)
        if bc >= 4: adj += 2

        break

    # 大宗交易
    for b in day.get('block_trades', []):
        if b.get('code') == code:
            prem = b.get('premium_pct', 0)
            amt = b.get('amount_wan', 0)
            if prem < -5 and amt > 500: adj -= 5
            elif prem < -3 and amt > 300: adj -= 3
            elif prem > 2 and amt > 300: adj += 4
            elif prem > 0 and amt > 500: adj += 2

    return adj


# ── 全市场涨停股扫描 ──
def scan_limit_ups(stock_files, date_range, target_date):
    """扫全市场, 找指定日期的涨停股"""
    lu_stocks = []
    count = 0
    for code, (name, fpath) in stock_files.items():
        if code.startswith(('300', '301', '688')): continue
        dr = date_range.get(code)
        if not dr: continue
        if target_date < dr[0] or target_date > dr[1]: continue
        count += 1

        try:
            kls = load_klines(fpath)
            for i, k in enumerate(kls):
                d = k.get('date', k.get('day', ''))
                if d == target_date and i >= 25:
                    lpct = get_lp(code)
                    if i > 0 and is_lu(k['close'], kls[i-1]['close'], lpct):
                        score, details, _ = v2_score_simple(kls, i, code)
                        if score is not None:
                            # 风控过滤
                            if details.get('true_one_line'): continue
                            if details.get('one_line') and details.get('cons', 1) >= 4: continue
                            lu_stocks.append({
                                'code': code, 'name': name,
                                'score': score, 'details': details,
                                'klines': kls, 'idx': i,
                            })
                    break
        except: pass

    return lu_stocks


# ── 模拟交易 ──
def run_sim(stock_files, date_range, trading_days, dt_all, use_dt):
    """核心模拟"""
    cash = INIT_CASH
    holding = None
    trades = []

    # T-1 前一天(首日不交易, 因为需要昨天涨停数据)
    prev_lu = None  # 上一日的涨停股列表

    for ti, today in enumerate(trading_days):
        # ── 卖出 (如果持仓) ──
        if holding:
            hc = holding['code']
            hn = holding['name']
            hkls = holding['klines']
            # 找today在持仓股K线中的位置
            sell_idx = None
            for i in range(holding['idx']+1, len(hkls)):
                if hkls[i].get('date', hkls[i].get('day', '')) == today:
                    sell_idx = i
                    break

            if sell_idx and sell_idx >= 2:
                sk = hkls[sell_idx]
                o_p = sk['open']; c_p = sk['close']; h_p = sk['high']
                pc = hkls[sell_idx-1]['close']

                y_lu = is_lu(hkls[sell_idx-1]['close'],
                            hkls[sell_idx-2]['close'] if sell_idx >= 2 else 0,
                            get_lp(hc))

                should_sell = False
                if y_lu and o_p < pc: should_sell = True
                elif not y_lu:
                    gap = (o_p - pc) / pc * 100 if pc > 0 else 0
                    if gap < 4: should_sell = True

                if should_sell:
                    sp = h_p if y_lu else (0.7 * (h_p + o_p) / 2 + 0.3 * c_p)
                    pnl = (sp - holding['bp']) / holding['bp'] * 100
                    cash += sp * holding['shares']
                    trades.append({
                        'buy_d': holding['bd'], 'sell_d': today,
                        'code': hc, 'name': hn,
                        'pnl': round(pnl, 2),
                        'score': holding['score'],
                        'dt_adj': holding.get('dt_adj', 0),
                    })
                    holding = None

        # ── 扫描今日涨停股(用于明天买入) ──
        # 先扫描
        lu_today = None

        # ── 买入 (基于昨天涨停) ──
        if holding is None and cash > 0 and prev_lu is not None:
            # 对昨天涨停股进行评分+买
            candidates = []
            for s in prev_lu:
                code = s['code']
                # 确认该股在today有交易(不是一字板封死)
                kls = s['klines']
                buy_idx = s['idx'] + 1  # 今天的位置
                if buy_idx >= len(kls): continue
                bk = kls[buy_idx]
                if bk.get('date', bk.get('day', '')) != today: continue

                o_p = bk['open']; c_p = bk['close']; h_p = bk['high']; l_p = bk['low']
                # 一字板封死买不到
                if h_p > 0 and l_p > 0 and abs(h_p - l_p) < 0.001 and abs(c_p - o_p) < 0.01:
                    continue

                # DT因子
                t_minus_1 = kls[s['idx']].get('date', kls[s['idx']].get('day', ''))
                dta = dt_adjust(code, t_minus_1, dt_all) if use_dt else 0

                candidates.append({
                    'code': code, 'name': s['name'],
                    'score': s['score'], 'vr': s['details']['vr'],
                    'open': o_p, 'close': c_p,
                    'dt_adj': dta,
                    'adj_score': s['score'] + dta,
                    'klines': kls, 'idx': buy_idx,
                })

            if candidates:
                # 排序
                sort_key = lambda x: x['adj_score'] if use_dt else x['score']
                candidates.sort(key=sort_key, reverse=True)
                top3 = candidates[:3]
                best = min(top3, key=lambda x: x['vr'])

                if best['score'] >= 10:
                    sh = int(cash / best['open'] / 100) * 100
                    if sh > 0:
                        cash -= sh * best['open']
                        holding = {
                            'code': best['code'], 'name': best['name'],
                            'bp': best['open'], 'shares': sh,
                            'bd': today, 'score': best['score'],
                            'dt_adj': best.get('dt_adj', 0),
                            'klines': best['klines'], 'idx': best['idx'],
                        }

        # 扫描今天涨停(供明天买入)
        if ti < len(trading_days) - 1:
            next_day = trading_days[ti + 1]
            # 提前扫: 只扫今天有数据且明天也有数据的
            prev_lu = scan_limit_ups(stock_files, date_range, today)

        # 进度
        if (ti + 1) % 20 == 0:
            pv = cash + (holding['shares'] * holding['klines'][holding['idx']]['close'] if holding else 0)
            print(f"  {today} ({ti+1}/{len(trading_days)}) 现金{cash:.0f} 持仓{'Y' if holding else 'N'} 总{pv:.0f}")

    # 清仓
    if holding:
        last_k = holding['klines'][-1]
        cash += holding['shares'] * last_k['close']

    return trades, cash


# ── 主流程 ──
def main():
    print("加载K线索引...")
    stock_files, date_range = load_kline_index()
    print(f"  全市场: {len(stock_files)} 只股")

    print("加载龙虎榜数据...")
    dt_all = load_dt_all()
    print(f"  dt_block: {len(dt_all)} 天")

    # 交易日列表
    trading_days = []
    d = datetime.strptime(START, '%Y-%m-%d')
    end_d = datetime.strptime(END, '%Y-%m-%d')
    while d <= end_d:
        if d.weekday() < 5:
            trading_days.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    print(f"  交易日: {len(trading_days)} ({trading_days[0]} → {trading_days[-1]})")

    # 跑回测
    print("\n[1/2] V2基线 (无DT因子)...")
    b_trades, b_cash = run_sim(stock_files, date_range, trading_days, dt_all, use_dt=False)
    b_ret = (b_cash - INIT_CASH) / INIT_CASH * 100
    b_wr = sum(1 for t in b_trades if t['pnl'] > 0) / max(len(b_trades), 1) * 100

    print("\n[2/2] V2+龙虎榜增强...")
    e_trades, e_cash = run_sim(stock_files, date_range, trading_days, dt_all, use_dt=True)
    e_ret = (e_cash - INIT_CASH) / INIT_CASH * 100
    e_wr = sum(1 for t in e_trades if t['pnl'] > 0) / max(len(e_trades), 1) * 100

    # ── 对比输出 ──
    print(f"\n{'='*65}")
    print(f"  回测: V2 基线 vs V2 + 龙虎榜/大宗增强")
    print(f"  区间: {START} -> {END} | 初始: {INIT_CASH:,}")
    print(f"  全市场: {len(stock_files)} 只 (排除300/301/688)")
    print(f"{'='*65}")
    print(f"  {'指标':<22} {'V2基线':>12} {'V2+DT':>12} {'差异':>10}")
    print(f"  {'-'*56}")
    print(f"  {'最终资产':<22} {b_cash:>12,.0f} {e_cash:>12,.0f} {e_cash-b_cash:>+10,.0f}")
    print(f"  {'收益率':<22} {b_ret:>+11.1f}% {e_ret:>+11.1f}% {e_ret-b_ret:>+9.1f}%")
    print(f"  {'交易笔数':<22} {len(b_trades):>12} {len(e_trades):>12} {len(e_trades)-len(b_trades):>+10}")
    print(f"  {'胜率':<22} {b_wr:>11.1f}% {e_wr:>11.1f}% {e_wr-b_wr:>+9.1f}%")

    if b_trades:
        ba = sum(t['pnl'] for t in b_trades) / len(b_trades)
        ea = sum(t['pnl'] for t in e_trades) / max(len(e_trades), 1)
        bm = min(t['pnl'] for t in b_trades)
        em = min(t['pnl'] for t in e_trades) if e_trades else 0
        print(f"  {'平均每笔':<22} {ba:>+11.2f}% {ea:>+11.2f}% {ea-ba:>+9.2f}%")
        print(f"  {'最大单笔亏损':<22} {bm:>+11.2f}% {em:>+11.2f}%")

    # DT信号统计
    dt_sigs = [t for t in e_trades if t.get('dt_adj', 0) != 0]
    if dt_sigs:
        pos = [t for t in dt_sigs if t['dt_adj'] > 0]
        neg = [t for t in dt_sigs if t['dt_adj'] < 0]
        print(f"\n  龙虎榜信号: {len(dt_sigs)}/{len(e_trades)}笔")
        if pos: print(f"    +正面{len(pos)}笔 均收益{sum(t['pnl'] for t in pos)/len(pos):+.2f}%")
        if neg: print(f"    -负面{len(neg)}笔 均收益{sum(t['pnl'] for t in neg)/len(neg):+.2f}%")

    # 结论
    diff = e_ret - b_ret
    if diff > 5:
        print(f"\n  [有效] DT因子提升 {diff:.1f}%")
    elif diff > 1:
        print(f"\n  [微弱] DT因子小幅提升 {diff:.1f}%")
    elif diff < -5:
        print(f"\n  [负面] DT因子降低收益 {diff:.1f}%")
    else:
        print(f"\n  [无显著差异] {diff:+.1f}%")

    # 保存
    out = {
        'baseline': {'trades': len(b_trades), 'cash': b_cash, 'ret': round(b_ret,1), 'wr': round(b_wr,1)},
        'enhanced': {'trades': len(e_trades), 'cash': e_cash, 'ret': round(e_ret,1), 'wr': round(e_wr,1)},
    }
    out_path = os.path.join(BASE, 'logs', 'backtest_dt_comparison.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n结果: {out_path}")


if __name__ == '__main__':
    main()
