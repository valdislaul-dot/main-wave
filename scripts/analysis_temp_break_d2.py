"""
研究: 断板后第2天(d2)分层 — 去留判断第二阶段 (2026-09-19)
=========================================================
背景: d1分层已回答"断板次日怎么办"; 但持仓常拿到"断板次日之后"——
      闽东电力 09-17断板 → 09-18(d1)触板未封+9.07% → 09-19(d2)待判。
      本脚本回答: d2 竞价时点, 已知 T/T+1 全部信息, 该留还是走。

口径(承接 analysis_temp_break_oos.py):
  - T   = 断板日(连板段结束第一根非涨停K线); 连板>=3板; 需有 T+1 与 T+2
  - 特征(决策时点T+2竞价可观测):
      T 日 : gap_T / recover_T(收红) / deep_T
      T+1  : d1_ret(相对T收盘) / d1_lu(反包涨停) / d1_gap / d1_vr(量能环比) / d1振幅
      T+2  : d2_gap(集合竞价, 实时)
  - 标签: d2_ret  = (T+2收 - T+1收)/T+1收   (可比口径, 承接d1)
          d2_intraday = (T+2收 - T+2开)/T+2开 (可执行口径: 竞价不卖 vs 收盘卖)
          d2_lu  = T+2涨停
  - 分段: 训练2016-2022 / 检验2023-2026
"""
import json, os, sys, glob

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
IPO_GUARD = 40


def is_lu(close, prev_close, cyb):
    limit = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit - 0.005


