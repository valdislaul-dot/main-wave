"""资金流二次检验 (2026-09-20, 回应用户两点质疑)

用户论点:
 ① 明盘流出1亿+暗盘流入2亿=净流入 → 后续涨。暗盘数据拿不到, 用"量价背离"做代理:
    明盘大幅流出但股价抗跌/上涨 = 存在(看不见的)承接力量 → 后续应更好?
 ② 单变量全市场检验可能掩盖条件效应 → 做多变量协同(量比/成交额/连板/涨跌幅矩阵)

数据: data/money_flow_history/ + data/kline_data/
"""
import json, os, sys, glob
import statistics as st

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(p):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except UnicodeDecodeError:
        with open(p, encoding='gbk') as f:
            return json.load(f)
    except Exception:
        return None


def build():
    print('加载...')
    rows = []
    for i, fp in enumerate(sorted(glob.glob(os.path.join(BASE, 'data', 'money_flow_history', '*.json')))):
        code = os.path.basename(fp)[:-5]
        kp = os.path.join(BASE, 'data', 'kline_data', code + '.json')
        if not os.path.exists(kp):
            continue
        mf, kd = load(fp), load(kp)
        if not mf or not kd:
            continue
        kl = kd.get('data', kd) if isinstance(kd, dict) else kd
        kl = [c for c in kl if c.get('date')]
        kby = {c['date']: c for c in kl}
        dates = sorted(d for d in mf.keys() if d in kby)
        for di, d in enumerate(dates):
            k, m = kby[d], mf[d]
            if not isinstance(m, dict) or 'net' not in m:
                continue
            vol = k.get('volume') or 0
            amt = vol * (k.get('close') or 0)
            if amt <= 0:
                continue
            # 量比: 当日量 / 前20日均量
            vr = None
            if di >= 20:
                pv = [kby[dates[j]].get('volume') or 0 for j in range(di - 20, di)]
                avg = sum(pv) / len(pv)
                if avg > 0:
                    vr = vol / avg
            # 连板数: 往前数连续 pct>=9.8 的天数(含当日)
            streak = 0
            j = di
            while j >= 0 and (kby[dates[j]].get('pct_change') or 0) >= 9.8:
                streak += 1
                j -= 1
            r = {'code': code, 'date': d, 'net_r': m['net'] / amt * 100,
                 'pct': k.get('pct_change', 0), 'amt': amt, 'vr': vr, 'streak': streak}
            for n, key in ((1, 'f1'), (2, 'f2'), (3, 'f3')):
                r[key] = (kby[dates[di + n]]['close'] / k['close'] - 1) * 100 if di + n < len(dates) else None
            if di + 1 < len(dates):
                n1 = kby[dates[di + 1]]
                r['b1'] = (n1['close'] / n1['open'] - 1) * 100 if n1.get('open') else None
                r['g1'] = (n1['open'] / k['close'] - 1) * 100 if n1.get('open') else None
            rows.append(r)
        if (i + 1) % 800 == 0:
            print(f'  {i+1}  ({len(rows)})')
    print(f'完成 {len(rows)} 样本\n')
    return rows


def stat(rs, key):
    v = [r[key] for r in rs if r.get(key) is not None]
    if not v:
        return None, 0
    return st.mean(v), sum(1 for x in v if x > 0) / len(v) * 100


def line(label, rs):
    if not rs:
        return f'{label:<30} n=0'
    n = len(rs)
    m1, w1 = stat(rs, 'f1'); m3, w3 = stat(rs, 'f3')
    mb, wb = stat(rs, 'b1'); mg, _ = stat(rs, 'g1')
    return (f'{label:<30} n={n:>7}  T+1 {m1:>+6.2f}%/{w1:>3.0f}%  T+3 {m3:>+6.2f}%/{w3:>3.0f}%  '
            f'┃ gap {mg:>+5.2f}%  开→收 {mb:>+5.2f}%/{wb:>3.0f}%')


