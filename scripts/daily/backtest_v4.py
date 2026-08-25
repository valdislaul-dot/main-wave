"""V4权重搜索 (2026-08-25)
架构: 预计算1年每日每股票的10因子归一化分(0-100) → 权重线性加权得总分
      权重搜索: 初始权重±随机扰动, 目标=收益60%+胜率40%(两窗交叉)
交易口径(用户定稿): 开盘价进出(含成本) / Top1优先买不进依次向下 / 弱市半仓强市全仓
窗口: 强市窗2026-03-04~07-24 + 弱市窗2025-10-09~2026-03-03 (避开同花顺9-10月缺失段)
用法: python backtest_v4.py            # 运行搜索(500组)
      python backtest_v4.py --best     # 仅跑最优权重
"""
import json, os, sys, random
from datetime import datetime, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
INIT = 200000
COST = 0.00125   # 滑点+佣金
FACTORS = ['vr', 'gap', 'board_type', 'cons', 'dow', 'seal', 'zhaban', 'sector', 'divergence', 'dt_risk']


def load_config_v4():
    with open(os.path.join(BASE, 'data', 'scoring_config.json'), encoding='utf-8') as f:
        cfg = json.load(f)
    return cfg['v4']


def main():
    cfg4 = load_config_v4()
    norm = cfg4['normalize']

    # ===== 预计算: 每日每股票因子原始值 =====
    # {date_fmt: {code: {vr, gap, board_type, cons, dow, seal, zhaban, sector, divergence, dt_risk_p}}}
    klines_cache = {}
    def get_klines(code):
        if code in klines_cache:
            return klines_cache[code]
        for enc in ('utf-8', 'gbk'):
            try:
                with open(os.path.join(KLINE_DIR, f'{code}.json'), encoding=enc) as f:
                    raw = json.load(f)
                kls = raw.get('data', raw) if isinstance(raw, dict) else raw
                klines_cache[code] = kls
                return kls
            except Exception:
                continue
        klines_cache[code] = None
        return None

    def is_lu_pct(k, pk):
        if k.get('pct_change') is not None:
            return k['pct_change'] >= 9.8
        return pk and pk['close'] > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098

    factor_days = {}   # date_fmt -> {code: {factor: norm_score}}
    # 先加载1年K线表(内存)
    ktbl = {}
    for fn in os.listdir(KLINE_DIR):
        if not fn.endswith('.json') or fn.startswith('._'):
            continue
        code = fn.replace('.json', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        kls = get_klines(code)
        if kls:
            ktbl[code] = kls
    print(f'K线: {len(ktbl)}只')

    ths_files = sorted(fn for fn in os.listdir(THS_DIR) if fn.endswith('.json'))
    # 两窗日期
    strong_dates = []
    weak_dates = []
    for fn in ths_files:
        ymd = fn.replace('.json', '')
        if '20260304' <= ymd <= '20260724':
            strong_dates.append(ymd)
        elif '20251009' <= ymd <= '20260303':
            weak_dates.append(ymd)
    all_dates = sorted(set(strong_dates + weak_dates))
    print(f'回测日: 强市窗{len(strong_dates)}天 + 弱市窗{len(weak_dates)}天')

    # 每日池 + 因子
    for ymd in all_dates:
        date_fmt = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
        with open(os.path.join(THS_DIR, f'{ymd}.json'), encoding='utf-8') as f:
            info = json.load(f)
        day_map = {}
        # 题材热度(当日)
        from collections import Counter
        word_freq = Counter()
        entries = []
        for s in info:
            code = str(s.get('code', ''))
            if not code or code.startswith(('300', '301', '688', '8', '9')):
                continue
            reason = s.get('reason_type', '')
            ws = [w for w in str(reason).replace('，', '+').split('+') if w.strip()]
            for w in ws:
                word_freq[w] += 1
            entries.append((code, s, ws))
        for code, s, ws in entries:
            kls = ktbl.get(code)
            if not kls:
                continue
            idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date_fmt), None)
            if idx is None or idx < 20:
                continue
            k = kls[idx]
            pk = kls[idx - 1]
            # 连板数
            cons = 1
            j = idx - 1
            while j >= 1:
                if is_lu_pct(kls[j], kls[j - 1]):
                    cons += 1
                    j -= 1
                else:
                    break
            # 量比20
            vols = [kls[t]['volume'] for t in range(max(0, idx - 20), idx) if kls[t].get('volume', 0) > 0]
            vr = k['volume'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1.0
            # gap(T-1日)
            gap = (k['open'] - pk['close']) / pk['close'] * 100 if pk['close'] > 0 else 0
            # 板型
            lu_price = round(pk['close'] * 1.10, 2)
            is_yz = k['open'] >= lu_price - 0.005 and k['low'] >= lu_price - 0.005
            is_tz = k['open'] >= lu_price - 0.005 and k['close'] >= lu_price - 0.005 and k['low'] < lu_price - 0.005
            board_type = '一字' if is_yz else ('T字' if is_tz else '换手')
            # 周几(买入日)
            dow = ['周一', '周二', '周三', '周四', '周五'][datetime.strptime(date_fmt, '%Y-%m-%d').weekday()]
            # 封板/炸板
            try:
                seal_hm = datetime.fromtimestamp(int(s.get('first_limit_up_time'))).strftime('%H%M')
            except Exception:
                seal_hm = '1500'
            seal_b = '<5min' if seal_hm <= '0935' else ('5-10min' if seal_hm <= '0940' else (
                '10-30min' if seal_hm <= '1000' else ('30-60min' if seal_hm <= '1030' else '>60min')))
            zh = int(s.get('open_num', 0) or 0)
            zh_b = '0' if zh == 0 else ('1' if zh == 1 else ('2' if zh == 2 else '3+'))
            # 题材热度
            heat = max(word_freq[w] for w in ws) if ws else 0
            sec_b = '<3' if heat < 3 else ('3-4' if heat < 5 else ('5-9' if heat < 10 else '>=10'))
            # 分歧
            div_b = '分歧' if (zh >= 1 and vr >= 1.5) else '非分歧'
            # 跌停风险概率(全路径模型查表)
            if cons >= 3:
                dt_p = 30.5
            elif cons == 2:
                dt_p = 22.0
            elif vr >= 4:
                dt_p = 9.5
            elif vr < 1:
                dt_p = 4.1
            else:
                dt_p = 10.7
            # 归一化
            f = {
                'vr': norm['vr'].get(('<0.5' if vr < 0.5 else '0.5-1' if vr < 1 else '1-2' if vr < 2 else '2-4' if vr < 4 else '>=4'), 50),
                'gap': norm['gap'].get(('<0' if gap < 0 else '0-2' if gap < 2 else '2-4' if gap < 4 else '4-6' if gap < 6 else '6-8' if gap < 8 else '8-10' if gap < 10 else '>=10'), 50),
                'board_type': norm['board_type'].get(board_type, 50),
                'cons': norm['cons'].get(('1' if cons == 1 else '2' if cons == 2 else '3' if cons == 3 else '4' if cons == 4 else '5+'), 55),
                'dow': norm['dow'].get(dow, 55),
                'seal': norm['seal'].get(seal_b, 60),
                'zhaban': norm['zhaban'].get(zh_b, 70),
                'sector': norm['sector'].get(sec_b, 70),
                'divergence': norm['divergence'].get(div_b, 55),
                'dt_risk': max(10, min(100, 100 - (dt_p - 5) * 3)),
            }
            day_map[code] = (f, board_type, cons, k)
        factor_days[date_fmt] = day_map
    print(f'因子预计算: {len(factor_days)}天')

    # ===== 交易模拟 =====
    def simulate(weights, dates_fmt, pos_pct):
        cash = INIT
        pos = None
        trades = []
        for i, d in enumerate(dates_fmt):
            # 卖出
            if pos is not None and i > 0:
                prev_d = dates_fmt[i - 1]
                kls = ktbl.get(pos['code'])
                if kls:
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    if idx1 is not None and idx0 is not None:
                        k1, k0 = kls[idx1], kls[idx0]
                        yest_lu = is_lu_pct(k1, kls[idx1 - 1] if idx1 > 0 else None)
                        today_lu = is_lu_pct(k0, kls[idx0 - 1] if idx0 > 0 else None)
                        gap = (k0['open'] - k1['close']) / k1['close'] * 100
                        loss = (k0['open'] - pos['buy_price']) / pos['buy_price'] * 100
                        if loss <= -10:
                            action = 'sell'
                        elif yest_lu and gap < 0:
                            action = 'sell'
                        elif yest_lu and today_lu:
                            action = 'hold'
                        elif yest_lu:
                            action = 'sell'
                        elif gap >= 4:
                            action = 'hold'
                        else:
                            action = 'sell'
                        if action == 'sell':
                            sell_price = k0['open'] * (1 - COST)
                            pnl = (sell_price - pos['buy_price']) / pos['buy_price'] * 100
                            cash += pos['shares'] * sell_price
                            trades.append({'pnl': pnl})
                            pos = None
            # 买入
            if pos is None and i > 0:
                prev_d = dates_fmt[i - 1]
                cands = []
                for code, (f, btype, cons, k) in factor_days.get(prev_d, {}).items():
                    if btype == '一字' or cons >= 4:
                        continue
                    score = sum(weights[fac] * f[fac] for fac in FACTORS) / 100.0
                    cands.append((score, code))
                cands.sort(key=lambda x: -x[0])
                for score, code in cands:
                    if score < 50:
                        break
                    kls = ktbl.get(code)
                    if not kls:
                        continue
                    idx0 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == d), None)
                    idx1 = next((j for j, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == prev_d), None)
                    if idx0 is None or idx1 is None:
                        continue
                    gap = (kls[idx0]['open'] - kls[idx1]['close']) / kls[idx1]['close'] * 100
                    if not (4.0 <= gap <= 8.0):
                        continue
                    price = kls[idx0]['open'] * (1 + COST)
                    budget = cash * pos_pct
                    shares = int(min(cash, budget) / price / 100) * 100
                    if shares <= 0:
                        continue
                    cash -= shares * price
                    pos = {'code': code, 'buy_date': d, 'buy_price': price, 'shares': shares}
                    break
        final = cash
        if pos:
            kls = ktbl.get(pos['code'])
            if kls:
                final += pos['shares'] * kls[-1]['close'] * (1 - COST)
        return final, trades

    def objective(weights):
        """两窗交叉: 强市窗全仓 + 弱市窗半仓, 目标=收益60%+胜率40%"""
        results = []
        s_fmt = [f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in strong_dates]
        w_fmt = [f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in weak_dates]
        for dates_fmt, pct in ((s_fmt, 1.0), (w_fmt, 0.5)):
            final, trades = simulate(weights, dates_fmt, pct)
            ret = (final / INIT - 1) * 100
            wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100 if trades else 0
            results.append((ret, wr, len(trades), final))
        ret_avg = (results[0][0] + results[1][0]) / 2
        wr_avg = (results[0][1] + results[1][1]) / 2
        obj = ret_avg * 0.6 + wr_avg * 0.4
        return obj, results

    base_w = cfg4['weights']
    # 搜索: 随机扰动
    best = None
    trials = 600 if '--best' not in sys.argv else 1
    random.seed(42)
    candidates = [dict(base_w)]
    for _ in range(trials - 1):
        w = dict(base_w)
        # 随机调 3 个因子 ±10
        for _ in range(3):
            fac = random.choice(FACTORS)
            w[fac] = max(0, min(40, w[fac] + random.choice([-10, -5, 5, 10])))
        # 归一化到100
        total = sum(w.values())
        if total > 0:
            w = {k: round(v * 100 / total, 1) for k, v in w.items()}
        candidates.append(w)
    for i, w in enumerate(candidates):
        obj, results = objective(w)
        if best is None or obj > best[0]:
            best = (obj, w, results)
        if (i + 1) % 50 == 0:
            print(f'  搜索 {i+1}/{len(candidates)}... 当前最优obj={best[0]:+.1f}')

    obj, w, results = best
    out = []
    out.append('=' * 78)
    out.append('V4权重搜索结果 (目标=收益60%+胜率40%, 强市窗+弱市窗交叉)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    out.append('=' * 78)
    out.append(f'最优目标分: {obj:+.1f}')
    out.append(f'最优权重: ' + ' '.join(f'{k}={w[k]}' for k in FACTORS))
    for label, r in (('强市窗(全仓)', results[0]), ('弱市窗(半仓)', results[1])):
        out.append(f'  {label}: 收益{r[0]:+.1f}% | 胜率{r[1]:.0f}% | {r[2]}笔 | 期末{r[3]:,.0f}')
    out.append(f'基线权重目标分(初始配置):')
    obj0, res0 = objective(dict(base_w))
    out.append(f'  初始权重: obj={obj0:+.1f} | 强市{res0[0][0]:+.1f}%/{res0[0][1]:.0f}%胜 | 弱市{res0[1][0]:+.1f}%/{res0[1][1]:.0f}%胜')
    # 对照: 弱市窗空仓(温度开关口径)下的最优权重表现
    out.append('')
    out.append('对照 — 弱市窗空仓(温度开关口径, 弱市不参与):')
    s_fmt = [f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in strong_dates]
    f_s, tr_s = simulate(w, s_fmt, 1.0)
    ret_s = (f_s / INIT - 1) * 100
    wr_s = sum(1 for t in tr_s if t['pnl'] > 0) / len(tr_s) * 100 if tr_s else 0
    out.append(f'  强市窗全仓: 收益{ret_s:+.1f}% | 胜率{wr_s:.0f}% | {len(tr_s)}笔')
    out.append(f'  弱市窗空仓: 收益0.0% | 0笔 (不参与)')
    out.append(f'  合计(仅强市窗): 收益{ret_s:+.1f}% — 对比用户口径(强弱都做)整体{(results[0][0]+results[1][0])/2:+.1f}%')
    with open(os.path.join(BASE, 'logs', 'backtest_v4_weights.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    # 保存最优权重
    cfg_path = os.path.join(BASE, 'data', 'scoring_config.json')
    with open(cfg_path, encoding='utf-8') as f:
        cfg = json.load(f)
    cfg['v4']['weights'] = w
    cfg['v4']['searched_obj'] = round(obj, 1)
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print('\n最优权重已写回 scoring_config.json v4.weights')


if __name__ == '__main__':
    main()