def med(vals):
    s = sorted(vals)
    return s[len(s) // 2] if s else None


def pct_up(vals):
    return sum(1 for v in vals if v > 0) / len(vals) * 100 if vals else 0


def collect():
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
            end = i
            streak = end - start
            # 需要 T(end) / T+1 / T+2 三根
            if streak < 3 or end + 2 >= n or start < IPO_GUARD:
                continue
            b, prev = kl[end], kl[end - 1]
            pc = prev.get('close') or 0
            b_close = b.get('close') or 0
            if not pc or not b_close:
                continue
            t1, t2 = kl[end + 1], kl[end + 2]
            if not t1.get('close') or not t2.get('close') or not t2.get('open'):
                continue
            gap = round((b['open'] - pc) / pc * 100, 2)
            recover = b['close'] > b['open']
            # d1 (T+1) 全天特征
            d1_ret = round((t1['close'] - b_close) / b_close * 100, 2)
            d1_gap = round((t1['open'] - b_close) / b_close * 100, 2)
            v1 = t1.get('volume', 0) or 0
            v0 = b.get('volume', 0) or 0
            d1_vr = round(v1 / v0, 2) if v0 > 0 else None
            hi1, lo1 = t1.get('high') or 0, t1.get('low') or 0
            d1_amp = round((hi1 - lo1) / b_close * 100, 2) if hi1 and lo1 and b_close else None
            d1_lu = lu[end + 1]
            # d2 (T+2)
            c1 = t1['close']
            d2_gap = round((t2['open'] - c1) / c1 * 100, 2)
            d2_ret = round((t2['close'] - c1) / c1 * 100, 2)
            d2_intraday = round((t2['close'] - t2['open']) / t2['open'] * 100, 2)
            evs.append({'y': b['date'][:4], 'date': b['date'], 'code': code, 'streak': streak,
                        'gap': gap, 'recover': recover, 'brk_pct': round((b['close'] - pc) / pc * 100, 2),
                        'd1_ret': d1_ret, 'd1_gap': d1_gap, 'd1_vr': d1_vr, 'd1_amp': d1_amp,
                        'd1_lu': d1_lu, 'd2_gap': d2_gap, 'd2_ret': d2_ret,
                        'd2_intraday': d2_intraday, 'd2_lu': lu[end + 2]})
    return evs


def report(evs, lo, hi, tag):
    sub = [e for e in evs if lo <= e['streak'] <= hi]
    if not sub:
        return None
    print(f'\n{"="*66}\n{tag}: n={len(sub)}')
    print(f'  基线 d2_ret中位 {med([e["d2_ret"] for e in sub]):+.2f}% | '
          f'上涨 {pct_up([e["d2_ret"] for e in sub]):.0f}% | '
          f'涨停 {sum(e["d2_lu"] for e in sub) / len(sub) * 100:.0f}% | '
          f'd2_intraday中位 {med([e["d2_intraday"] for e in sub]):+.2f}%')
    print(f'{"="*66}')

    def seg(label, conds, use_intraday=False):
        key = 'd2_intraday' if use_intraday else 'd2_ret'
        for seg_name, seg_ok in [('训练 2016-2022', lambda e: e['y'] <= '2022'),
                                 ('检验 2023-2026', lambda e: e['y'] >= '2023')]:
            print(f'  [{seg_name}]')
            for cname, cond in conds:
                ss = [e for e in sub if seg_ok(e) and cond(e)]
                if len(ss) < 10:
                    print(f'    {cname}: n={len(ss)}(少)')
                    continue
                vals = [e[key] for e in ss]
                lu_rate = sum(e['d2_lu'] for e in ss) / len(ss) * 100
                print(f'    {cname}: n={len(ss)} d2中位{med(vals):+.2f}% 涨{pct_up(vals):.0f}% 涨停{lu_rate:.0f}%')

    print('\n-- F1 T+1结果形态 (收盘后已知) --')
    seg('d1形态', [
        ('d1反包涨停', lambda e: e['d1_lu']),
        ('d1涨5-10%', lambda e: not e['d1_lu'] and 5 <= e['d1_ret'] < 9.8),
        ('d1涨0-5%', lambda e: 0 <= e['d1_ret'] < 5),
        ('d1跌0-5%', lambda e: -5 < e['d1_ret'] < 0),
        ('d1跌超5%', lambda e: e['d1_ret'] <= -5)])

    print('\n-- F2 d1量能环比 (vol T+1 / vol T) --')
    seg('d1量能', [
        ('缩量<0.7x', lambda e: e['d1_vr'] is not None and e['d1_vr'] < 0.7),
        ('平量0.7-1.5x', lambda e: e['d1_vr'] is not None and 0.7 <= e['d1_vr'] < 1.5),
        ('放量>=1.5x', lambda e: e['d1_vr'] is not None and e['d1_vr'] >= 1.5)])

    print('\n-- F3 d1缺口 (T+1开盘 vs T收盘) --')
    seg('d1缺口', [
        ('高开>=0', lambda e: e['d1_gap'] >= 0),
        ('低开<0', lambda e: e['d1_gap'] < 0)])

    print('\n-- F4 d2竞价gap (实时决策变量) --')
    seg('d2gap', [
        ('高开>=0', lambda e: e['d2_gap'] >= 0),
        ('小低开-3~0', lambda e: -3 <= e['d2_gap'] < 0),
        ('大低开<-3%', lambda e: e['d2_gap'] < -3)])

    print('\n-- F5 组合: d1强势 x d2高开 (闽东型: d1触板未封) --')
    seg('组合', [
        ('d1强(涨>=5%未封)', lambda e: not e['d1_lu'] and e['d1_ret'] >= 5),
        ('d1强+d2高开', lambda e: not e['d1_lu'] and e['d1_ret'] >= 5 and e['d2_gap'] >= 0),
        ('d1强+d2低开', lambda e: not e['d1_lu'] and e['d1_ret'] >= 5 and e['d2_gap'] < 0),
        ('d1中(0~5%)+d2高开', lambda e: 0 <= e['d1_ret'] < 5 and e['d2_gap'] >= 0),
        ('d1中+d2低开', lambda e: 0 <= e['d1_ret'] < 5 and e['d2_gap'] < 0),
        ('d1跌+d2高开', lambda e: e['d1_ret'] < 0 and e['d2_gap'] >= 0),
        ('d1跌+d2低开', lambda e: e['d1_ret'] < 0 and e['d2_gap'] < 0)])

    print('\n-- F6 可执行口径: d2竞价不卖 vs 收盘卖 (d2_intraday) --')
    seg('可执行', [
        ('d1强+d2高开', lambda e: not e['d1_lu'] and e['d1_ret'] >= 5 and e['d2_gap'] >= 0),
        ('d1强+d2低开', lambda e: not e['d1_lu'] and e['d1_ret'] >= 5 and e['d2_gap'] < 0),
        ('d1跌+d2低开', lambda e: e['d1_ret'] < 0 and e['d2_gap'] < 0),
        ('d2大低开<-3', lambda e: e['d2_gap'] < -3),
        ('d1反包涨停', lambda e: e['d1_lu'])], use_intraday=True)

    print('\n-- F7 d1反包涨停 x d2 gap (重新上板后的d2) --')
    seg('反包后', [
        ('d1LU+d2高开', lambda e: e['d1_lu'] and e['d2_gap'] >= 0),
        ('d1LU+d2小低开', lambda e: e['d1_lu'] and -3 <= e['d2_gap'] < 0),
        ('d1LU+d2大低开', lambda e: e['d1_lu'] and e['d2_gap'] < -3)])

    return {'n': len(sub), 'base_d2_med': med([e['d2_ret'] for e in sub]),
            'base_d2_up': pct_up([e['d2_ret'] for e in sub])}


def main():
    evs = collect()
    print(f'\n断板事件(含完整T/T+1/T+2): {len(evs)} 个')
    total = {}
    total['3_4'] = report(evs, 3, 4, '3-4板断板后d2')
    total['5p'] = report(evs, 5, 999, '5板+断板后d2')

    # 稳健性: 逐板级细分
    print(f'\n{"="*66}\n逐板级 d2 基线 (检验段 2023-2026)\n{"="*66}')
    for s in range(3, 9):
        ss = [e for e in evs if e['streak'] == s and e['y'] >= '2023']
        allv = [e for e in evs if e['streak'] == s]
        if len(ss) < 10:
            continue
        print(f'  {s}板: n={len(ss)} d2中位{med([e["d2_ret"] for e in ss]):+.2f}% '
              f'涨{pct_up([e["d2_ret"] for e in ss]):.0f}% 涨停{sum(e["d2_lu"] for e in ss)/len(ss)*100:.0f}%'
              f'  (全样本n={len(allv)})')

    out = os.path.join(BASE, 'logs', 'research_break_d2.json')
    json.dump({'total': len(evs), 'summary': total},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
