"""资金流假设检验: 主力净流入 vs 后续收益 (2026-09-20 用户观察验证)

用户假设: 主力持续流入 → 低位承接 → 拉升基础。
关键控制: 只看"下跌日主力仍净流入"(逆势承接), 排除"上涨→主动买多→统计净流入"镜像效应。
口径: net/成交额 归一化(排除市值/成交额差异); 收益用 T+N close/T close-1。
数据: data/money_flow_history/ (新浪, 2024-08~2026-09-03, 500天) + data/kline_data/
"""
import json, os, sys, glob
import statistics as st

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except UnicodeDecodeError:
        with open(path, encoding='gbk') as f:
            return json.load(f)
    except Exception:
        return None


def main():
    print('加载数据...')
    mf_files = sorted(glob.glob(os.path.join(BASE, 'data', 'money_flow_history', '*.json')))
    rows = []
    miss = 0
    for i, fp in enumerate(mf_files):
        code = os.path.basename(fp)[:-5]
        kp = os.path.join(BASE, 'data', 'kline_data', code + '.json')
        if not os.path.exists(kp):
            miss += 1
            continue
        mf = load(fp)
        kd = load(kp)
        if not mf or not kd:
            miss += 1
            continue
        kl = kd.get('data', kd) if isinstance(kd, dict) else kd
        kby = {c['date']: c for c in kl if c.get('date')}
        dates = sorted(d for d in mf.keys() if d in kby)
        for di, d in enumerate(dates):
            k = kby[d]
            m = mf[d]
            if not isinstance(m, dict) or 'net' not in m:
                continue
            amt = (k.get('volume') or 0) * (k.get('close') or 0)
            if amt <= 0:
                continue
            net_r = m['net'] / amt * 100
            rec = {'code': code, 'date': d, 'net_r': net_r,
                   'pct': k.get('pct_change', 0), 'vr': None}
            j = di
            for n, key in ((1, 'f1'), (3, 'f3'), (5, 'f5')):
                if j + n < len(dates):
                    cn = kby[dates[j + n]]['close']
                    rec[key] = (cn / k['close'] - 1) * 100
                else:
                    rec[key] = None
            # T+1 开盘买入口径
            if j + 1 < len(dates):
                n1 = kby[dates[j + 1]]
                rec['b1'] = (n1['close'] / n1['open'] - 1) * 100 if n1.get('open') else None
                rec['g1'] = (n1['open'] / k['close'] - 1) * 100 if n1.get('open') else None
                rec['hi1'] = (n1['high'] / k['close'] - 1) * 100 if n1.get('high') else None
            rows.append(rec)
        if (i + 1) % 500 == 0:
            print(f'  {i+1}/{len(mf_files)}  ({len(rows)} 样本)')
    print(f'完成: {len(rows)} 样本, 缺K线 {miss} 只\n')

    def show(label, rs):
        rs = [r for r in rs if r.get('f1') is not None]
        if not rs:
            print(f'{label}: n=0')
            return
        n = len(rs)
        def col(key):
            v = [r[key] for r in rs if r.get(key) is not None]
            return (st.mean(v), sum(1 for x in v if x > 0) / len(v) * 100) if v else (float('nan'), 0)
        m1, w1 = col('f1'); m3, w3 = col('f3'); m5, w5 = col('f5')
        mb, wb = col('b1'); mg, _ = col('g1')
        print(f'{label:<34} n={n:>7}  T+1 {m1:>+6.2f}%/{w1:>3.0f}%  T+3 {m3:>+6.2f}%/{w3:>3.0f}%  '
              f'T+5 {m5:>+6.2f}%/{w5:>3.0f}%  ┃ 次日gap {mg:>+5.2f}%  开→收 {mb:>+5.2f}%/{wb:>3.0f}%')

    print('=' * 150)
    print('【检验A】全样本: 主力净流入强度(净额/成交额) 分档')
    print('=' * 150)
    allr = rows
    bins = [('强流入 >+15%', 15, 999), ('流入 +5~15%', 5, 15), ('中性 -5~+5%', -5, 5),
            ('流出 -15~-5%', -15, -5), ('强流出 <-15%', -999, -15)]
    for lab, lo, hi in bins:
        show(lab, [r for r in allr if lo <= r['net_r'] < hi])

    print()
    print('=' * 150)
    print('【检验B】★逆势承接: 只看下跌日 (排除"涨→买多→净流入"镜像效应)')
    print('=' * 150)
    down = [r for r in allr if r['pct'] < 0]
    print(f'下跌日总样本 {len(down)}')
    for lab, lo, hi in bins:
        show('  跌  ' + lab, [r for r in down if lo <= r['net_r'] < hi])

    print()
    print('【对照】上涨日')
    up = [r for r in allr if r['pct'] > 0]
    for lab, lo, hi in bins:
        show('  涨  ' + lab, [r for r in up if lo <= r['net_r'] < hi])

    print()
    print('=' * 150)
    print('【检验C】大涨/大跌日 的净流入方向 差异')
    print('=' * 150)
    for lab, cond in (('跌停/近跌停 (pct<=-9%)', lambda r: r['pct'] <= -9),
                      ('大跌 -7~-9%', lambda r: -9 < r['pct'] <= -7),
                      ('中跌 -3~-7%', lambda r: -7 < r['pct'] <= -3),
                      ('小跌 -3~0%', lambda r: -3 < r['pct'] < 0),
                      ('小涨 0~3%', lambda r: 0 < r['pct'] < 3),
                      ('涨停 (pct>=9.8%)', lambda r: r['pct'] >= 9.8)):
        s = [r for r in allr if cond(r)]
        if not s:
            continue
        pos = [r for r in s if r['net_r'] > 5]
        neg = [r for r in s if r['net_r'] < -5]
        print(f'{lab:<28} n={len(s):>6}  净流入占比{sum(1 for r in s if r["net_r"]>0)/len(s)*100:>5.1f}%')
        if pos:
            show('     其中 净流入>+5%', pos)
        if neg:
            show('     其中 净流出<-5%', neg)

    print()
    print('=' * 150)
    print('【检验D】★连续流入: 连续N日净流入(净额>0) 后 的后续表现')
    print('=' * 150)
    by_code = {}
    for r in rows:
        by_code.setdefault(r['code'], []).append(r)
    for k in by_code:
        by_code[k].sort(key=lambda x: x['date'])
    for streak in (2, 3, 5):
        hit = []
        for code, rs in by_code.items():
            for i in range(streak - 1, len(rs)):
                win = rs[i - streak + 1:i + 1]
                if len(win) < streak:
                    continue
                if all(x['net_r'] > 0 for x in win) and rs[i].get('f1') is not None:
                    rec = dict(rs[i])
                    rec['streak_net'] = sum(x['net_r'] for x in win)
                    rec['streak_chg'] = sum(x['pct'] for x in win)
                    hit.append(rec)
        show(f'连续{streak}日净流入', hit)
        # 对照: 同样连续N日, 但净流出
        hit2 = []
        for code, rs in by_code.items():
            for i in range(streak - 1, len(rs)):
                win = rs[i - streak + 1:i + 1]
                if len(win) < streak:
                    continue
                if all(x['net_r'] < 0 for x in win) and rs[i].get('f1') is not None:
                    hit2.append(dict(rs[i]))
        show(f'连续{streak}日净流出 [对照]', hit2)
        print()

    print('=' * 150)
    print('【检验E】★用户案例型: 连续流入 + 期间股价未涨(横盘/下跌) = "低位吸筹"')
    print('=' * 150)
    for streak in (3, 5):
        hit = []
        for code, rs in by_code.items():
            for i in range(streak - 1, len(rs)):
                win = rs[i - streak + 1:i + 1]
                if len(win) < streak:
                    continue
                if all(x['net_r'] > 3 for x in win):
                    chg = sum(x['pct'] for x in win)
                    if chg < 5 and rs[i].get('f1') is not None:
                        hit.append(dict(rs[i]))
        show(f'连续{streak}日净流入>3% 且 累计涨幅<5%', hit)
    # 反向对照: 连续流入但股价已大涨
    for streak in (3, 5):
        hit = []
        for code, rs in by_code.items():
            for i in range(streak - 1, len(rs)):
                win = rs[i - streak + 1:i + 1]
                if len(win) < streak:
                    continue
                if all(x['net_r'] > 3 for x in win):
                    chg = sum(x['pct'] for x in win)
                    if chg >= 15 and rs[i].get('f1') is not None:
                        hit.append(dict(rs[i]))
        show(f'连续{streak}日净流入>3% 且 累计涨幅>=15% [对照]', hit)


if __name__ == '__main__':
    main()