def main():
    rows = build()
    rows = [r for r in rows if r.get('f1') is not None]

    print('=' * 140)
    print('【检验F】"暗盘承接"代理: 明盘大幅流出(net_r<-10%) 时, 当日股价表现 决定后续?')
    print('  逻辑: 若真有隐性承接, 明盘流出但股价抗跌/上涨 的票 → 后续应显著更好')
    print('=' * 140)
    out = [r for r in rows if r['net_r'] < -10]
    print(f'明盘大幅流出总样本 {len(out)}')
    for lab, cond in (('流出 且 当日上涨 (最强背离)', lambda r: r['pct'] > 0),
                      ('流出 且 小跌 -2~0%', lambda r: -2 < r['pct'] <= 0),
                      ('流出 且 中跌 -5~-2%', lambda r: -5 < r['pct'] <= -2),
                      ('流出 且 大跌 <-5%', lambda r: r['pct'] <= -5)):
        print(line('  ' + lab, [r for r in out if cond(r)]))
    print()
    print('反向代理: 明盘大幅流入(net_r>+10%) 但当日滞涨/下跌 → 后续?')
    inn = [r for r in rows if r['net_r'] > 10]
    print(f'明盘大幅流入总样本 {len(inn)}')
    for lab, cond in (('流入 且 当天下跌', lambda r: r['pct'] < 0),
                      ('流入 且 滞涨 0~2%', lambda r: 0 <= r['pct'] < 2),
                      ('流入 且 上涨 2~5%', lambda r: 2 <= r['pct'] < 5),
                      ('流入 且 大涨 >=5%', lambda r: r['pct'] >= 5)):
        print(line('  ' + lab, [r for r in inn if cond(r)]))

    print()
    print('=' * 140)
    print('【检验G】二维矩阵: 主力净流入档 × 当日涨跌幅档  (T+1 均值/胜率)')
    print('=' * 140)
    netb = [('强流出<-15%', -999, -15), ('流出-15~-5%', -15, -5), ('中性-5~5%', -5, 5),
            ('流入5~15%', 5, 15), ('强流入>15%', 15, 999)]
    pctb = [('跌停<=-9%', -99, -9), ('大跌-9~-5%', -9, -5), ('中跌-5~-2%', -5, -2),
            ('小跌-2~0%', -2, 0), ('小涨0~2%', 0, 2), ('中涨2~5%', 2, 5),
            ('大涨5~9.8%', 5, 9.8), ('涨停>=9.8%', 9.8, 99)]
    print(f"{'':<16}" + ''.join(f'{p[0]:>13}' for p in pctb))
    for nb in netb:
        cells = []
        for pb in pctb:
            s = [r for r in rows if nb[1] <= r['net_r'] < nb[2] and pb[1] <= r['pct'] < pb[2]]
            if len(s) < 30:
                cells.append(f'{"n<30":>13}')
            else:
                m, w = stat(s, 'f1')
                cells.append(f'{m:>+7.2f}/{w:>3.0f}%')
        print(f'{nb[0]:<16}' + ''.join(cells))

    print()
    print('=' * 140)
    print('【检验H】多变量协同: 涨停股内 资金流 × 量比 × 连板数')
    print('  项目此前结论"区分度全在涨停/断板状态" → 就在涨停态里做细分')
    print('=' * 140)
    lu = [r for r in rows if r['pct'] >= 9.8]
    print(f'涨停样本 {len(lu)}\n')
    for lab, cond in (('全部涨停', lambda r: True),
                      ('首板 (streak=1)', lambda r: r['streak'] == 1),
                      ('2板', lambda r: r['streak'] == 2),
                      ('3板+', lambda r: r['streak'] >= 3)):
        s = [r for r in lu if cond(r)]
        print(f'── {lab}  n={len(s)}')
        for nb in [('  强流入>15%', 15, 999), ('  流入5~15%', 5, 15), ('  中性-5~5%', -5, 5),
                   ('  流出-15~-5%', -15, -5), ('  强流出<-15%', -999, -15)]:
            print(line('  ' + nb[0], [r for r in s if nb[1] <= r['net_r'] < nb[2]]))
        print()

    print('=' * 140)
    print('【检验I】多变量: 主力流入 × 量比 (全样本)')
    print('=' * 140)
    vrb = [('缩量<1x', 0, 1), ('1~2x', 1, 2), ('2~4x', 2, 4), ('4x+', 4, 999)]
    netb2 = [('强流入>15%', 15, 999), ('流入5~15%', 5, 15), ('中性-5~5%', -5, 5),
             ('流出-15~-5%', -15, -5), ('强流出<-15%', -999, -15)]
    print(f"{'':<16}" + ''.join(f'{v[0]:>15}' for v in vrb))
    for nb in netb2:
        cells = []
        for vb in vrb:
            s = [r for r in rows if nb[1] <= r['net_r'] < nb[2] and r['vr'] is not None and vb[1] <= r['vr'] < vb[2]]
            if len(s) < 100:
                cells.append(f'{"n<100":>15}')
            else:
                m, w = stat(s, 'f1')
                cells.append(f'{m:>+7.2f}/{w:>3.0f}%')
        print(f'{nb[0]:<16}' + ''.join(cells))


if __name__ == '__main__':
    main()
