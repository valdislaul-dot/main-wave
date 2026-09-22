"""拆单吸筹(暗盘)假设检验 (2026-09-20)

用户定义: 暗盘 = 主力把大额买卖单拆成多笔小单, 不显山露水完成交易。
可观测推论: 拆单 → 大单(明盘)流出, 但总成交放量, 且价格抗跌(压价吸筹)。
→ 检验: 同样价格区间内, "明盘流出+放量" vs "明盘流出+缩量" 谁后续更强?
   若拆单吸筹成立, 前者应显著更强。

关键控制: 必须锁定当日涨跌幅区间, 否则"放量流出"会被暴跌股主导(动量混淆)。
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
        kby = {c['date']: c for c in kl if c.get('date')}
        dates = sorted(d for d in mf.keys() if d in kby)
        for di, d in enumerate(dates):
            k, m = kby[d], mf[d]
            if not isinstance(m, dict) or 'net' not in m:
                continue
            vol = k.get('volume') or 0
            amt = vol * (k.get('close') or 0)
            if amt <= 0:
                continue
            vr20 = vr5 = None
            if di >= 20:
                pv = [kby[dates[j]].get('volume') or 0 for j in range(di - 20, di)]
                a = sum(pv) / len(pv)
                if a > 0:
                    vr20 = vol / a
            if di >= 5:
                pv = [kby[dates[j]].get('volume') or 0 for j in range(di - 5, di)]
                a = sum(pv) / len(pv)
                if a > 0:
                    vr5 = vol / a
            r = {'code': code, 'date': d, 'net_r': m['net'] / amt * 100,
                 'pct': k.get('pct_change', 0), 'vr20': vr20, 'vr5': vr5}
            for n, key in ((1, 'f1'), (2, 'f2'), (3, 'f3'), (5, 'f5')):
                r[key] = (kby[dates[di + n]]['close'] / k['close'] - 1) * 100 if di + n < len(dates) else None
            if di + 1 < len(dates):
                n1 = kby[dates[di + 1]]
                r['b1'] = (n1['close'] / n1['open'] - 1) * 100 if n1.get('open') else None
            rows.append(r)
        if (i + 1) % 800 == 0:
            print(f'  {i+1} ({len(rows)})')
    print(f'完成 {len(rows)}\n')
    return rows


def line(label, rs, keys=('f1', 'f2', 'f3', 'f5')):
    if not rs:
        return f'{label:<32} n=0'
    n = len(rs)
    out = f'{label:<32} n={n:>6} '
    for k in keys:
        v = [r[k] for r in rs if r.get(k) is not None]
        if v:
            out += f' {k.upper()} {st.mean(v):>+6.2f}%/{sum(1 for x in v if x > 0)/len(v)*100:>3.0f}%'
    b = [r['b1'] for r in rs if r.get('b1') is not None]
    if b:
        out += f'  ┃开→收 {st.mean(b):>+5.2f}%/{sum(1 for x in b if x > 0)/len(b)*100:>3.0f}%'
    return out


def main():
    rows = build()
    # 锁定正常波动区间: 排除涨跌停(右偏)与暴跌(动量混淆)
    base = [r for r in rows if -4 <= r['pct'] <= 6 and r['vr20'] is not None and r.get('f1') is not None]
    print(f'价格区间[-4%,+6%] 基线样本 {len(base)}\n')

    print('=' * 150)
    print('【检验J】拆单吸筹核心: 明盘流出 时, 放量 vs 缩量  (同样价格区间内)')
    print('  拆单理论预测: 明盘流出+放量(有人在小单吸) 后续应强于 明盘流出+缩量(无人接)')
    print('=' * 150)
    for netlab, ncond in (('明盘流出 net<-3%', lambda r: r['net_r'] < -3),
                          ('明盘强流出 net<-10%', lambda r: r['net_r'] < -10),
                          ('【对照】明盘流入 net>+3%', lambda r: r['net_r'] > 3)):
        s = [r for r in base if ncond(r)]
        print(f'── {netlab}  (n={len(s)})')
        for vlab, lo, hi in (('  缩量 <0.8x', 0, 0.8), ('  平量 0.8~1.5x', 0.8, 1.5),
                             ('  放量 1.5~3x', 1.5, 3), ('  大幅放量 >3x', 3, 999)):
            print(line(vlab, [r for r in s if lo <= r['vr20'] < hi]))
        print()

    print('=' * 150)
    print('【检验K】三维: 明盘流出 × 放量 × 价格抗跌  (最贴近"压价吸筹")')
    print('=' * 150)
    out = [r for r in base if r['net_r'] < -3]
    for plab, pcond in (('小涨 0~6% (抗跌+上涨)', lambda r: 0 <= r['pct'] <= 6),
                        ('微跌 -2~0%', lambda r: -2 < r['pct'] < 0),
                        ('中跌 -4~-2%', lambda r: -4 <= r['pct'] <= -2)):
        s = [r for r in out if pcond(r)]
        print(f'── {plab}  (n={len(s)})')
        for vlab, lo, hi in (('  缩量 <1x', 0, 1), ('  放量 1~3x', 1, 3), ('  大幅放量 >3x', 3, 999)):
            print(line(vlab, [r for r in s if lo <= r['vr20'] < hi]))
        print()

    print('=' * 150)
    print('【检验L】持续性: 连续N日"明盘流出" 且 期间放量')
    print('=' * 150)
    by = {}
    for r in rows:
        by.setdefault(r['code'], []).append(r)
    for k in by:
        by[k].sort(key=lambda x: x['date'])
    for N in (3, 5):
        for tag, cond in (('连续流出(net<-3%)', lambda w: all(x['net_r'] < -3 for x in w)),
                          ('连续流出 且 每日放量>1.5x', lambda w: all(x['net_r'] < -3 and (x['vr20'] or 0) > 1.5 for x in w)),
                          ('连续流出 且 每日缩量<0.8x', lambda w: all(x['net_r'] < -3 and (x['vr20'] or 9) < 0.8 for x in w))):
            hit = []
            for code, rs in by.items():
                for i in range(N - 1, len(rs)):
                    w = rs[i - N + 1:i + 1]
                    if len(w) < N:
                        continue
                    if cond(w) and rs[i].get('f1') is not None:
                        hit.append(rs[i])
            print(line(f'{tag} ({N}日)', hit))
        print()

    print('=' * 150)
    print('【检验M】"明盘流出但小单在接"的可观测后果: 换手耗尽后  (T+5/T+10)')
    print('=' * 150)
    for netlab, ncond in (('明盘流出 net<-3% + 放量>1.5x', lambda r: r['net_r'] < -3 and (r['vr20'] or 0) > 1.5),
                          ('明盘流出 net<-3% + 缩量<0.8x', lambda r: r['net_r'] < -3 and (r['vr20'] or 9) < 0.8)):
        s = [r for r in base if ncond(r)]
        print(line(netlab, s, keys=('f1', 'f3', 'f5')))


if __name__ == '__main__':
    main()
