"""
研究: 断板因子时间稳定性检验 (2026-09-19)
=========================================
背景: 用户确认方向 — 从"预测成妖"转向"断板后的去留判断"。
      本脚本对断板研究的核心因子做训练段(2016-2022) vs 检验段(2023-2026)
      分层对比, 回答"断板规律是否跨期稳定"。

口径:
  - >=5板连板段结束后的第一根非涨停K线 = 断板日; 仅已结束段; IPO_GUARD=40
  - 因子(断板日收盘/次日开盘可观测): 收红/收阴, 断板日量能环比(brk_vr),
    断板日缺口(gap), 断板日换手(turnover_pct), 次日开盘缺口(d1_gap)
  - 标签: d1(次一交易日)相对断板日收盘的收益 / 上涨率 / 反包涨停率
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
            end = i
            streak = end - start
            if streak < 5 or end >= n or start < IPO_GUARD or end + 1 >= n:
                continue
            b, prev = kl[end], kl[end - 1]
            pc = prev.get('close') or 0
            if not pc:
                continue
            gap = round((b['open'] - pc) / pc * 100, 2)
            brk_pct = round((b['close'] - pc) / pc * 100, 2)
            recover = b['close'] > b['open']
            pv = prev.get('volume', 0) or 0
            brk_vr = round((b.get('volume', 0) or 0) / pv, 2) if pv > 0 else None
            # 连板期均量口径 (观察断板日相对连板期是否放量)
            sv = [kl[j].get('volume', 0) or 0 for j in range(start, end)]
            avg_sv = sum(sv) / len(sv) if sv else 0
            streak_vr = round((b.get('volume', 0) or 0) / avg_sv, 2) if avg_sv > 0 else None
            turn = b.get('turnover_pct')
            d1 = kl[end + 1]
            base = b['close']
            d1_ret = round((d1['close'] - base) / base * 100, 2)
            d1_gap = round((d1['open'] - base) / base * 100, 2)
            evs.append({'y': b['date'][:4], 'code': code, 'streak': streak, 'gap': gap,
                        'brk_pct': brk_pct, 'recover': recover, 'brk_vr': brk_vr,
                        'streak_vr': streak_vr, 'turn': turn, 'd1_ret': d1_ret,
                        'd1_gap': d1_gap, 'd1_lu': lu[end + 1]})

    print(f'\n>=5板断板事件: {len(evs)} 个')
    base_ret = med([e['d1_ret'] for e in evs])
    base_up = pct_up([e['d1_ret'] for e in evs])
    print(f'基线: d1中位 {base_ret:+.2f}% | 上涨率 {base_up:.0f}%')

    def seg_rows(label, conds):
        print(f'\n-- {label} --')
        for seg_name, seg_ok in [('训练 2016-2022', lambda e: e['y'] <= '2022'),
                                 ('检验 2023-2026', lambda e: e['y'] >= '2023')]:
            parts = []
            for cname, cond in conds:
                sub = [e for e in evs if seg_ok(e) and cond(e)]
                if len(sub) < 10:
                    parts.append(f'{cname}: n不足({len(sub)})')
                    continue
                vals = [e['d1_ret'] for e in sub]
                lu_rate = sum(e['d1_lu'] for e in sub) / len(sub) * 100
                parts.append(f'{cname}: n={len(sub)} d1中位{med(vals):+.2f}% 涨{pct_up(vals):.0f}% 反包{lu_rate:.0f}%')
            print(f'  [{seg_name}]')
            for p in parts:
                print(f'    {p}')

    seg_rows('F1 断板日形态', [('收红', lambda e: e['recover']), ('收阴', lambda e: not e['recover'])])
    seg_rows('F2 断板日量能环比 (vs前一日)', [
        ('缩量<1.5x', lambda e: e['brk_vr'] is not None and e['brk_vr'] < 1.5),
        ('1.5-2x', lambda e: e['brk_vr'] is not None and 1.5 <= e['brk_vr'] < 2),
        ('放量>=2x', lambda e: e['brk_vr'] is not None and e['brk_vr'] >= 2)])
    seg_rows('F2b 断板日量能 (vs连板期均量)', [
        ('<1.5x', lambda e: e['streak_vr'] is not None and e['streak_vr'] < 1.5),
        ('>=2x', lambda e: e['streak_vr'] is not None and e['streak_vr'] >= 2)])
    seg_rows('F3 断板日缺口', [
        ('深水低开<=-5%', lambda e: e['gap'] <= -5),
        ('低开-5~0', lambda e: -5 < e['gap'] < 0),
        ('平/高开>=0', lambda e: e['gap'] >= 0)])
    seg_rows('F4 断板日换手 (新)', [
        ('<5%', lambda e: e['turn'] is not None and e['turn'] < 5),
        ('5-10%', lambda e: e['turn'] is not None and 5 <= e['turn'] < 10),
        ('10-20%', lambda e: e['turn'] is not None and 10 <= e['turn'] < 20),
        ('>=20%', lambda e: e['turn'] is not None and e['turn'] >= 20)])
    seg_rows('F5 次日开盘缺口 (d1实时确认)', [
        ('高开>=0', lambda e: e['d1_gap'] >= 0),
        ('小低开-3~0', lambda e: -3 <= e['d1_gap'] < 0),
        ('大低开<-3%', lambda e: e['d1_gap'] < -3)])

    # 组合: 深水拉回收阳(闽东型) 时间稳定性
    seg_rows('F6 深水拉回收阳组合 (gap<=-5 且 收红)', [
        ('闽东型', lambda e: e['gap'] <= -5 and e['recover']),
        ('深水溃败对照组', lambda e: e['gap'] <= -5 and not e['recover'])])

    out = os.path.join(BASE, 'logs', 'research_break_oos.json')
    json.dump({'total': len(evs), 'base_ret': base_ret, 'base_up': base_up},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
