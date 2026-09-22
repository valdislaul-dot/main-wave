"""
研究: 3-4板断板验证 — 模块触发门槛前置研究 (2026-09-19)
=====================================================
背景: 断板研究现有口径 >=5板 (n=987)。模块若要对 3-4板持仓触发,
      需先验证同一判断框架(断板形态/断板日缺口/次日gap/深水拉回)
      在 3-4板 是否成立, 与 5板+ 对照。

口径: 与 analysis_temp_break_oos.py 完全一致, 仅连板高度分组不同
  - 断板日 = 连板段结束后第一根非涨停K线; 仅已结束段; 需有 d1
  - 标签 = d1相对断板日收盘的收益 / 上涨率 / 反包涨停率
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
            if streak < 3 or end >= n or start < IPO_GUARD or end + 1 >= n:
                continue
            b, prev = kl[end], kl[end - 1]
            pc = prev.get('close') or 0
            if not pc:
                continue
            gap = round((b['open'] - pc) / pc * 100, 2)
            recover = b['close'] > b['open']
            d1 = kl[end + 1]
            base = b['close']
            evs.append({'y': b['date'][:4], 'code': code, 'streak': streak, 'gap': gap,
                        'recover': recover, 'gap24': 0,  # placeholder
                        'd1_ret': round((d1['close'] - base) / base * 100, 2),
                        'd1_gap': round((d1['open'] - base) / base * 100, 2),
                        'd1_lu': lu[end + 1]})

    for tag, lo, hi in [('3-4板断板 (新验证)', 3, 4), ('5板+断板 (对照组)', 5, 999)]:
        sub = [e for e in evs if lo <= e['streak'] <= hi]
        if not sub:
            continue
        br = med([e['d1_ret'] for e in sub])
        bu = pct_up([e['d1_ret'] for e in sub])
        bl = sum(e['d1_lu'] for e in sub) / len(sub) * 100
        print(f'\n{"="*64}\n{tag}: n={len(sub)} | 基线 d1中位 {br:+.2f}% | 上涨 {bu:.0f}% | 反包 {bl:.0f}%\n{"="*64}')

        for seg_name, seg_ok in [('训练 2016-2022', lambda e: e['y'] <= '2022'),
                                 ('检验 2023-2026', lambda e: e['y'] >= '2023')]:
            print(f'  [{seg_name}]')
            for label, conds in [
                ('断板形态', [('收红', lambda e: e['recover']), ('收阴', lambda e: not e['recover'])]),
                ('断板日缺口', [('深水<=-5%', lambda e: e['gap'] <= -5),
                               ('低开-5~0', lambda e: -5 < e['gap'] < 0),
                               ('平/高开>=0', lambda e: e['gap'] >= 0)]),
                ('次日gap', [('高开>=0', lambda e: e['d1_gap'] >= 0),
                            ('小低开-3~0', lambda e: -3 <= e['d1_gap'] < 0),
                            ('大低开<-3', lambda e: e['d1_gap'] < -3)]),
                ('深水拉回(闽东型)', [('拉回收阳', lambda e: e['gap'] <= -5 and e['recover']),
                                     ('溃败', lambda e: e['gap'] <= -5 and not e['recover'])]),
            ]:
                parts = []
                for cname, cond in conds:
                    ss = [e for e in sub if seg_ok(e) and cond(e)]
                    if len(ss) < 10:
                        parts.append(f'{cname}: n={len(ss)}(少)')
                        continue
                    vals = [e['d1_ret'] for e in ss]
                    lu_rate = sum(e['d1_lu'] for e in ss) / len(ss) * 100
                    parts.append(f'{cname}: n={len(ss)} d1中位{med(vals):+.2f}% 涨{pct_up(vals):.0f}% 反包{lu_rate:.0f}%')
                print(f'    {label}:')
                for p in parts:
                    print(f'      {p}')

    out = os.path.join(BASE, 'logs', 'research_break_lowboard.json')
    json.dump({'total_3_4': sum(1 for e in evs if e['streak'] in (3, 4)),
               'total_5p': sum(1 for e in evs if e['streak'] >= 5)},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
